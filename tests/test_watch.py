"""The cruise watch: price history by hand, the sale verdict, feed watches.

The verdict is the point. A Black Friday price is a sale only if it beats what
the same sailing cost before the sale, so each state below is pinned.
"""

import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import dotfares, fx, positioning, render, score, watch  # noqa: E402
from farewatch.models import Deal  # noqa: E402

positioning._FARES = {}
dotfares._TABLE = {}

SALE = {"name": "Black Friday", "start": "2026-11-26", "end": "2026-12-01"}
PROFILE = {
    "home_cities": ["huntsville"], "home_airports": ["HSV", "BHM", "BNA", "ATL"],
    "home_currency": "USD", "travel_style": "mid", "travelers": 2,
    "cruise_cabin": "balcony",
    "positioning": {"enabled": True, "base": "HSV", "nonstop_from_base": ["ATL"]},
}


def rates():
    return fx.Rates({"USD": 1.0}, {"USD": 1.0}, as_of="2026-11-01")


def priced(*days_and_prices):
    state = watch.load(os.path.join(tempfile.mkdtemp(), "none.json"))
    state["sale"] = dict(SALE)
    first_day, first_price = days_and_prices[0]
    entry = watch.add_sailing(state, "Firenze 7n W Caribbean", first_price, nights=7,
                              port="mobile", when=date.fromisoformat(first_day))
    for day, price in days_and_prices[1:]:
        watch.record_price(state, entry["id"], price, when=date.fromisoformat(day))
    return state, entry


class TestPrices(unittest.TestCase):

    def test_one_price_a_day_and_a_total_is_halved(self):
        state, entry = priced(("2026-11-02", 900))
        watch.record_price(state, entry["id"], 1700, basis="total",
                           when=date(2026, 11, 2))
        self.assertEqual(entry["prices"], [{"date": "2026-11-02", "per_person": 850.0}])

    def test_state_round_trips(self):
        path = os.path.join(tempfile.mkdtemp(), "watch.json")
        state, _entry = priced(("2026-11-02", 900))
        watch.save(state, path)
        self.assertEqual(watch.load(path)["sailings"][0]["prices"][0]["per_person"], 900.0)


class TestVerdict(unittest.TestCase):

    def test_before_the_sale_it_names_the_low(self):
        _s, entry = priced(("2026-11-02", 880), ("2026-11-10", 950))
        said = watch.verdict(entry, SALE, today=date(2026, 11, 12))
        self.assertEqual(said["state"], "before")
        self.assertIn("low so far $880", said["text"])

    def test_on_a_sale_day_with_no_sale_price_it_asks_for_one(self):
        _s, entry = priced(("2026-11-02", 880))
        self.assertEqual(watch.verdict(entry, SALE, today=date(2026, 11, 27))["state"], "waiting")

    def test_a_real_sale_beats_the_pre_sale_low(self):
        _s, entry = priced(("2026-11-02", 900), ("2026-11-15", 880), ("2026-11-27", 800))
        said = watch.verdict(entry, SALE)
        self.assertEqual(said["state"], "real")
        self.assertIn("under its pre-sale low of $880", said["text"])

    def test_the_same_price_on_a_sale_day_is_not_a_sale(self):
        _s, entry = priced(("2026-11-15", 880), ("2026-11-27", 870))
        self.assertEqual(watch.verdict(entry, SALE)["state"], "same")

    def test_a_higher_sale_price_is_called_out(self):
        _s, entry = priced(("2026-11-15", 800), ("2026-11-27", 880))
        self.assertEqual(watch.verdict(entry, SALE)["state"], "worse")

    def test_a_price_from_another_season_is_not_the_comparison(self):
        _s, entry = priced(("2026-08-01", 1200), ("2026-11-27", 900))
        said = watch.verdict(entry, SALE)
        self.assertNotEqual(said["state"], "real")
        self.assertIn("nothing recorded", said["text"])


class TestAllIn(unittest.TestCase):

    def test_a_sailing_is_costed_like_a_ranked_cruise(self):
        _s, entry = priced(("2026-11-02", 900))
        cost = watch.all_in(entry, PROFILE, rates(), score.expected_flight_usd)
        # Two balcony fares as entered, plus fees, tips, onboard, ashore, the drive.
        self.assertGreater(cost["total_usd"], 1800 + 500)
        self.assertEqual(cost["port"]["port"], "mobile")


def ranked_cruise(title, nights=7, total=4000, region="caribbean", port="mobile", fp="a"):
    deal = Deal(source="t", title=title, url="http://x", kind="cruise", price=600,
                currency="USD", nights=nights, fingerprint=fp)
    deal.trip = {"region": region, "total_usd": total, "total_home": total,
                 "cruise_port": {"port": port}}
    return deal


class TestFeeds(unittest.TestCase):

    def setUp(self):
        self.state = watch.load(os.path.join(tempfile.mkdtemp(), "none.json"))
        self.feed = watch.add_feed(self.state, "Gulf week", regions=["caribbean"],
                                   min_nights=5, max_nights=8, max_all_in=4500,
                                   ports=["gulf"])

    def test_a_fitting_cruise_matches(self):
        self.assertTrue(watch.matches(self.feed, ranked_cruise("7-night W Caribbean")))

    def test_each_rule_can_refuse(self):
        self.assertFalse(watch.matches(self.feed, ranked_cruise("x", region="alaska")))
        self.assertFalse(watch.matches(self.feed, ranked_cruise("x", nights=11)))
        self.assertFalse(watch.matches(self.feed, ranked_cruise("x", total=5200)))
        self.assertFalse(watch.matches(self.feed, ranked_cruise("x", port="los angeles")))

    def test_a_match_alerts_once(self):
        found = watch.feed_matches(self.state, [ranked_cruise("7-night W Caribbean")])
        self.assertEqual(len(watch.new_matches(self.state, found)), 1)
        self.assertEqual(watch.new_matches(self.state, found), [])


class TestReminder(unittest.TestCase):

    def test_reminds_on_a_sale_day_until_priced(self):
        state, entry = priced(("2026-11-02", 900))
        self.assertEqual(watch.needs_reminder(state, today=date(2026, 11, 20)), [])
        self.assertEqual(len(watch.needs_reminder(state, today=date(2026, 11, 27))), 1)
        watch.record_price(state, entry["id"], 850, when=date(2026, 11, 27))
        self.assertEqual(watch.needs_reminder(state, today=date(2026, 11, 27)), [])


class TestReport(unittest.TestCase):

    def test_the_report_leads_with_the_verdict(self):
        state, _entry = priced(("2026-11-15", 880), ("2026-11-27", 800))
        html = render.watch_html(state, {}, PROFILE, rates(), score.expected_flight_usd)
        self.assertIn("A real sale", html)
        self.assertIn("all-in for 2", html)

    def test_nothing_watched_adds_nothing(self):
        state = watch.load(os.path.join(tempfile.mkdtemp(), "none.json"))
        self.assertEqual(render.watch_html(state, {}, PROFILE, rates(),
                                           score.expected_flight_usd), "")


if __name__ == "__main__":
    unittest.main()
