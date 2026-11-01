"""Cruises: region, cabin, the costs a headline leaves out, the port, and value.

Built 2026-11-01 when the author planned to book a cruise on Black Friday and
the ranking called ordinary Caribbean fares "57-61% below typical". Each test
below pins one thing that was wrong then.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import baselines, costs, cruise, dotfares, fx, parse, positioning, score  # noqa: E402
from farewatch.models import Deal  # noqa: E402

# Never this machine's own measured tables: a failure here is the logic.
positioning._FARES = {}
dotfares._TABLE = {}


def make_rates():
    return fx.Rates({"USD": 1.0, "MXN": 18.0}, {"USD": 1.0, "MXN": 18.0},
                    as_of="2026-11-01")

PROFILE = {
    "home_cities": ["huntsville"],
    "home_airports": ["HSV", "BHM", "BNA", "ATL"],
    "home_currency": "USD",
    "travel_style": "mid",
    "travelers": 2,
    "max_trip_budget": 6000,
    "cruise_cabin": "balcony",
    "positioning": {"enabled": True, "base": "HSV",
                    "nonstop_from_base": ["ATL", "MCO", "TPA", "FLL"]},
}


def sailing(title, price=599.0, nights=7, summary=""):
    return Deal(source="test", title=title, url="http://x", kind="cruise",
                price=price, currency="USD", destination="nassau",
                basis="per_person", nights=nights, summary=summary)


class TestRegion(unittest.TestCase):

    def test_itinerary_words_set_the_region_not_a_city_name(self):
        self.assertEqual(cruise.region(sailing("11-night Windward & Leeward Islands cruise"))[0],
                         "caribbean")
        self.assertEqual(cruise.region(sailing("Mexican Riviera & Sea of Cortez cruise"))[0],
                         "mexican_riviera")
        self.assertEqual(cruise.region(sailing("14-night Panama Canal cruise from Florida"))[0],
                         "panama_canal")

    def test_southern_caribbean_sails_from_florida_not_the_gulf(self):
        ports, stated = cruise.candidate_ports(sailing("9-night Southern Caribbean cruise"))
        self.assertFalse(stated)
        self.assertNotIn("mobile", ports)
        self.assertIn("tampa", ports)

    def test_a_named_port_group_is_used(self):
        ports, stated = cruise.candidate_ports(sailing("7 nights: Eastern Caribbean cruise from Florida"))
        self.assertTrue(stated)
        self.assertEqual(ports, cruise.PORT_GROUPS["florida"])


class TestCabin(unittest.TestCase):

    def test_a_from_fare_is_an_inside_cabin_scaled_to_the_balcony_booked(self):
        self.assertEqual(cruise.cabin_factor(sailing("$599 & up -- 7-night Caribbean cruise"), PROFILE),
                         cruise.CABIN_MULT["balcony"])

    def test_the_balcony_premium_is_the_line_s_own(self):
        self.assertEqual(cruise.cabin_factor(sailing("Celebrity Reflection 7-night Caribbean cruise"), PROFILE), 1.224)
        self.assertEqual(cruise.cabin_factor(sailing("Eurodam 7-night cruise"), PROFILE), 1.432)

    def test_a_balcony_fare_is_not_scaled_again(self):
        self.assertEqual(cruise.cabin_factor(sailing("Norway balcony cruise incl. drinks"), PROFILE), 1.0)

    def test_luxury_river_and_bundles_are_not_scaled(self):
        for title in ("Luxury Italy, France & Spain all-inclusive cruise",
                      "9-night Danube river cruise",
                      "Japan adventure w/flights, cruise & bullet trains",
                      "Alaska cruise & land tours"):
            self.assertEqual(cruise.cabin_factor(sailing(title), PROFILE), 1.0, title)


class TestCosts(unittest.TestCase):

    def test_fees_and_gratuities_are_added_unless_included(self):
        plain = cruise.costs(sailing("7-night Caribbean cruise"), PROFILE, 7)
        self.assertGreater(plain["fees_usd"], 0)
        self.assertEqual(plain["gratuities_usd"], cruise.GRATUITY_DAILY * 7 * 2)
        inclusive = cruise.costs(
            sailing("7-night Caribbean cruise incl. taxes & fees, gratuities included"), PROFILE, 7)
        self.assertEqual(inclusive["fees_usd"], 0)
        self.assertEqual(inclusive["gratuities_usd"], 0)

    def test_gratuities_are_the_line_s_own(self):
        self.assertEqual(cruise.costs(sailing("Norwegian Joy 7-night cruise"), PROFILE, 7)["gratuities_usd"], 20 * 7 * 2)
        self.assertEqual(cruise.costs(sailing("Virgin Voyages cruise"), PROFILE, 7)["gratuities_usd"], 0)

    def test_included_in_plain_words(self):
        trip = cruise.costs(sailing("Costa Rica cruise", summary="Drinks, tips and Wi-Fi are covered on this sailing"), PROFILE, 7)
        self.assertEqual(trip["gratuities_usd"], 0)
        self.assertTrue(trip["drinks_included"])

    def test_drinks_in_the_fare_cut_the_onboard_spend(self):
        dry = cruise.costs(sailing("7-night Caribbean cruise"), PROFILE, 7)
        wet = cruise.costs(sailing("7-night Caribbean cruise with free drinks"), PROFILE, 7)
        self.assertLess(wet["onboard_usd"], dry["onboard_usd"])
        self.assertIn("drinks included", wet["perks"])

    def test_onboard_credit_comes_off(self):
        trip = cruise.costs(sailing("Caribbean cruise plus $100 onboard credit"), PROFILE, 7)
        self.assertEqual(trip["onboard_credit_usd"], 100)

    def test_a_cruise_is_costed_even_where_the_city_is_unknown(self):
        deal = sailing("7-night Caribbean cruise")
        deal.destination = None
        trip = costs.breakdown(deal, PROFILE, make_rates())
        self.assertTrue(trip["known"])
        # Fare scaled to balcony, plus fees, tips, onboard and shore.
        self.assertGreater(trip["total_usd"], 599 * 2 * cruise.CABIN_MULT["balcony"])

    def test_black_friday_is_named(self):
        self.assertIn("Black Friday", cruise.perks(sailing("Black Friday sale: Caribbean cruise")))


class TestPort(unittest.TestCase):

    def test_a_gulf_drive_beats_flying_for_a_western_caribbean_sailing(self):
        # Hops at roughly what DOT measured from HSV (Tampa ~$300 a person);
        # the bare deal-blog curve would price them at a third of that.
        hops = {c: {"roundtrip_usd": 300.0} for c in (
            "tampa", "orlando", "new orleans", "houston", "miami",
            "fort lauderdale", "jacksonville")}
        positioning._FARES = {"base": "huntsville", "fares": hops}
        try:
            port = cruise.getting_there(sailing("Carnival Valor 7-night Western Caribbean cruise"), PROFILE,
                                        score.expected_flight_usd, 7)
        finally:
            positioning._FARES = {}
        self.assertEqual(port["how"], "drive")
        self.assertEqual(port["port"], "mobile")

    def test_a_line_is_priced_from_the_ports_it_sails_from(self):
        ports, _stated = cruise.candidate_ports(sailing("10-night Western Caribbean cruise",
                                                        summary="Holland America's private island"))
        self.assertIn("fort lauderdale", ports)
        self.assertNotIn("mobile", ports)
        ports, stated = cruise.candidate_ports(sailing("Eurodam cruise from Florida"))
        self.assertTrue(stated)
        self.assertNotIn("miami", ports)

    def test_no_ship_leaves_from_an_inland_capital(self):
        deal = sailing("Spain & Morocco: 4-night luxury cruise")
        deal.destination = "madrid"
        self.assertIn("barcelona", cruise.candidate_ports(deal)[0])

    def test_an_unnamed_line_is_not_assumed_to_sail_from_mobile(self):
        ports, _stated = cruise.candidate_ports(sailing("7-night Western Caribbean cruise"))
        self.assertNotIn("mobile", ports)

    def test_a_port_the_copy_names_beats_the_table(self):
        self.assertEqual(cruise.candidate_ports(sailing("Holland America cruise from Galveston")),
                         (["galveston"], True))

    def test_a_european_sailing_boards_near_the_place_named(self):
        deal = sailing("Venice to Rome: 8-night cruise")
        deal.destination = "venice"
        self.assertEqual(cruise.candidate_ports(deal)[0], ["venice"])

    def test_flights_in_the_fare_cost_nothing_to_reach(self):
        port = cruise.getting_there(sailing("Greek islands cruise with Athens hotel & flights"),
                                    PROFILE, score.expected_flight_usd, 7)
        self.assertEqual(port["how"], "included")
        self.assertEqual(port["party_usd"], 0.0)

    def test_scoring_adds_the_trip_to_the_port(self):
        deal = score.score_deal(sailing("7-night Western Caribbean cruise"), PROFILE, make_rates())
        self.assertGreater(deal.trip.get("port_cost_usd", 0), 0)


class TestValue(unittest.TestCase):

    def test_tracked_sailings_set_the_expectation(self):
        history = baselines.Baselines()
        for i, price in enumerate((700, 770, 840, 910, 980, 1050)):
            history.add_cruise("$%d -- 7-night Western Caribbean cruise %d" % (price, i), price / 7)
        deal = sailing("$599 -- 7-night Western Caribbean cruise", price=599)
        value, note = score.cruise_value(deal, deal.trip, 599, history)
        self.assertIn("6 of 6 tracked Caribbean", note)
        self.assertGreater(value, 0.5)

    def test_an_ordinary_fare_is_not_called_a_bargain(self):
        # $100 a night is the measured Caribbean median: no "below typical".
        deal = sailing("$700 -- 7-night Western Caribbean cruise", price=700)
        _value, note = score.cruise_value(deal, deal.trip, 700, baselines.Baselines())
        self.assertFalse(note and "below" in note, note)

    def test_luxury_is_compared_with_luxury(self):
        self.assertFalse(cruise.comparable("Italy & Croatia all-inclusive cruise",
                                           "7-night Mediterranean cruise"))

    def test_no_length_no_per_night_judgement(self):
        deal = sailing("Mediterranean summer cruise", price=1799, nights=None)
        value, note = score.cruise_value(deal, deal.trip, 1799, baselines.Baselines())
        self.assertEqual(value, 0.5)
        self.assertEqual(note, "length not stated")


class TestParse(unittest.TestCase):

    def test_for_two_after_the_price_is_the_party_total(self):
        self.assertEqual(parse.extract_basis("MSC 7-Night Bahamas Cruise for From $1,116 for 2",
                                             "cruise"), "total")

    def _build(self, title, summary, url="https://www.travelzoo.com/direct/cruises/x/1/"):
        return parse.build_detailed({"title": title, "summary": summary, "link": url,
                                     "source": "travelzoo", "source_kind": "mixed", "trust_url_kind": True})[0]

    def test_a_cruise_takes_its_length_from_the_summary(self):
        deal = self._build("$3459 -- Italy & Croatia all-inclusive cruise",
                           "Drinks are covered on this 8-night sailing that visits Rome.")
        self.assertEqual(deal.nights, 8)

    def test_a_rail_tour_filed_under_cruises_is_a_package(self):
        deal = self._build("$7999 -- India's Golden Triangle & Himalayan rail incl. flights",
                           "See tigers and the Taj Mahal on a 30-night trip.")
        self.assertEqual(deal.kind, "package")

    def test_a_cruise_accessory_is_not_a_sailing(self):
        deal, reason = parse.build_detailed({
            "title": "Comfycheer Cruise Essentials Kit for $20 + free shipping",
            "summary": "", "link": "http://x", "source": "dealnews-cruises",
            "source_kind": "cruise", "trust_url_kind": False})
        self.assertIsNone(deal)
        self.assertEqual(reason, parse.REJECT_NOT_A_SAILING)


if __name__ == "__main__":
    unittest.main()
