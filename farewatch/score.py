"""Ranking deals against one person's actual constraints.

The deal blogs broadcast: they find a $340 fare to Lisbon and send it to everyone,
most of whom cannot fly those dates, do not live near that airport, and are not
interested in Lisbon. Everything here exists to undo that - to ask whether a
given deal is good *for you*, and to say why in words you can check.

Every component returns 0..1 and carries its own explanation, so a score is
always auditable rather than a number you have to take on faith.
"""

import re
from datetime import datetime, timezone

from . import baselines as baselines_mod
from . import costs, faremodel, places, positioning
from .models import fingerprint

# The fare curve lives in faremodel so that baselines.py can use it too
# without the two importing each other. Re-exported here because it has
# always been part of this module's surface.
CABIN_MULT = faremodel.CABIN_MULT
FARE_BASE_USD = faremodel.FARE_BASE_USD
FARE_PER_KM = faremodel.FARE_PER_KM
expected_flight_usd = faremodel.expected_flight_usd

CRUISE_FARE_PER_NIGHT = 200.0     # mainstream balcony, per person
PACKAGE_AIR_PER_DAY = 90.0        # amortised airfare inside a package price

DEFAULT_WEIGHTS = {
    "value": 28,
    "reachable": 18,
    "affordable": 15,
    "wishlist": 12,
    "fx": 8,
    "fresh": 8,
    "timing": 6,
    "urgency": 5,
}

MONTHS = ("january february march april may june july august september "
          "october november december").split()
SEASON_MONTHS = {
    "winter": ("december", "january", "february"),
    "summer": ("june", "july", "august"),
    "spring": ("march", "april", "may"),
    "autumn": ("september", "october", "november"),
    "fall": ("september", "october", "november"),
}
_MONTH_RE = re.compile(r"\b(" + "|".join(MONTHS + list(SEASON_MONTHS)) + r")\b", re.I)


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------
# is it actually cheap?
# --------------------------------------------------------------------------

def value_component(deal, trip, rates, history=None):
    """How far below the expected price this is, as 0..1 plus an explanation.

    Compares the headline price to a headline-shaped expectation. Deal copy
    quotes a unit - one seat, one room-night, one person on a package - so the
    party-total used for budgeting is the wrong number to judge value with, and
    dividing it back down by party size double-counts.

    Where enough history exists for the route, the eyeballed fare curve gives way
    to what we have actually observed, and the wording changes with it: a
    percentile among tracked deals is a claim that can be checked, where "% below
    typical" against a fitted line was always half guess.
    """
    nights = trip.get("nights") or 1
    unit = rates.to_usd(deal.price, deal.currency)
    if unit is None:
        return 0.5, None

    _ground, lodging = costs.daily_rates(deal.destination, "mid")
    expected = None
    actual = unit

    if deal.kind == "flight" and deal.origin:
        # Headline is one seat.
        expected = expected_flight_usd(deal.origin, deal.destination, deal.cabin)
    elif deal.kind == "hotel" and lodging:
        # Headline is a room, either for one night or for the whole stay.
        expected = (lodging if deal.basis in ("per_night", "per_room_night")
                    else lodging * nights)
    elif deal.kind == "cruise":
        expected = CRUISE_FARE_PER_NIGHT * nights
    elif deal.kind == "package" and lodging:
        # Headline is one person: half a room plus their share of the airfare.
        expected = (lodging / 2.0 + PACKAGE_AIR_PER_DAY) * nights

    # Let observed history correct the model where it has earned the right to.
    # The lookup walks from this exact route out to "flights of roughly this
    # length", stopping at the first level with enough evidence, so a correction
    # is available long before any single route has been seen four times.
    found = None
    modelled = expected          # keep the uncalibrated value; the percentile needs it
    if history is not None:
        if deal.kind == "flight":
            found = history.flight(deal.origin, deal.destination, deal.cabin)
        elif deal.kind == "hotel":
            found = history.stay(deal.destination)
        if found:
            expected = history.calibrate(expected, found)

    if not expected or expected <= 0:
        return 0.5, None

    discount = 1.0 - (actual / expected)
    # Anything past 60% off a reference this rough is more likely a parse error
    # or a per-person/total mixup than a real fare, so it stops earning credit.
    score = _clip((discount + 0.25) / 0.85)

    # When the headline never said how long the trip is, the expectation was
    # built on an assumed duration and deserves less confidence. A "$249 New
    # Orleans trip w/flights" scored against an assumed week looks 79% below
    # market; it is really a long weekend. Pull such scores toward neutral and
    # say so rather than quietly ranking on a guess.
    assumed_duration = deal.nights is None and deal.kind in ("package", "cruise")
    if assumed_duration:
        score = 0.5 + (score - 0.5) * 0.5
        discount *= 0.5

    trip["baseline"] = {
        "expected_usd": expected,
        "history_weight": round(found.weight, 2) if found else 0.0,
        "samples": found.n if found else 0,
        "level": found.level if found else None,
    }

    # Prefer the checkable claim when history is carrying real weight. The note
    # names the level it rests on, because "cheaper than most fares we track to
    # Bangkok" and "...on routes this length" are different strengths of claim.
    if found and found.weight >= 0.5 and modelled:
        # Observations are stored as observed/modelled, so this deal has to be
        # expressed the same way before it can be placed among them. Comparing
        # against the *calibrated* expectation would measure the deal against a
        # figure already moved by the very sample it is being ranked in.
        beaten = found.sample.percentile_of(actual / modelled)
        scope = found.describe(deal.destination, deal.kind)
        suffix = " " + scope if scope else ""
        if beaten >= 0.6:
            return score, "cheaper than %d of the %d tracked%s" % (
                round(beaten * found.n), found.n, suffix)
        if beaten <= 0.2:
            return score, "pricier than most tracked%s" % suffix
        return score, None

    # No history backed this expectation, so it rests entirely on the fare curve
    # - and the curve has been measured wrong. A price-check of the top-ranked
    # deal (Asiana LAX-BKK, $741) found the real market fare was $742 and Google
    # rated it "typical", where the curve had called it 25% below. Fares scale
    # sub-linearly with distance, so a straight line overestimates long haul
    # badly. The figure is still the best guide available, but it is an estimate
    # and gets labelled as one rather than stated to the percent.
    if discount >= 0.15:
        note = "est. %.0f%% below typical%s" % (
            discount * 100, " (duration assumed)" if assumed_duration else "")
    elif discount <= -0.20:
        note = "est. %.0f%% above typical" % (-discount * 100)
    else:
        note = None
    return score, note


