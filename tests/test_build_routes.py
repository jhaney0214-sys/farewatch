"""tools/build_routes.py without the network: python -m unittest tests.test_build_routes"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_routes as br  # noqa: E402
from farewatch import places  # noqa: E402


def miles(a, b):
    return round(places.distance_km(a, b) / br.bp.KM_PER_MILE)


def row(c1, c2, n_miles, year=2026, quarter=1, pax=10, fare=200, fare_low=150):
    return {"year": str(year), "quarter": str(quarter), "city1": c1, "city2": c2,
            "nsmiles": str(n_miles), "passengers": str(pax),
            "fare": str(fare), "fare_low": str(fare_low)}


class Build(unittest.TestCase):

    def test_a_pair_is_keyed_either_way_and_doubled(self):
        t = br.build([row("Los Angeles, CA", "San Francisco, CA",
                          miles("los angeles", "san francisco"))])
        r = t["routes"]["los angeles|san francisco"]
        self.assertEqual((r["roundtrip_low_usd"], r["roundtrip_avg_usd"]), (300.0, 400.0))

    def test_a_distance_that_disagrees_is_dropped(self):
        # Portland resolves to Oregon; this Portland is Maine's.
        t = br.build([row("Boston, MA", "Portland, ME", 100)])
        self.assertEqual(t["routes"], {})

    def test_only_the_latest_four_quarters_count(self):
        m = miles("los angeles", "san francisco")
        rows = [row("Los Angeles, CA", "San Francisco, CA", m, 2025, q) for q in (1, 2, 3, 4)]
        rows.append(row("Los Angeles, CA", "San Francisco, CA", m, 2024, 4, fare_low=900))
        t = br.build(rows)
        self.assertEqual(t["quarters"], ["2025Q1", "2025Q2", "2025Q3", "2025Q4"])
        self.assertEqual(t["routes"]["los angeles|san francisco"]["roundtrip_low_usd"], 300.0)


if __name__ == "__main__":
    unittest.main()
