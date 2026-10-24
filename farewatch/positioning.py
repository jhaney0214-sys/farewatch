"""Getting yourself to where the deal actually starts.

Deal blogs post from the airports they post from, and for a mid-size city that
mostly means somewhere else. Hiding those deals is the obvious response and the
wrong one: a $400 fare out of Atlanta plus a $160 hop from a regional airport is
still a $560 trip, and refusing to show it is how anyone flying from a small
field ends up with an empty flight list while good deals go by.

So instead of hiding an unreachable origin, price the leg that reaches it and
rank the honest total. Two things make this defensible rather than wishful:

  * Nonstop matters enormously. A regional airport typically reaches the big
    hubs - Atlanta, Chicago, Dallas, Denver - without a connection, and those
    are exactly the cities the feeds post from. A positioning leg on a nonstop is a cheap,
    low-risk add-on; one requiring its own connection is neither.
  * Separate tickets carry real risk. A missed connection on a self-connect is
    your problem, not the airline's, and no cost model should quietly bury that.
    It is surfaced as a caveat on the deal rather than priced into it.

What a hop costs
----------------
The fare curve is fitted to deal-blog postings, the cheapest fares there are,
and a hop out of a regional airport is not one. Against DOT's Consumer Airfare
Report for one regional base, the curve priced its nonstop hops at a median of
a third of what the cheapest carrier in each market collected. So where
`tools/build_positioning.py` has measured the base, a hop is the measured fare;
a city it did not measure is the curve times the base's measured median; and
only with no table at all does the bare curve, marked up for a connection,
still stand in.
"""

import json
import os

from . import dotfares, places

# Positioning legs are short domestic hops bought close to the deal. They price
# above a plain distance curve, and a leg that needs its own connection prices
# above that again - more segments, less competition, worse timing options.
# Only used when nothing has been measured: DOT's averages already include
# whatever connections passengers took.
NONSTOP_MULTIPLIER = 1.0
CONNECTING_MULTIPLIER = 1.35

FARES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "positioning_fares.json")
_FARES = None

# Below this, a positioning leg is noise rather than a decision.
MIN_NOTABLE_USD = 25.0

# No default base. A library has no business guessing which airport you live
# near, and `estimate` already returns None when there is no base, so an unset
# one degrades to "do not price positioning legs" rather than to someone else's
# home field. Set it in your profile.
DEFAULTS = {
    "enabled": True,
    "base": "",
    "nonstop_from_base": [],
    "max_positioning_usd": 600,
    "self_connect_warning": True,
    # Driving to an alternate airport: marginal fuel and wear per road mile
    # (not the IRS rate, which carries insurance and depreciation you pay
    # anyway), and long-term parking per day of the trip.
    "drive_cost_per_mile": 0.25,
    "parking_per_day": 15.0,
    # What the party's hour behind the wheel is worth. Used only to choose
    # between flying from the base and driving to an alternate, never added to
    # a total: nobody is billed for it, but a seven-hour round trip to save $70
    # is not a saving.
    "drive_hour_usd": 20.0,
}

# Road miles run longer than great-circle ones; 1.3 is what the three drives
# this was built against measure (110-190 road miles against 90-145).
ROAD_FACTOR = 1.3
KM_PER_MILE = 1.609344
ROAD_MPH = 55.0


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


def drive_alternates(profile):
    """Home airports other than the base: the ones you would drive to."""
    base = base_key(profile)
    homes = {places.resolve(c) for c in profile.get("home_cities", [])}
    keys = set()
    for code in profile.get("home_airports", []):
        key = places.resolve(code)
        if key and key != base and key not in homes:
            keys.add(key)
    return keys


def drive_hours(profile, airport):
    """Hours behind the wheel, there and back."""
    km = places.distance_km(base_key(profile), airport)
    return None if km is None else km / KM_PER_MILE * ROAD_FACTOR * 2 / ROAD_MPH


def drive_usd(profile, airport, nights):
    """Driving the party to `airport` and back, and parking for the trip."""
    cfg = config(profile)
    km = places.distance_km(base_key(profile), airport)
    if km is None:
        return None
    road_miles = km / KM_PER_MILE * ROAD_FACTOR * 2
    return (road_miles * float(cfg["drive_cost_per_mile"])
            + float(cfg["parking_per_day"]) * (nights + 1))


def trip_nights(deal, profile):
    defaults = profile.get("default_nights") or {}
    return int(deal.nights or defaults.get(deal.kind) or 7)


def measured_fares(path=None):
    """The table tools/build_positioning.py wrote, or {} when there is none."""
    global _FARES
    if _FARES is not None and path is None:
        return _FARES
    try:
        with open(path or FARES_PATH, encoding="utf-8") as fh:
            table = json.load(fh)
    except (OSError, ValueError):
        table = {}
    if path is None:
        _FARES = table
    return table


def estimate(origin_key, profile, fare_curve, fares=None):
    """What it costs one person to reach `origin_key` from the base, roundtrip.

    `fare_curve` is score.expected_flight_usd, injected rather than imported so
    that the fare model stays in one place and this module stays testable.
    `fares` is a measured table (default: data/positioning_fares.json); one built
    for a different base is ignored.

    Returns None when there is no base, no route, or the origin *is* the base.
    """
    cfg = config(profile)
    if not cfg.get("enabled"):
        return None
    base = base_key(profile)
    if not base or not origin_key or origin_key == base:
        return None

    nonstop = origin_key in nonstop_keys(profile)
    table = measured_fares() if fares is None else fares
    if table.get("base") != base:
        table = {}
    row = (table.get("fares") or {}).get(origin_key)

    if row:
        fare, source = row["roundtrip_usd"], "measured"
    else:
        fare = fare_curve(base, origin_key, "economy")
        if fare is None:
            return None
        if table.get("curve_multiplier"):
            fare *= table["curve_multiplier"]
            source = "scaled"
        else:
            fare *= NONSTOP_MULTIPLIER if nonstop else CONNECTING_MULTIPLIER
            source = "modelled"
    return {
        "from": base,
        "to": origin_key,
        "nonstop": nonstop,
        "per_person_usd": fare,
        "source": source,
        "quarters": table.get("quarters") if source != "modelled" else None,
    }