# --------------------------------------------------------------------------
# can you even take it?
# --------------------------------------------------------------------------

def home_keys(profile):
    keys = set()
    for name in profile.get("home_cities", []):
        key = places.resolve(name)
        if key:
            keys.add(key)
    for code in profile.get("home_airports", []):
        key = places.resolve(code)
        if key:
            keys.add(key)
    return keys


def reachable_component(deal, home):
    if deal.origin and not deal.origin_is_departure:
        # The origin is a stop on the itinerary, not somewhere you must get to.
        return 0.55, None
    if not deal.origin:
        # Hotels, cruises and packages rarely name an origin, and for those the
        # absence is genuinely neutral rather than bad news.
        return (0.55, None) if deal.kind != "flight" else (0.4, "origin not stated")
    if deal.origin in home:
        return 1.0, "departs %s" % places.label(deal.origin)

    # Once a positioning leg has been priced into the total, an unreachable
    # origin is an inconvenience rather than a disqualification - the money is
    # already counted by `affordable`, so scoring it near zero here would charge
    # for the same problem twice. What is left to grade is the hassle, and a
    # nonstop hop is much less of it than one that connects.
    est = (deal.trip or {}).get("positioning")
    if est:
        return (0.6, None) if est.get("nonstop") else (0.3, None)
    return 0.05, "departs %s, not one of yours" % places.label(deal.origin)


def wishlist_component(deal, profile):
    wishlist = {w.strip().lower() for w in profile.get("wishlist", [])}
    if not wishlist:
        return 0.5, None
    city = places.city(deal.destination)
    country = places.country_of(deal.destination)
    names = {deal.destination}
    if city:
        names.add(city["name"].lower())
        names.add(city["country"].lower())
    if country:
        names.add(country["name"].lower())
    if names & wishlist:
        return 1.0, "on your list"
    return 0.35, None


def affordable_component(trip, profile):
    budget = profile.get("max_trip_budget")
    total = trip.get("total_home")
    if not budget or total is None:
        return 0.5, None
    ratio = total / float(budget)
    if ratio > 1.0:
        return 0.0, "over your %s budget" % _money(budget, trip.get("home_currency"))
    return _clip((1.5 - ratio) / 1.0), None


def fx_component(trip):
    tailwind = trip.get("tailwind")
    if tailwind is None:
        return 0.5, None
    return _clip(0.5 + tailwind * 3.0), trip.get("tailwind_note")


def fresh_component(deal):
    if not deal.published:
        return 0.5, None
    try:
        published = datetime.fromisoformat(deal.published)
    except ValueError:
        return 0.5, None
    age_days = (datetime.now(timezone.utc) - published).total_seconds() / 86400.0
    if age_days < 1:
        return 1.0, "posted today"
    if age_days < 3:
        return 0.85, None
    if age_days > 21:
        return 0.1, "%.0f days old" % age_days
    return _clip(1.0 - (age_days - 1) / 20.0), None


def timing_component(deal, profile):
    preferred = {m.strip().lower() for m in profile.get("preferred_months", [])}
    if not preferred:
        return 0.5, None
    found = {m.lower() for m in _MONTH_RE.findall(deal.title)}
    expanded = set()
    for token in found:
        expanded.update(SEASON_MONTHS.get(token, (token,)))
    if not expanded:
        return 0.6, None
    if expanded & preferred:
        return 1.0, "travels in %s" % ", ".join(sorted(expanded & preferred)[:2])
    return 0.2, "travels outside the months you picked"


