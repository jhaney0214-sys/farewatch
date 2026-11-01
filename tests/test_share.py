"""What leaves for the friends' board: cruises only, no profile, and the cruise
line where the copy gives it away. Added 2026-11-01."""

import json
import os
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import cruise, dotfares, fx, positioning, score, share, store  # noqa: E402
from farewatch.models import Deal  # noqa: E402

positioning._FARES = {}
dotfares._TABLE = {}

SECRET_BITS = ["HSV", "6,000", "6000", "wishlist", "over your", "on your list"]
PROFILE = {
    "home_cities": ["huntsville"], "home_airports": ["HSV", "BHM", "BNA", "ATL"],
    "home_currency": "USD", "travel_style": "mid", "travelers": 2, "cruise_cabin": "balcony",
    "max_trip_budget": 6000, "wishlist": ["portugal"],
    "positioning": {"enabled": True, "base": "HSV", "nonstop_from_base": ["ATL"]},
    "share": {"url": "https://board.example/api/deals", "key": "k"},
}


def rates():
    return fx.Rates({"USD": 1.0}, {"USD": 1.0}, as_of="2026-11-01")


def sailing(title, summary="", price=599.0, nights=7, kind="cruise", basis="per_person", dest="nassau"):
    return Deal(source="t", title=title, url="https://x.example/d", kind=kind, price=price,
                currency="USD", destination=dest, basis=basis, nights=nights, summary=summary)


class TestLine(unittest.TestCase):

    def test_named_in_the_copy(self):
        self.assertEqual(cruise.line(sailing("x", "Set sail aboard MSC Grandiosa")), ("MSC", "MSC Grandiosa"))
        self.assertEqual(cruise.line(sailing("Royal Caribbean sale"))[0], "Royal Caribbean")

    def test_a_ship_names_its_line(self):
        self.assertEqual(cruise.line(sailing("x", "Aboard the Eurodam, you'll sail")),
                         ("Holland America", "Eurodam"))

    def test_a_private_island_names_its_line(self):
        self.assertEqual(cruise.line(sailing("x", "dock at RelaxAway Half Moon Cay"))[0], "Holland America")

    def test_ordinary_words_name_nobody(self):
        for text in ("Visit Costa Maya and Costa Rica", "Norway fjords on a Norwegian coast tour",
                     "A carnival atmosphere ashore", "Our celebrity chef", "A regal princess experience",
                     "Stops in Rotterdam and Volendam", "Viking history in Oslo"):
            self.assertIsNone(cruise.line(sailing("x", text))[0], text)

    def test_a_line_named_outright_beats_a_ship_or_a_town(self):
        self.assertEqual(cruise.line(sailing("Avalon 7-Night Tulip River Cruise", "Sail from Rotterdam"))[0],
                         "Avalon Waterways")

    def test_a_region_after_the_line_is_not_a_ship(self):
        self.assertEqual(cruise.line(sailing("Celebrity Northern Europe Cruise Sale")), ("Celebrity", None))


class TestCabinInSummary(unittest.TestCase):

    def test_a_summary_that_prices_a_balcony_is_not_scaled_twice(self):
        deal = sailing("MSC 7-Night Cruise", "Enjoy an oceanview balcony stateroom as you visit Nassau")
        self.assertEqual(cruise.cabin(deal), "balcony")
        self.assertEqual(cruise.cabin_factor(deal, PROFILE), 1.0)

    def test_an_offer_of_an_upgrade_is_not_this_price(self):
        for text in ("Upgrade to a balcony stateroom for $200", "Inside cabin from $599, balcony stateroom from $899"):
            self.assertEqual(cruise.cabin(sailing("x", text)), "inside", text)


class TestRows(unittest.TestCase):

    def ranked(self, *deals):
        return [score.score_deal(d, PROFILE, rates()) for d in deals]

    def test_only_cruises_travel_and_nothing_from_the_profile(self):
        ranked = self.ranked(
            sailing("$2,987 -- Lisbon cruise over budget", price=2987, dest="lisbon"),
            sailing("$599 & up -- 7-night Western Caribbean cruise"),
            sailing("Lisbon hotel", kind="hotel", dest="lisbon", basis="per_room_night"))
        # A cruise that scoring called over budget and on the wishlist.
        self.assertTrue(any("budget" in r or "on your list" in r for d in ranked for r in d.reasons))
        rows = share.rows(ranked)
        self.assertEqual(len(rows), 3)
        text = json.dumps(rows).lower().replace("over budget", "")
        for bit in SECRET_BITS:
            self.assertNotIn(bit.lower(), text, bit)

    def test_the_trip_to_port_names_the_home_city_from_the_profile(self):
        ranked = self.ranked(sailing("7-night Western Caribbean cruise"))
        self.assertEqual(share.home_name(PROFILE), "Huntsville")
        self.assertIn("Huntsville", share.rows(ranked, share.home_name(PROFILE))[0]["travel"])

    def test_per_person_and_tidy(self):
        row = share.rows(self.ranked(sailing("MSC 7-Night Bahamas Cruise for From $1,116 for 2",
                                             "Aboard MSC Grandiosa, an oceanview balcony stateroom, departing March 6, 2027.",
                                             price=1116, basis="total")))[0]
        self.assertEqual(row["title"], "MSC 7-Night Bahamas Cruise")
        self.assertEqual(row["from_pp"], 558)
        self.assertEqual(row["balcony_pp"], 558)
        self.assertEqual(row["line"], "MSC")
        self.assertEqual(row["ship"], "MSC Grandiosa")
        self.assertEqual(row["dates"], "March 6, 2027")