def via_alternate(origin_key, profile, nights, routes=None):
    """The cheapest drive-then-fly to `origin_key` through an alternate airport.

    Only a fare DOT measured counts: from a regional base the hop out of a hub
    an hour or two away is usually far cheaper (Nashville to Denver averaged
    $241 against $545 from the base), but stacking a guessed fare on a guessed
    drive is how a cheap-looking total gets invented.
    """
    travelers = max(1, int(profile.get("travelers", 1)))
    best = None
    for alt in drive_alternates(profile):
        row = dotfares.lookup(alt, origin_key, routes)
        drive = drive_usd(profile, alt, nights)
        if not row or drive is None:
            continue
        party = row["roundtrip_low_usd"] * travelers + drive
        weighed = party + drive_hours(profile, alt) * float(config(profile)["drive_hour_usd"])
        if best is None or weighed < best["weighed_usd"]:
            best = {"via": alt, "air_per_person_usd": row["roundtrip_low_usd"],
                    "drive_usd": drive, "party_usd": party, "weighed_usd": weighed}
    return best


def apply(deal, profile, rates, fare_curve, home_keys, fares=None, routes=None):
    """Attach positioning cost to a deal, or explain why none is needed.

    Mutates deal.trip and returns the per-party USD cost to add (0.0 when none).
    """
    trip = deal.trip
    trip["positioning"] = None
    if not deal.origin:
        return 0.0
    cfg = config(profile)
    travelers = max(1, int(profile.get("travelers", 1)))
    nights = trip_nights(deal, profile)
    home = (profile.get("home_currency") or "USD")

    # A deal out of an airport you would drive to is not free: it costs the
    # drive and the parking, which used to be counted as nothing at all.
    if (cfg.get("enabled") and deal.origin_is_departure
            and deal.origin in drive_alternates(profile)):
        drive = drive_usd(profile, deal.origin, nights)
        if drive:
            est = {"from": base_key(profile), "to": deal.origin, "nonstop": True,
                   "drive_only": True, "via": None, "drive_usd": drive,
                   "per_person_usd": drive / travelers, "party_usd": drive,
                   "party_home": rates.convert(drive, "USD", home),
                   "source": "drive"}
            trip["positioning"] = est
            return drive

    if deal.origin in home_keys:
        return 0.0

    # A package saying "flights from Vienna" really does require you to be in
    # Vienna, and costs whatever that costs. A package saying "Lisbon to Porto"
    # names its own itinerary and starts wherever you live. Only the first kind
    # is a departure, which is why the parser records which one it saw.
    if not deal.origin_is_departure:
        return 0.0

    est = estimate(deal.origin, profile, fare_curve, fares)
    alt = via_alternate(deal.origin, profile, nights, routes) if cfg.get("enabled") else None
    if est is None and alt is None:
        return 0.0
    if est is not None:
        est["party_usd"] = est["per_person_usd"] * travelers
        est["via"] = None
    if alt and (est is None or alt["weighed_usd"] < est["party_usd"]):
        est = {"from": base_key(profile), "to": deal.origin, "nonstop": False,
               "via": alt["via"], "drive_usd": alt["drive_usd"],
               "per_person_usd": alt["party_usd"] / travelers,
               "party_usd": alt["party_usd"], "source": "measured"}

    est["party_home"] = rates.convert(est["party_usd"], "USD", home)
    if est.get("via"):
        est["drive_home"] = rates.convert(est["drive_usd"], "USD", home)
    trip["positioning"] = est
    return est["party_usd"]


def describe(deal, profile, money):
    """A short human note for the deal card, or None."""
    est = (deal.trip or {}).get("positioning")
    if not est or est["party_usd"] < MIN_NOTABLE_USD:
        return None
    name = lambda key: (places.city(key) or {}).get("name", key)  # noqa: E731
    if est.get("drive_only"):
        return "add %s to drive to %s and park, est." % (money(est.get("party_home")),
                                                        name(est["to"]))
    if est.get("via"):
        return "add %s to reach %s via %s (drive and park %s), DOT average paid" % (
            money(est.get("party_home")), name(est["to"]), name(est["via"]),
            money(est.get("drive_home")))
    return "add %s to reach %s from %s%s, %s" % (
        money(est.get("party_home")),
        places.city(est["to"])["name"],
        (places.city(est["from"]) or {}).get("name", est["from"]),
        "" if est["nonstop"] else " (connects)",
        SOURCE_NOTES.get(est.get("source"), SOURCE_NOTES["modelled"]))


# How the hop was priced, said on the card so the total can be weighed.
SOURCE_NOTES = {
    "measured": "DOT average paid",
    "scaled": "est. from DOT fares",
    "modelled": "est., unmeasured",
}


def caveat(deal, profile):
    """The risk that does not belong in a price."""
    cfg = config(profile)
    est = (deal.trip or {}).get("positioning")
    if not est or not cfg.get("self_connect_warning") or est.get("drive_only"):
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
