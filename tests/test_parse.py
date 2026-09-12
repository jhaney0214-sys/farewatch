"""Parsing tests.

Most of these are regressions. Every one marked REGRESSION is a bug that was
live and produced a confidently wrong number, which is the failure mode that
matters here - a deal that silently ranks first because its price was misread
is worse than a deal that never appears.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import feeds, parse, places  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name + ".xml"), "rb") as fh:
        return fh.read()


class TestPrice(unittest.TestCase):

    def test_plain(self):
        self.assertEqual(parse.extract_price("American: LA - Miami. $417"), (417.0, "USD"))

    def test_symbol_after_number(self):
        self.assertEqual(parse.extract_price("Brussels to Hong Kong 1720€ Round Trip"),
                         (1720.0, "EUR"))

    def test_four_digits_not_split(self):
        # REGRESSION: the thousands group was optional, so "1349" matched as
        # "134" and a $1349 cruise was ranked as a $134 one.
        self.assertEqual(parse.extract_price("$1349 -- Sicily & Malta w/flights"),
                         (1349.0, "USD"))

    def test_comma_thousands(self):
        self.assertEqual(parse.extract_price("$10,999 -- Antarctica voyage"),
                         (10999.0, "USD"))

    def test_lower_of_two_fares(self):
        self.assertEqual(
            parse.extract_price("$117 (Basic Economy) / $197 (Regular Economy)"),
            (117.0, "USD"))

    def test_ignores_included_credit(self):
        # REGRESSION: taking the minimum price made this a $1000 cruise.
        self.assertEqual(
            parse.extract_price("$1799 -- Norway cruises incl. $1000 flight credit"),
            (1799.0, "USD"))

    def test_ignores_former_price(self):
        self.assertEqual(
            parse.extract_price("$245 -- Cancun all-inclusive Hyatt, reg. $529"),
            (245.0, "USD"))

    def test_ignores_perk_value(self):
        # REGRESSION: "$70+ in extras" was read as the room rate, so a $129
        # hotel appeared to be 90% below market and ranked third overall.
        self.assertEqual(
            parse.extract_price("$129-$175 -- San Francisco hotel w/$70+ in extras"),
            (129.0, "USD"))

    def test_ignores_savings(self):
        self.assertEqual(parse.extract_price("Save $500 -- Mediterranean cruises"),
                         (None, None))

    def test_percentages_are_not_prices(self):
        self.assertEqual(parse.extract_price("50% off -- Antarctica cruises"),
                         (None, None))

    def test_star_rating_is_not_a_price(self):
        amount, _cur = parse.extract_price("Well-rated 4* hotel in Lombok for €24")
        self.assertEqual(amount, 24.0)


class TestBasis(unittest.TestCase):

    def test_explicit_per_night(self):
        self.assertEqual(parse.extract_basis("Le Meridien for only €126 per night",
                                             "hotel"), "per_night")

    def test_explicit_double(self):
        self.assertEqual(parse.extract_basis("4* hotel for €62/double", "hotel"),
                         "per_room_night")

    def test_explicit_per_person(self):
        self.assertEqual(parse.extract_basis("Kefalonia for €557 p.p", "package"),
                         "per_person")

    def test_hotel_default_is_nightly(self):
        # REGRESSION: an unlabelled hotel price was read as the whole stay, so a
        # $159 New York room scored as 76% below market.
        self.assertEqual(parse.extract_basis("$159-$189 -- NYC hotel", "hotel"),
                         "per_room_night")

    def test_package_default_is_per_person(self):
        self.assertEqual(parse.extract_basis("$249 -- New Orleans trip w/flights",
                                             "package"), "per_person")


class TestNights(unittest.TestCase):

    def test_nights(self):
        self.assertEqual(parse.extract_nights("$949 -- Lisbon & Porto: 6 nights"), 6)

    def test_hyphenated(self):
        self.assertEqual(parse.extract_nights("7-night stay at aparthotel"), 7)

    def test_days_become_nights(self):
        self.assertEqual(parse.extract_nights("10-day tour of Peru"), 9)

    def test_absent(self):
        self.assertIsNone(parse.extract_nights("Cheap flights to Lisbon"))


class TestClassify(unittest.TestCase):

    def test_url_wins_when_trusted(self):
        self.assertEqual(
            parse.classify("$3370 -- Madeira & Canary Islands", "",
                           "https://www.travelzoo.com/cruises/x/", trust_url=True),
            "cruise")

    def test_untrusted_url_defers_to_title(self):
        # REGRESSION: Fly4Free files hotel posts under /flight-deals/, so
        # trusting its URL labelled a third of the feed as flights.
        self.assertEqual(
            parse.classify("Well-rated 4* Palmscape Boutique Hotel in the Maldives",
                           "", "https://www.fly4free.com/flight-deals/europe/x/",
                           trust_url=False),
            "hotel")

    def test_package_beats_flight_and_hotel(self):
        self.assertEqual(parse.classify("Holiday in Kefalonia: flights + 7-night stay",
                                        "", "", trust_url=False), "package")

    def test_entertainment_is_not_travel(self):
        self.assertEqual(
            parse.classify("One World Observatory tickets", "",
                           "https://www.travelzoo.com/entertainment/new-york/x/"),
            "local")

    def test_summary_does_not_override_hotel_title(self):
        # Deal-blog summaries mention flights almost universally.
        self.assertEqual(
            parse.classify("4* hotel on the island Lombok",
                           "Cheap flights and more deals from Europe", "",
                           trust_url=False),
            "hotel")


class TestRoute(unittest.TestCase):

    def test_from_to(self):
        self.assertEqual(
            parse.extract_route("Cheap non-stop flights from Bucharest to Dubai"),
            ("bucharest", "dubai"))

    def test_from_to_beats_mention_order(self):
        # REGRESSION: the destination is named before the origin here, so taking
        # the first two places found reversed the route.
        self.assertEqual(
            parse.extract_route("Winter escape to the UAE. Cheap non-stop flights "
                                "from Bucharest to Dubai for €163"),
            ("bucharest", "dubai"))

    def test_to_without_from(self):
        self.assertEqual(
            parse.extract_route("Business Class Deal: Brussels to Hong Kong"),
            ("brussels", "hong kong"))

    def test_airline_dash_route(self):
        self.assertEqual(
            parse.extract_route("American: Los Angeles - St. Maarten. Roundtrip",
                                "flight"),
            ("los angeles", "st. maarten"))

    def test_dash_route_with_prefix_and_region(self):
        self.assertEqual(
            parse.extract_route("The Shorthaul - United: San Francisco - Seattle, "
                                "Washington (and vice versa)", "flight"),
            ("san francisco", "seattle"))

    def test_country_resolves_to_its_main_city(self):
        self.assertEqual(
            parse.extract_route("Business Class Deal: Spain to Canada"),
            ("madrid", "toronto"))

    def test_origin_only_then_destination(self):
        origin, dest = parse.extract_route(
            "Holiday in Kefalonia, Greece: flights from Vienna + 7-night stay",
            "package")
        self.assertEqual((origin, dest), ("vienna", "kefalonia"))

    def test_hotel_takes_first_place_as_destination(self):
        origin, dest = parse.extract_route(
            "B&B stay at 4* hotel on the island Lombok, Indonesia", "hotel")
        self.assertIsNone(origin)
        self.assertEqual(dest, "lombok")

    def test_unknown_place(self):
        self.assertEqual(parse.extract_route("Flights to Nowheresville"), (None, None))


class TestPlaces(unittest.TestCase):

    def test_iata(self):
        self.assertEqual(places.resolve("MCI"), "kansas city")

    def test_alias(self):
        self.assertEqual(places.resolve("NYC"), "new york")

    def test_country_alias(self):
        self.assertEqual(places.resolve("Japan"), "tokyo")

    def test_longest_match_wins(self):
        found = [k for k, _ in places.find_all("New York to Kansas City")]
        self.assertEqual(found, ["new york", "kansas city"])

    def test_currency(self):
        self.assertEqual(places.currency_of("tokyo"), "JPY")

    def test_distance_is_plausible(self):
        km = places.distance_km("new york", "london")
        self.assertTrue(5500 < km < 5700, km)

    def test_label(self):
        self.assertEqual(places.label("tokyo"), "Tokyo, Japan")


class TestFeedParsing(unittest.TestCase):

    def test_rss(self):
        entries = feeds.parse(fixture("theflightdeal"))
        self.assertGreater(len(entries), 10)
        self.assertTrue(all(e["title"] for e in entries))
        self.assertTrue(all(e["link"].startswith("http") for e in entries))

    def test_atom(self):
        entries = feeds.parse(fixture("reddit_flightdeals"))
        self.assertGreater(len(entries), 10)
        self.assertTrue(all(e["link"].startswith("http") for e in entries))

    def test_junk_does_not_raise(self):
        self.assertEqual(feeds.parse(b"<html>not a feed</html>"), [])
        self.assertEqual(feeds.parse(b""), [])

    def test_dates_are_iso(self):
        entries = feeds.parse(fixture("travelzoo"))
        dated = [e for e in entries if e["published"]]
        self.assertTrue(dated)
        self.assertIn("T", dated[0]["published"])


class TestBuildAgainstRealFeeds(unittest.TestCase):
    """The parser has to survive real feeds, not just the cases it was written for."""

    def _build(self, name, trust_url):
        entries = feeds.parse(fixture(name))
        for e in entries:
            e["source"] = name
            e["trust_url_kind"] = trust_url
        return entries, parse.build_all(entries)[0]

    def test_flightdeal_fully_parsed(self):
        entries, deals = self._build("theflightdeal", False)
        # This feed is entirely structured headlines; anything less than all of
        # them means the route or price parser has regressed.
        self.assertEqual(len(deals), len(entries))
        for deal in deals:
            self.assertEqual(deal.kind, "flight")
            self.assertIsNotNone(deal.origin)
            self.assertIsNotNone(deal.destination)

    def test_fly4free_mostly_parsed(self):
        entries, deals = self._build("fly4free", False)
        self.assertGreater(len(deals) / len(entries), 0.85)
        kinds = {d.kind for d in deals}
        self.assertIn("hotel", kinds)
        self.assertIn("flight", kinds)

    def test_travelzoo_covers_every_kind(self):
        _entries, deals = self._build("travelzoo", True)
        kinds = {d.kind for d in deals}
        for kind in ("hotel", "package", "cruise"):
            self.assertIn(kind, kinds)
        self.assertNotIn("local", kinds)

    def test_no_deal_has_an_absurd_price(self):
        for name, trust in (("theflightdeal", False), ("fly4free", False),
                            ("travelzoo", True), ("reddit_flightdeals", False)):
            _entries, deals = self._build(name, trust)
            for deal in deals:
                self.assertTrue(5 <= deal.price < 100000,
                                "%s: %r in %s" % (deal.price, deal.title, name))


class TestRejectReasons(unittest.TestCase):
    """The parser drops ~35% of entries; it has to be able to say why."""

    def _reason(self, title, url="", summary="", trust=True):
        deal, reason = parse.build_detailed({
            "title": title, "link": url, "summary": summary,
            "source": "t", "trust_url_kind": trust})
        return deal, reason

    def test_no_price(self):
        _d, reason = self._reason("Up to 30% off -- Daytona Beach hotels")
        self.assertEqual(reason, parse.REJECT_NO_PRICE)

    def test_not_travel(self):
        _d, reason = self._reason(
            "$34 & up -- NUTCRACKER Christmas ballet shows in Cleveland",
            "https://www.travelzoo.com/entertainment/cleveland/x/")
        self.assertEqual(reason, parse.REJECT_NOT_TRAVEL)

    def test_unknown_destination(self):
        _d, reason = self._reason("$995 -- Zorblatt river cruises")
        self.assertEqual(reason, parse.REJECT_NO_DESTINATION)

    def test_success_reports_no_reason(self):
        deal, reason = self._reason("American: Los Angeles - Tokyo. $417. Roundtrip")
        self.assertIsNotNone(deal)
        self.assertIsNone(reason)

    def test_build_all_returns_inspectable_rejects(self):
        entries = [
            {"title": "Up to 30% off -- hotels", "link": "", "source": "t"},
            {"title": "American: Los Angeles - Tokyo. $417. Roundtrip",
             "link": "", "source": "t"},
        ]
        deals, rejects = parse.build_all(entries)
        self.assertEqual(len(deals), 1)
        self.assertEqual(len(rejects), 1)
        self.assertEqual(rejects[0]["reason"], parse.REJECT_NO_PRICE)
        self.assertIn("title", rejects[0])
        self.assertIn("source", rejects[0])


class TestLocalDealsAreNotAllLocal(unittest.TestCase):
    """REGRESSION: Travelzoo files real hotel getaways under /local-deals/.

    Treating that path as non-travel threw away genuine resort deals alongside
    the theatre tickets they share a URL prefix with.
    """

    LOCAL = "https://www.travelzoo.com/local-deals/International/Getaway/1/x/"

    def test_hotel_under_local_deals_is_a_hotel(self):
        self.assertEqual(
            parse.classify("$1699 -- Tulum 5-star for 2 incl. meals", "",
                           self.LOCAL), "hotel")

    def test_getaway_wording_reads_as_lodging(self):
        self.assertEqual(
            parse.classify("$779 -- Weeklong Phuket private beach getaway for 2",
                           "", self.LOCAL), "hotel")

    def test_a_show_under_local_deals_is_still_not_travel(self):
        self.assertEqual(
            parse.classify("$139 -- 7-course dinner from Vatican chef", "",
                           self.LOCAL), "local")

    def test_entertainment_stays_rejected(self):
        self.assertEqual(
            parse.classify("$26 & up -- One World Observatory tickets", "",
                           "https://www.travelzoo.com/entertainment/ny/x/"), "local")


class TestNewPlaces(unittest.TestCase):
    """Airports and regions added because the rejects report showed them missing."""

    def test_huntsville(self):
        self.assertEqual(places.resolve("HSV"), "huntsville")

    def test_fort_lauderdale_is_no_longer_miami(self):
        # Breeze and Allegiant both fly HSV-FLL nonstop, so it needs its own
        # cost basis rather than being aliased onto Miami.
        self.assertEqual(places.resolve("FLL"), "fort lauderdale")
        self.assertEqual(places.resolve("MIA"), "miami")

    def test_uk_birmingham_still_wins_the_bare_name(self):
        self.assertEqual(places.resolve("Birmingham"), "birmingham")
        self.assertEqual(places.resolve("BHM"), "birmingham al")

    def test_orlando_has_both_airports(self):
        self.assertEqual(places.resolve("SFB"), "orlando")
        self.assertEqual(places.resolve("MCO"), "orlando")

    def test_cruise_regions_resolve_to_a_representative_port(self):
        for region in ("Mediterranean", "Caribbean", "British Isles"):
            self.assertIsNotNone(places.resolve(region), region)

    def test_resort_areas_resolve(self):
        for name in ("Hilton Head", "Asheville", "Scottsdale", "Lake Tahoe",
                     "Galapagos", "Fuerteventura"):
            self.assertIsNotNone(places.resolve(name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