class TestLinks(unittest.TestCase):

    def test_a_named_line_links_to_the_line_not_the_ad(self):
        deal = score.score_deal(sailing("Carnival Valor cruise"), PROFILE, rates())
        deal.url = "https://www.travelzoo.com/direct/cruises/x/-1-1234567/"
        deal.source = "travelzoo"
        self.assertEqual(share.row(deal)["go_url"], share.LINE_SITES["Carnival"])
        self.assertEqual(share.row(deal)["source"], "Travelzoo")

    def test_an_unnamed_cruise_links_to_a_search_never_the_ad(self):
        deal = score.score_deal(sailing("7-night Baja cruise"), PROFILE, rates())
        deal.source = "travelzoo"
        go = share.row(deal)["go_url"]
        self.assertTrue(go.startswith("https://www.google.com/search?q="))

    def test_other_kinds_can_be_shared_and_keep_a_working_source_link(self):
        deal = sailing("Lisbon hotel", kind="hotel", dest="lisbon", basis="per_room_night", price=120)
        deal = score.score_deal(deal, PROFILE, rates())
        deal.source = "fly4free"
        row = share.row(deal)
        self.assertEqual((row["kind"], row["price_word"], row["go_url"]), ("hotel", "a night", deal.url))


class TestPriceLog(unittest.TestCase):

    def setUp(self):
        self.conn = store.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.addCleanup(self.conn.close)

    def test_the_key_survives_a_new_price(self):
        a = store.deal_key("https://www.travelzoo.com/direct/cruises/x/-849-up-9-night-3280009/", "$849 & up -- 9-night")
        b = store.deal_key("https://www.travelzoo.com/direct/cruises/x/-699-up-9-night-3280009/", "$699 & up -- 9-night")
        self.assertEqual(a, b)
        self.assertEqual(store.deal_key("https://x.example/a", "$5 -- Trip"), store.deal_key("https://x.example/b", "$9 -- Trip"))

    def _deal(self, price, url="https://x.example/-1234567/"):
        deal = sailing("$%d -- 7-night cruise" % price, price=price)
        deal.url = url
        deal.trip = {"unit_usd": price}
        return deal

    def test_a_daily_pull_logs_changes_and_keeps_the_first_price(self):
        store.log_prices(self.conn, [self._deal(849)], day="2026-11-01")
        store.log_prices(self.conn, [self._deal(849)], day="2026-11-02")
        store.log_prices(self.conn, [self._deal(699)], day="2026-11-03")
        history = store.price_history(self.conn)["1234567"]
        self.assertEqual(history, [["2026-11-01", 849], ["2026-11-03", 699]])

    def test_one_price_a_day_the_last_pull_wins(self):
        store.log_prices(self.conn, [self._deal(849)], day="2026-11-01")
        store.log_prices(self.conn, [self._deal(800)], day="2026-11-01")
        self.assertEqual(store.price_history(self.conn)["1234567"], [["2026-11-01", 800]])

    def test_a_for_two_cruise_is_logged_per_person(self):
        deal = self._deal(1116)
        deal.basis = "total"
        store.log_prices(self.conn, [deal], day="2026-11-01")
        self.assertEqual(store.price_history(self.conn)["1234567"], [["2026-11-01", 558]])

    def test_the_list_carries_it(self):
        deal = score.score_deal(self._deal(699), PROFILE, rates())
        row = share.row(deal, history={"1234567": [["2026-09-01", 849], ["2026-09-04", 699]]})
        self.assertEqual(row["history"][0], ["2026-09-01", 849])


class TestPush(unittest.TestCase):

    def test_off_without_a_share_block(self):
        self.assertFalse(share.push([], {}, log=lambda m: None,
                                    opener=lambda *a, **k: self.fail("must not send")))

    def test_sends_the_key_and_the_list(self):
        seen = {}

        class Done:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        def opener(request, timeout=0):
            seen["key"] = request.get_header("X-deals-key")
            seen["body"] = json.loads(request.data)
            return Done()

        self.assertTrue(share.push([], PROFILE, log=lambda m: None, opener=opener, history={}))
        self.assertEqual(seen, {"key": "k", "body": {"deals": []}})

    def test_a_failure_is_quiet_and_keeps_the_secret_out_of_the_log(self):
        lines = []

        def opener(request, timeout=0):
            raise urllib.error.URLError("https://board.example/t/secret/ refused")

        self.assertFalse(share.push([], PROFILE, log=lines.append, opener=opener, history={}))
        self.assertNotIn("secret", " ".join(lines))


if __name__ == "__main__":
    unittest.main()
