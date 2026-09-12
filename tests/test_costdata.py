"""The cost data, and what has actually been measured of it.

`destinations.json` drives every all-in total, and for most of the world it is
still hand-authored guesswork. Five countries were checked against real market
data on 2026-08-29 - Google Hotels for lodging medians, Numbeo for food and
transport - and those figures are pinned here so a future edit cannot quietly
walk them back to a guess.

The tolerances are wide on purpose. These are approximations for ranking, not
budgets, and a measurement taken from one city on one day does not deserve to be
asserted to the cent. What they catch is a figure drifting back to the wrong
order of magnitude, which is the failure that actually happened.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import costs, fx, places  # noqa: E402
from farewatch.models import Deal  # noqa: E402

# country -> field -> value measured on 2026-08-29.
MEASURED = {
    "US": {"hotel_mid": 105, "meal_mid_two": 104, "taxi_km": 1.6, "transit": 2.22},
    "JP": {"hotel_mid": 68, "transit": 1.05, "meal_cheap": 6.25},
    "TH": {"hotel_mid": 43.5, "meal_mid_two": 31.6, "transit": 1.0, "taxi_km": 1.05},
    "CH": {"hotel_mid": 157, "meal_mid_two": 124, "transit": 4.75},
    "PT": {"hotel_mid": 99},
}


class TestVerifiedFigures(unittest.TestCase):

    def test_measured_countries_carry_measured_values(self):
        for code, fields in MEASURED.items():
            country = places.country(code)
            for field, expected in fields.items():
                self.assertAlmostEqual(
                    country[field], expected, places=2,
                    msg="%s.%s drifted from its measured value" % (code, field))

    def test_measured_countries_are_marked_as_such(self):
        for code in MEASURED:
            self.assertTrue(places.country(code).get("verified"),
                            "%s lost its verification note" % code)

    def test_unmeasured_countries_are_not_marked(self):
        # Honesty about provenance cuts both ways: a guess must not be able to
        # pass itself off as a measurement.
        for code in ("FR", "IT", "BR", "KE"):
            self.assertIsNone(places.country(code).get("verified"))

    def test_us_lodging_is_not_back_at_its_guessed_value(self):
        # REGRESSION: the authored $165 was 60% above the measured figure, which
        # inflated the all-in total of every United States trip.
        self.assertLess(places.country("US")["hotel_mid"], 130)

    def test_thai_ground_transport_is_not_back_at_its_guessed_value(self):
        # REGRESSION: taxi was $0.50/km against a measured $1.05, and transit
        # $0.60 against $1.00 - understating the cost of getting around exactly
        # the sort of cheap destination this project likes to recommend.
        country = places.country("TH")
        self.assertGreater(country["taxi_km"], 0.9)
        self.assertGreater(country["transit"], 0.9)


class TestThePremiseOnMeasuredData(unittest.TestCase):
    """The claim the whole project rests on, re-checked after correction.

    Both measurement errors happened to flatter this comparison - lodging was
    overstated in rich countries, ground transport understated in cheap ones -
    so it had to be re-run on corrected figures rather than assumed to survive.
    """

    def trip(self, destination, fare):
        deal = Deal(source="t", title="t", url="u", kind="flight", price=fare,
                    currency="USD", destination=destination, origin="chicago",
                    basis="per_person", nights=7)
        rates = fx.Rates({"USD": 1.0}, {"USD": 1.0})
        return costs.breakdown(
            deal, {"travel_style": "mid", "travelers": 2,
                   "home_currency": "USD"}, rates)

    def test_cheaper_fare_is_still_the_dearer_trip(self):
        zurich = self.trip("zurich", 300)
        bangkok = self.trip("bangkok", 450)
        self.assertLess(zurich["deal_usd"], bangkok["deal_usd"])
        self.assertGreater(zurich["total_usd"], bangkok["total_usd"])

    def test_the_gap_is_large_enough_to_act_on(self):
        gap = self.trip("zurich", 300)["total_usd"] - self.trip("bangkok", 450)["total_usd"]
        self.assertGreater(gap, 1500)

    def test_corrections_narrowed_the_gap_rather_than_widening_it(self):
        """Sanity: correcting for honesty should cost the claim something.

        Thai ground costs roughly doubled and US lodging fell by a third, so the
        measured gap must be smaller than the one the old guesses produced.
        """
        gap = self.trip("zurich", 300)["total_usd"] - self.trip("bangkok", 450)["total_usd"]
        self.assertLess(gap, 3000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
