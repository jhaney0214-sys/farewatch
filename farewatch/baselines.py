"""What we have actually observed, as opposed to what the model guesses.

`score.py` judges value against a fare curve fitted by eye. That was the only
option on day one, and it is wrong in absolute terms for any single route - New
York to Punta Cana reads as "37% above typical" because a straight line through
distance does not know Caribbean routes price high. Every run banks real prices
in sqlite. This module reads that pile back and corrects the curve.

Two design decisions carry the whole thing.

Observations are ratios, not prices
-----------------------------------
Keying on the exact route was the obvious approach and it does not work. A route
only gains an observation when a genuinely *different* offer appears on it, which
for a given city pair happens a handful of times a year - so most routes sit at
one or two observations forever and the correction never activates. Measured on
real data: 26 of 27 routes had exactly one.

So every observation is stored as `observed / modelled` instead. A ratio of 0.8
means "20% under what the curve predicts" and means the same thing on a 900km hop
as on a 12,000km haul. That makes observations from *different* routes poolable,
which is what lets evidence accumulate at all. The correction is then a multiplier
on the curve rather than a replacement for it, so route-specific shape is kept
and only the systematic error is removed.

Coarser keys catch what finer ones miss
---------------------------------------
Each observation is filed under several keys at once, from exact route down to
"economy flights of roughly this length". A lookup walks specific to general and
stops at the first level with enough evidence. Precision where the data supports
it, coverage everywhere else, and the level used is reported so a claim can say
what it is actually based on.

The trap worth naming
---------------------
These are *deal* prices - a sample biased low by construction, since nobody posts
an average fare to a deal blog. Two consequences pulling opposite ways:

  * For **judging a deal**, comparing against other deals beats a guessed market
    rate, provided the claim is framed as a percentile among tracked deals. It is,
    and this module never calls it a discount off retail.
  * For **estimating a trip's cost**, deal prices are the wrong input entirely.
    Book your own hotel beside a flight deal and you pay near market, not near
    promotional. So nothing here feeds the cost model; `costs.py` keeps using the
    hand-authored figures, and `fw.py calibrate` exists to let a human compare
    the two and edit them deliberately.
"""

import statistics
from datetime import datetime, timedelta, timezone

from . import costs, faremodel, places

# Below this many observations, a level has no opinion worth hearing.
MIN_SAMPLES = 4
# At this many, trust the observed correction completely.
FULL_SAMPLES = 12
# What a level is worth the moment it reaches MIN_SAMPLES.
MIN_WEIGHT = 0.25
# Prices drift. Anything older than this stops counting.
WINDOW_DAYS = 120

# A ratio outside this range is a parse error far more often than a real price,
# and letting one into a median poisons every lookup that reaches that level.
MIN_RATIO = 0.15
MAX_RATIO = 6.0

# Specific to general. The first level with MIN_SAMPLES wins.
FLIGHT_LEVELS = ("route", "destination", "country", "distance", "cabin")
LODGING_LEVELS = ("city", "country", "global")


