"""Getting yourself to where the deal actually starts.

Deal blogs post from the airports they post from, and for a mid-size city that
mostly means somewhere else. Hiding those deals is the obvious response and the
wrong one: a $400 fare out of Atlanta plus a $160 hop from Huntsville is still a
$560 trip, and refusing to show it is how a Huntsville flyer ends up with an
empty flight list while good deals go by.

So instead of hiding an unreachable origin, price the leg that reaches it and
rank the honest total. Two things make this defensible rather than wishful:

  * Nonstop matters enormously. HSV reaches Atlanta, New York, Chicago, Dallas,
    Miami, LA and Washington without a connection, and those are exactly the
    cities the feeds post from. A positioning leg on a nonstop is a cheap,
    low-risk add-on; one requiring its own connection is neither.
  * Separate tickets carry real risk. A missed connection on a self-connect is
    your problem, not the airline's, and no cost model should quietly bury that.
    It is surfaced as a caveat on the deal rather than priced into it.
"""

from . import places

# Positioning legs are short domestic hops bought close to the deal. They price
# above a plain distance curve, and a leg that needs its own connection prices
# above that again - more segments, less competition, worse timing options.
NONSTOP_MULTIPLIER = 1.0
CONNECTING_MULTIPLIER = 1.35

# Below this, a positioning leg is noise rather than a decision.
MIN_NOTABLE_USD = 25.0

DEFAULTS = {
    "enabled": True,
    "base": "HSV",
    "nonstop_from_base": [],
    "max_positioning_usd": 600,
    "self_connect_warning": True,
}


def config(profile):
    cfg = dict(DEFAULTS)
    cfg.update(profile.get("positioning") or {})
    return cfg


def base_key(profile):
    cfg = config(profile)
    return places.resolve(cfg.get("base") or "")


def nonstop_keys(profile):
    """The cities the base airport reaches without a connection, as city keys."""
    cfg = config(profile)
    keys = set()
    for code in cfg.get("nonstop_from_base", []):
        key = places.resolve(code)
        if key:
            keys.add(key)
    return keys


def estimate(origin_key, profile, fare_curve):
    """What it costs one person to reach `origin_key` from the base, roundtrip.

    `fare_curve` is score.expected_flight_usd, injected rather than imported so
    that the fare model stays in one place and this module stays testable.

    Returns None when there is no base, no route, or the origin *is* the base.
    """
    cfg = config(profile)
    if not cfg.get("enabled"):
        return None
    base = base_key(profile)
    if not base or not origin_key or origin_key == base:
        return None

    fare = fare_curve(base, origin_key, "economy")
    if fare is None:
        return None

    nonstop = origin_key in nonstop_keys(profile)
    fare *= NONSTOP_MULTIPLIER if nonstop else CONNECTING_MULTIPLIER
    return {
        "from": base,
        "to": origin_key,
        "nonstop": nonstop,
        "per_person_usd": fare,
    }


def apply(deal, profile, rates, fare_curve, home_keys):
    """Attach positioning cost to a deal, or explain why none is needed.

    Mutates deal.trip and returns the per-party USD cost to add (0.0 when none).
    """
    trip = deal.trip
    trip["positioning"] = None

    if not deal.origin or deal.origin in home_keys:
        return 0.0

    # A package saying "flights from Vienna" really does require you to be in
    # Vienna, and costs whatever that costs. A package saying "Lisbon to Porto"
    # names its own itinerary and starts wherever you live. Only the first kind
    # is a departure, which is why the parser records which one it saw.
    if not deal.origin_is_departure:
        return 0.0

    est = estimate(deal.origin, profile, fare_curve)
    if est is None:
        return 0.0

    travelers = max(1, int(profile.get("travelers", 1)))
    party_usd = est["per_person_usd"] * travelers
    est["party_usd"] = party_usd
    est["party_home"] = rates.convert(party_usd, "USD",
                                      (profile.get("home_currency") or "USD"))
    trip["positioning"] = est
    return party_usd


def describe(deal, profile, money):
    """A short human note for the deal card, or None."""
    est = (deal.trip or {}).get("positioning")
    if not est or est["party_usd"] < MIN_NOTABLE_USD:
        return None
    return "add %s to reach %s from %s%s" % (
        money(est.get("party_home")),
        places.city(est["to"])["name"],
        (places.city(est["from"]) or {}).get("name", est["from"]),
        "" if est["nonstop"] else " (connects)")


def caveat(deal, profile):
    """The risk that does not belong in a price."""
    cfg = config(profile)
    est = (deal.trip or {}).get("positioning")
    if not est or not cfg.get("self_connect_warning"):
        return None
    if est["party_usd"] < MIN_NOTABLE_USD:
        return None
    return "separate tickets - a missed connection is on you"


def too_far(deal, profile):
    """True when the positioning leg costs more than the profile tolerates."""
    cfg = config(profile)
    est = (deal.trip or {}).get("positioning")
    if not est:
        return False
    ceiling = cfg.get("max_positioning_usd")
    return bool(ceiling) and est["per_person_usd"] > ceiling
