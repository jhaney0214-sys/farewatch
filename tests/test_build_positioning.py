"""tools/build_positioning.py without the network: python -m unittest tests.test_build_positioning"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_positioning as bp  # noqa: E402
from farewatch import places  # noqa: E402

MARKET = "Des Moines, IA"


def miles(key):
    return round(places.distance_km("des moines", key) / bp.KM_PER_MILE)


def row(other, year, quarter, pax, fare_low, fare=None, nsmiles=None, carrier="AA"):
    """One DOT Table 6 row, with the base on whichever side DOT put it."""
    a, b = sorted([MARKET, other])
    return {"year": str(year), "quarter": str(quarter), "city1": a, "city2": b,
            "nsmiles": str(nsmiles), "passengers": str(pax),
            "fare_low": str(fare_low), "fare": str(fare or fare_low),
            "carrier_low": carrier}


class Build(unittest.TestCase):

    def test_round_trip_is_twice_the_passenger_weighted_one_way(self):
        rows = [row("Chicago, IL", 2026, 1, 30, 200, nsmiles=miles("chicago")),
                row("Chicago, IL", 2025, 4, 10, 100, nsmiles=miles("chicago"))]
        t = bp.build(rows, MARKET, "des moines")
        self.assertAlmostEqual(t["fares"]["chicago"]["roundtrip_usd"], 2 * 175.0)

    def test_only_the_latest_four_quarters_count(self):
        rows = [row("Chicago, IL", y, q, 10, 100, nsmiles=miles("chicago"))
                for y, q in [(2025, 1), (2025, 2), (2025, 3), (2025, 4)]]
        rows.append(row("Chicago, IL", 2024, 4, 1000, 900, nsmiles=miles("chicago")))
        t = bp.build(rows, MARKET, "des moines")
        self.assertEqual(t["quarters"], ["2025Q1", "2025Q2", "2025Q3", "2025Q4"])
        self.assertAlmostEqual(t["fares"]["chicago"]["roundtrip_usd"], 200.0)

    def test_a_name_whose_distance_disagrees_is_not_matched(self):
        # Portland resolves to Oregon; a Portland 400 miles away is Maine's.
        rows = [row("Portland, ME", 2026, 1, 10, 150, nsmiles=400)]
        t = bp.build(rows, MARKET, "des moines")
        self.assertEqual(t["fares"], {})
        self.assertEqual(t["unmatched"], ["Portland, ME"])

    def test_two_markets_on_one_city_keep_the_closer_distance(self):
        # Sarasota is an alias of Tampa; Tampa's own market is the one to keep.
        rows = [row("Tampa, FL", 2026, 1, 10, 90, nsmiles=miles("tampa")),
                row("Sarasota/Bradenton, FL", 2026, 1, 10, 300,
                    nsmiles=miles("tampa") + 30)]
        t = bp.build(rows, MARKET, "des moines")
        self.assertEqual(t["fares"]["tampa"]["market"], "Tampa, FL")
        self.assertIn("Sarasota/Bradenton, FL", t["unmatched"])

    def test_the_multiplier_is_the_median_measured_over_curve(self):
        from farewatch import faremodel
        rows = [row("Chicago, IL", 2026, 1, 10, 300, nsmiles=miles("chicago"))]
        t = bp.build(rows, MARKET, "des moines")
        curve = faremodel.expected_flight_usd("des moines", "chicago")
        self.assertAlmostEqual(t["curve_multiplier"], round(600.0 / curve, 3))


if __name__ == "__main__":
    unittest.main()
