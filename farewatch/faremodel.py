"""The fare curve, alone in its own module.

Both the scorer and the baselines need it - the scorer to form an expectation,
the baselines to express every observation as a ratio against that expectation -
and putting it here is what stops those two importing each other.

The curve itself is deliberately crude. It is a straight line through great
circle distance, fitted by eye against The Flight Deal's own postings. It is
wrong for any single route; its job is to be wrong *consistently*, so that the
ratio of a real price to it carries the route-specific information the line does
not. Calibration then happens on those ratios rather than on the line.
"""

from . import places

CABIN_MULT = {"economy": 1.0, "premium": 1.8, "business": 3.2, "first": 5.0}

FARE_BASE_USD = 60.0
FARE_PER_KM = 0.075

# Distance buckets, in km. Pooling across a bucket is the coarsest useful way to
# say "flights of roughly this length", and it is the level that will always
# have data even when a specific route never does.
BANDS = (1500, 3000, 5000, 8000, 12000)


def expected_flight_usd(origin, destination, cabin="economy"):
    """Modelled roundtrip economy fare, times a cabin multiplier."""
    km = places.distance_km(origin, destination)
    if km is None:
        return None
    return (FARE_BASE_USD + FARE_PER_KM * km) * CABIN_MULT.get(cabin, 1.0)


def distance_band(origin, destination):
    """A coarse label for how long a flight is, or None."""
    km = places.distance_km(origin, destination)
    if km is None:
        return None
    for edge in BANDS:
        if km < edge:
            return "<%dkm" % edge
    return ">=%dkm" % BANDS[-1]