def _cutoff(window_days):
    return (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()


def confidence(n):
    """0.0 below MIN_SAMPLES, MIN_WEIGHT at it, ramping to 1.0 at FULL_SAMPLES.

    The floor matters. Ramping from zero meant a level that had just reached the
    threshold carried exactly no weight, so a lookup skipped it and fell through
    to a coarser level that was no better informed - MIN_SAMPLES silently meant
    "one more than MIN_SAMPLES". Crossing the bar should count for something.
    """
    if n < MIN_SAMPLES:
        return 0.0
    if n >= FULL_SAMPLES:
        return 1.0
    span = float(FULL_SAMPLES - MIN_SAMPLES)
    return MIN_WEIGHT + (1.0 - MIN_WEIGHT) * (n - MIN_SAMPLES) / span


def nightly_rate(unit_usd, basis, nights):
    """Reduce a hotel headline price to one night, or None if it cannot be.

    Lodging observations only compare to each other if they mean the same thing.
    A weeklong getaway at $779 and a room at $159 a night are both real prices,
    and averaging them raw produced a $414 "typical night" for Phuket, roughly
    eight times what a night there costs.
    """
    if not unit_usd or unit_usd <= 0:
        return None
    if basis in ("per_night", "per_room_night"):
        return unit_usd
    if basis == "total" and nights and nights > 0:
        return unit_usd / float(nights)
    if basis == "total":
        # A stay price with no stated length cannot be reduced to a night, and
        # guessing here is how the average gets poisoned.
        return None
    if basis == "per_person" and nights and nights > 0:
        # Two people usually share the room the rate is quoted against.
        return (unit_usd * 2) / float(nights)
    return None


class Sample:
    """Observed ratios against the model, for one key at one level."""

    __slots__ = ("ratios", "prices", "since")

    def __init__(self, ratios=None, prices=None, since=None):
        self.ratios = list(ratios or [])
        self.prices = list(prices or [])
        self.since = since

    def __len__(self):
        return len(self.ratios)

    def add(self, ratio, price, seen):
        self.ratios.append(ratio)
        self.prices.append(price)
        if self.since is None or (seen and seen < self.since):
            self.since = seen

    @property
    def median_ratio(self):
        return statistics.median(self.ratios) if self.ratios else None

    @property
    def cheapest(self):
        return min(self.prices) if self.prices else None

    def percentile_of(self, ratio):
        """Fraction of observations this ratio undercuts, 0..1."""
        if not self.ratios:
            return None
        return sum(1 for r in self.ratios if ratio < r) / float(len(self.ratios))


class Lookup:
    """What a baseline query found: a sample, the level it came from, its weight."""

    __slots__ = ("sample", "level", "weight")

    def __init__(self, sample=None, level=None, weight=0.0):
        self.sample = sample
        self.level = level
        self.weight = weight

    def __bool__(self):
        return self.sample is not None and self.weight > 0

    @property
    def n(self):
        return len(self.sample) if self.sample else 0

    def describe(self, destination=None, kind="flight"):
        """How to phrase a claim built on this level, or None.

        The level is part of the claim. "Cheaper than most fares we track to
        Bangkok" and "...on routes this length" are different strengths of
        evidence, and a reader deserves to know which one they are being given.
        """
        if not self:
            return None
        # A flight goes *to* somewhere; a room is *in* it.
        preposition = "in" if kind == "hotel" else "to"
        city = places.city(destination) if destination else None
        country = places.country_of(destination) if destination else None

        if self.level == "route":
            return "on this route"
        if self.level in ("destination", "city") and city:
            return "%s %s" % (preposition, city["name"])
        if self.level == "country" and country:
            return "%s %s" % (preposition, country["name"])
        if self.level == "distance":
            return "on routes this length"
        if self.level == "cabin":
            return "in this cabin"
        if self.level == "global":
            return "across everything tracked"
        return None


class Baselines:
    """Observed history, filed at several levels of specificity."""

    def __init__(self, flights=None, lodging=None, window_days=WINDOW_DAYS):
        # {level: {key: Sample}}
        self.flights = flights or {level: {} for level in FLIGHT_LEVELS}
        self.lodging = lodging or {level: {} for level in LODGING_LEVELS}
        self.window_days = window_days

    # -- filing -------------------------------------------------------------

    def _file(self, table, level, key, ratio, price, seen):
        if key is None:
            return
        table.setdefault(level, {}).setdefault(key, Sample()).add(ratio, price, seen)

    def add_flight(self, origin, destination, cabin, price_usd, seen=None):
        """File one fare under every level it belongs to."""
        model = faremodel.expected_flight_usd(origin, destination, cabin)
        if not model or not price_usd:
            return False
        ratio = price_usd / model
        if not MIN_RATIO <= ratio <= MAX_RATIO:
            return False
        cabin = cabin or "economy"
        country = places.city(destination)
        country = country["country"] if country else None
        band = faremodel.distance_band(origin, destination)

        self._file(self.flights, "route", (origin, destination, cabin), ratio, price_usd, seen)
        self._file(self.flights, "destination", (destination, cabin), ratio, price_usd, seen)
        self._file(self.flights, "country", (country, cabin), ratio, price_usd, seen)
        self._file(self.flights, "distance", (band, cabin), ratio, price_usd, seen)
        self._file(self.flights, "cabin", (cabin,), ratio, price_usd, seen)
        return True

    def add_stay(self, destination, nightly_usd, seen=None):
        _ground, authored = costs.daily_rates(destination, "mid")
        if not authored or not nightly_usd:
            return False
        ratio = nightly_usd / authored
        if not MIN_RATIO <= ratio <= MAX_RATIO:
            return False
        city = places.city(destination)
        country = city["country"] if city else None

        self._file(self.lodging, "city", destination, ratio, nightly_usd, seen)
        self._file(self.lodging, "country", country, ratio, nightly_usd, seen)
        self._file(self.lodging, "global", "all", ratio, nightly_usd, seen)
        return True

    # -- lookups ------------------------------------------------------------

    def _walk(self, table, levels, keys):
        """Most specific level with enough evidence, else an empty Lookup."""
        for level in levels:
            key = keys.get(level)
            if key is None:
                continue
            sample = table.get(level, {}).get(key)
            if sample is None:
                continue
            weight = confidence(len(sample))
            if weight > 0:
                return Lookup(sample, level, weight)
        return Lookup()

    def flight(self, origin, destination, cabin="economy"):
        cabin = cabin or "economy"
        city = places.city(destination) if destination else None
        country = city["country"] if city else None
        return self._walk(self.flights, FLIGHT_LEVELS, {
            "route": (origin, destination, cabin) if origin and destination else None,
            "destination": (destination, cabin) if destination else None,
            "country": (country, cabin) if country else None,
            "distance": ((faremodel.distance_band(origin, destination), cabin)
                         if origin and destination else None),
            "cabin": (cabin,),
        })

    def stay(self, destination):
        city = places.city(destination) if destination else None
        country = city["country"] if city else None
        return self._walk(self.lodging, LODGING_LEVELS, {
            "city": destination,
            "country": country,
            "global": "all",
        })

    # -- the part the scorer uses ------------------------------------------

    def calibrate(self, model_usd, lookup):
        """Correct a modelled expectation by the observed ratio.

        Returns the corrected value. The correction is a multiplier, so the
        curve keeps whatever route-specific shape it had and only its systematic
        error is removed.
        """
        if model_usd is None or not lookup:
            return model_usd
        ratio = lookup.sample.median_ratio
        if ratio is None:
            return model_usd
        # Blend toward the observed ratio as evidence grows.
        adjusted = 1.0 - lookup.weight + lookup.weight * ratio
        return model_usd * adjusted

    def summary(self):
        out = {"window_days": self.window_days}
        for level in FLIGHT_LEVELS:
            samples = self.flights.get(level, {})
            out["flight_" + level] = len(samples)
            out["flight_" + level + "_ready"] = sum(
                1 for s in samples.values() if len(s) >= MIN_SAMPLES)
        for level in LODGING_LEVELS:
            samples = self.lodging.get(level, {})
            out["lodging_" + level] = len(samples)
            out["lodging_" + level + "_ready"] = sum(
                1 for s in samples.values() if len(s) >= MIN_SAMPLES)
        out["ready"] = sum(out["flight_%s_ready" % lv] for lv in FLIGHT_LEVELS) \
            + sum(out["lodging_%s_ready" % lv] for lv in LODGING_LEVELS)
        return out


def load(conn, window_days=WINDOW_DAYS):
    """Build baselines from the deals table. Never raises on a thin database."""
    history = Baselines(window_days=window_days)
    if conn is None:
        return history
    cutoff = _cutoff(window_days)

    for row in conn.execute(
            "SELECT origin, destination, cabin, unit_usd, first_seen FROM deals"
            " WHERE kind = 'flight' AND destination IS NOT NULL"
            "   AND unit_usd IS NOT NULL AND first_seen >= ?", (cutoff,)):
        history.add_flight(row["origin"], row["destination"],
                           row["cabin"] or "economy", row["unit_usd"],
                           row["first_seen"])

    for row in conn.execute(
            "SELECT destination, unit_usd, nights, basis, first_seen FROM deals"
            " WHERE kind = 'hotel' AND destination IS NOT NULL"
            "   AND unit_usd IS NOT NULL AND first_seen >= ?", (cutoff,)):
        nightly = nightly_rate(row["unit_usd"], row["basis"], row["nights"])
        if nightly is not None:
            history.add_stay(row["destination"], nightly, row["first_seen"])

    return history


def divergences(history, authored_lookup, min_samples=MIN_SAMPLES):
    """Where observed nightly prices disagree sharply with the authored cost data.

    Returns rows for human review, never an automatic correction. Deals sit below
    market by construction, so a moderate gap is expected and healthy; it is the
    extremes that suggest an authored number is simply wrong.
    """
    out = []
    for destination, sample in history.lodging.get("city", {}).items():
        if len(sample) < min_samples:
            continue
        authored = authored_lookup(destination)
        if not authored:
            continue
        observed = statistics.median(sample.prices)
        out.append({
            "destination": destination,
            "observed_median": observed,
            "authored": authored,
            "ratio": observed / authored,
            "n": len(sample),
        })
    out.sort(key=lambda r: abs(1.0 - r["ratio"]), reverse=True)
    return out
