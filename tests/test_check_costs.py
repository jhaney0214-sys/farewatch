"""tools/check_costs.py without the network: python -m unittest tests.test_check_costs"""

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import check_costs as cc  # noqa: E402


def row(scale, name="X", **over):
    """A country whose every price is `scale` times the base country's."""
    base = {"name": name, "meal_cheap": 20.0, "meal_mid_two": 100.0, "beer": 6.0,
            "transit": 2.0, "taxi_km": 1.5, "hotel_mid": 100.0}
    out = {k: (v * scale if isinstance(v, float) else v) for k, v in base.items()}
    out.update(over)
    return out


class PriceLevels(unittest.TestCase):

    def test_the_latest_year_both_tables_have_is_used(self):
        levels = cc.price_levels({"TH": {"2023": 11.0, "2024": 10.8, "2025": 10.5}},
                                 {"TH": {"2023": 35.0, "2024": 36.0}})
        self.assertEqual(levels["TH"][1], 2024)
        self.assertAlmostEqual(levels["TH"][0], 10.8 / 36.0)

    def test_a_country_in_one_table_only_has_no_level(self):
        self.assertEqual(cc.price_levels({"TW": {"2024": 14.0}}, {}), {})


class Relative(unittest.TestCase):

    def test_a_zero_price_is_left_out_not_counted_as_free(self):
        dry = row(0.5, beer=0.0)
        self.assertAlmostEqual(cc.relative(dry, row(1.0), ("meal_cheap", "beer")), 0.5)


class Check(unittest.TestCase):

    def setUp(self):
        # Twelve countries written exactly at their price level, and one at
        # three times it.
        self.levels = {"US": (1.0, 2025)}
        self.countries = {"US": row(1.0, "United States")}
        for i in range(12):
            level = 0.2 + 0.08 * i
            code = "C%02d" % i
            self.levels[code] = (level, 2025)
            self.countries[code] = row(level, code)
        self.levels["ZZ"] = (0.4, 2025)
        self.countries["ZZ"] = row(1.2, "Stale")

    def test_the_row_three_times_its_level_is_the_only_one_listed(self):
        flags = cc.flagged(cc.check(self.countries, self.levels))
        self.assertEqual(list(flags), ["ZZ"])
        self.assertEqual(set(flags["ZZ"]), {"food", "getting around", "hotel"})
        self.assertGreater(min(flags["ZZ"].values()), cc.FACTOR)

    def test_without_it_nothing_is_listed_and_the_line_is_the_price_level(self):
        del self.countries["ZZ"], self.levels["ZZ"]
        result = cc.check(self.countries, self.levels)
        self.assertEqual(cc.flagged(result), {})
        self.assertAlmostEqual(result["hotel"]["slope"], 1.0, places=6)
        self.assertAlmostEqual(result["hotel"]["r2"], 1.0, places=6)

    def test_a_country_with_no_price_level_is_named_not_dropped_quietly(self):
        self.countries["TW"] = row(0.5, "Taiwan")
        text = cc.report(self.countries, self.levels)
        self.assertIn("none for TW", text)
        self.assertFalse(math.isnan(cc.check(self.countries, self.levels)["food"]["r2"]))


if __name__ == "__main__":
    unittest.main()