def urgency_component(deal):
    deadline = (deal.trip or {}).get("deadline")
    if deadline:
        return 1.0, "book by %s" % deadline
    return 0.5, None


# --------------------------------------------------------------------------

def _money(amount, currency="USD"):
    if amount is None:
        return "-"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "C$",
              "AUD": "A$", "JPY": "¥"}.get((currency or "USD").upper(), "")
    if symbol:
        return "%s%s" % (symbol, format(int(round(amount)), ","))
    return "%s %s" % (format(int(round(amount)), ","), currency)


def score_deal(deal, profile, rates, home=None, history=None):
    """Attach trip costs, a 0-100 score and the reasons behind it."""
    home = home if home is not None else home_keys(profile)
    weights = dict(DEFAULT_WEIGHTS)
    weights.update(profile.get("weights") or {})

    trip = costs.breakdown(deal, profile, rates)
    deal.trip.update(trip)

    # Price the leg that gets you to where the deal starts, before anything is
    # scored, so the ranking sees the honest total rather than the advertised one.
    pos_usd = positioning.apply(deal, profile, rates, expected_flight_usd, home)
    if pos_usd:
        costs.add_cost(deal.trip, "positioning_cost", pos_usd, rates)
    trip = deal.trip

    parts = {
        "value": value_component(deal, trip, rates, history),
        "reachable": reachable_component(deal, home),
        "affordable": affordable_component(trip, profile),
        "wishlist": wishlist_component(deal, profile),
        "fx": fx_component(trip),
        "fresh": fresh_component(deal),
        "timing": timing_component(deal, profile),
        "urgency": urgency_component(deal),
    }

    total_weight = sum(weights.get(k, 0) for k in parts) or 1
    raw = sum(parts[k][0] * weights.get(k, 0) for k in parts)
    deal.score = round(100.0 * raw / total_weight, 1)
    deal.reasons = [note for _v, note in parts.values() if note]

    note = positioning.describe(deal, profile, lambda v: _money(v, trip.get(
        "home_currency", "USD")))
    if note:
        deal.reasons.append(note)
    caveat = positioning.caveat(deal, profile)
    if caveat:
        deal.reasons.append(caveat)
    deal.trip["components"] = {k: round(v, 3) for k, (v, _n) in parts.items()}
    return deal


def excluded(deal, profile):
    """Hard filters. Returns a reason string when the deal should never be shown."""
    avoid = {a.strip().lower() for a in profile.get("avoid", [])}
    if avoid:
        country = places.country_of(deal.destination)
        names = {deal.destination}
        if country:
            names.add(country["name"].lower())
        if names & avoid:
            return "on your avoid list"
    # How to treat a flight leaving from somewhere you are not.
    #   position - price the leg that reaches it and rank the honest total
    #   hide     - drop it, the old behaviour
    #   show     - leave it alone and price nothing
    # `require_reachable_origin: true` still means "hide" for anyone who set it
    # before this existed, but only when a policy has not been stated outright.
    policy = profile.get("unreachable_origins")
    if policy is None:
        policy = "hide" if profile.get("require_reachable_origin") else "position"
    if policy == "hide" and deal.origin and deal.origin_is_departure:
        if deal.origin not in home_keys(profile):
            return "not reachable from your airports"
    if positioning.too_far(deal, profile):
        return "positioning flight costs more than your ceiling"
    max_price = profile.get("hard_price_ceiling")
    if max_price and deal.price_usd and deal.price_usd > max_price:
        return "above your hard price ceiling"
    return None


def rank(deals, profile, rates, history=None):
    """Score, dedupe and sort. The same fare on four blogs collapses to one row."""
    home = home_keys(profile)
    scored = []
    for deal in deals:
        why = excluded(deal, profile)
        if why:
            continue
        deal = score_deal(deal, profile, rates, home, history)
        # The positioning ceiling can only be applied after scoring, because
        # scoring is what prices the leg. Checking it in excluded() looked right
        # and silently never fired, which let $873-per-person repositioning to
        # Prague rank as though it were free.
        if positioning.too_far(deal, profile):
            continue
        # Only now does the deal have a USD price, which is what makes the same
        # fare on four different blogs collapse to one row. Fingerprinting at
        # parse time silently fell back to the URL and deduped nothing.
        deal.fingerprint = fingerprint(deal)
        scored.append(deal)

    best = {}
    for deal in scored:
        seen = best.get(deal.fingerprint)
        if seen is None or deal.score > seen.score:
            if seen is not None:
                deal.trip["also_seen_on"] = sorted(
                    set(seen.trip.get("also_seen_on", []) + [seen.source]))
            best[deal.fingerprint] = deal
        else:
            seen.trip.setdefault("also_seen_on", [])
            if deal.source not in seen.trip["also_seen_on"]:
                seen.trip["also_seen_on"].append(deal.source)

    out = sorted(best.values(), key=lambda d: d.score, reverse=True)
    return out
