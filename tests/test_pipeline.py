"""Cost model, currency, scoring, storage and rendering.

Rates are pinned to fixed values rather than fetched, so a failure here always
means the logic changed and never that the euro moved.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import costs, fx, positioning, render, score, store  # noqa: E402
from farewatch.models import Deal, fingerprint  # noqa: E402


def make_rates(**overrides):
    """USD-based rates with a deliberate divergence between now and the average.

    JPY sits 20% weaker than its trailing year (a tailwind for a USD holder);
    CHF sits 10% stronger (a headwind). EUR is unchanged.
    """
    latest = {"USD": 1.0, "EUR": 0.90, "GBP": 0.78, "JPY": 150.0,
              "CHF": 0.80, "THB": 34.0, "MXN": 18.0}
    avg = {"USD": 1.0, "EUR": 0.90, "GBP": 0.78, "JPY": 125.0,
           "CHF": 0.888, "THB": 34.0}
    latest.update(overrides.get("latest", {}))
    avg.update(overrides.get("avg", {}))
    return fx.Rates(latest, avg, as_of="2026-08-27")


def make_deal(**kw):
    base = dict(source="test", title="t", url="http://x", kind="flight",
                price=500.0, currency="USD", destination="tokyo",
                origin="san francisco", basis="per_person")
    base.update(kw)
    return Deal(**base)


PROFILE = {
    "home_cities": ["san francisco"],
    "home_airports": ["SFO"],
    "home_currency": "USD",
    "travel_style": "mid",
    "travelers": 2,
    "max_trip_budget": 8000,
    "wishlist": ["japan"],
    "preferred_months": ["april"],
}


class TestRates(unittest.TestCase):

    def test_to_usd(self):
        self.assertAlmostEqual(make_rates().to_usd(90, "EUR"), 100.0)

    def test_convert(self):
        self.assertAlmostEqual(make_rates().convert(100, "USD", "EUR"), 90.0)

    def test_unknown_currency_is_none_not_zero(self):
        self.assertIsNone(make_rates().to_usd(100, "XYZ"))

    def test_tailwind_positive_when_destination_currency_weakened(self):
        tw = make_rates().tailwind("USD", "JPY")
        self.assertAlmostEqual(tw, 0.2, places=2)

    def test_tailwind_negative_when_destination_currency_strengthened(self):
        self.assertLess(make_rates().tailwind("USD", "CHF"), -0.05)

    def test_tailwind_zero_for_same_currency(self):
        self.assertEqual(make_rates().tailwind("USD", "USD"), 0.0)

    def test_tailwind_none_without_history(self):
        self.assertIsNone(make_rates().tailwind("USD", "MXN"))

    def test_describe_ignores_small_moves(self):
        rates = make_rates(latest={"JPY": 126.0})
        self.assertIsNone(rates.describe_tailwind("USD", "JPY"))

    def test_describe_reports_large_moves(self):
        note = make_rates().describe_tailwind("USD", "JPY")
        self.assertIn("20%", note)
        self.assertIn("further", note)


class TestPriceBasis(unittest.TestCase):

    def test_per_person_multiplies_by_party(self):
        deal = make_deal(basis="per_person", price=500)
        self.assertEqual(costs.price_as_total(deal, 7, 2), 1000)

    def test_total_does_not(self):
        deal = make_deal(basis="total", price=500)
        self.assertEqual(costs.price_as_total(deal, 7, 2), 500)

    def test_per_night_multiplies_by_nights_and_party(self):
        deal = make_deal(basis="per_night", price=100)
        self.assertEqual(costs.price_as_total(deal, 3, 2), 600)

    def test_room_night_shares_a_double(self):
        deal = make_deal(basis="per_room_night", price=100)
        self.assertEqual(costs.price_as_total(deal, 3, 2), 300)

    def test_room_night_needs_a_second_room_for_three(self):
        deal = make_deal(basis="per_room_night", price=100)
        self.assertEqual(costs.price_as_total(deal, 3, 3), 600)


class TestCostModel(unittest.TestCase):

    def test_flight_adds_lodging_and_ground(self):
        deal = make_deal(kind="flight", price=500, nights=7)
        trip = costs.breakdown(deal, PROFILE, make_rates())
        self.assertTrue(trip["known"])
        self.assertGreater(trip["lodging_usd"], 0)
        self.assertGreater(trip["ground_usd"], 0)
        self.assertGreater(trip["total_usd"], trip["deal_usd"])

    def test_package_lodging_is_already_included(self):
        deal = make_deal(kind="package", price=1200, nights=7)
        trip = costs.breakdown(deal, PROFILE, make_rates())
        self.assertTrue(trip["lodging_included"])
        self.assertEqual(trip["lodging_usd"], 0.0)

    def test_cruise_charges_onboard_not_lodging(self):
        deal = make_deal(kind="cruise", price=2000, nights=7, destination="nassau")
        trip = costs.breakdown(deal, PROFILE, make_rates())
        self.assertEqual(trip["lodging_usd"], 0.0)
        self.assertGreater(trip["onboard_usd"], 0)

    def test_expensive_destination_costs_more_on_the_ground(self):
        cheap = costs.breakdown(make_deal(destination="bangkok", nights=7),
                                PROFILE, make_rates())
        dear = costs.breakdown(make_deal(destination="zurich", nights=7),
                               PROFILE, make_rates())
        self.assertGreater(dear["ground_usd"], cheap["ground_usd"] * 2)

    def test_cheaper_fare_can_be_the_dearer_trip(self):
        """The entire premise of the project, asserted.

        A cheaper fare to an expensive country loses to a dearer fare to a cheap
        one once a week on the ground is counted.
        """
        zurich = costs.breakdown(
            make_deal(destination="zurich", price=300, nights=7),
            PROFILE, make_rates())
        bangkok = costs.breakdown(
            make_deal(destination="bangkok", price=450, nights=7),
            PROFILE, make_rates())
        self.assertLess(zurich["deal_usd"], bangkok["deal_usd"])
        self.assertGreater(zurich["total_usd"], bangkok["total_usd"])

    def test_currency_tailwind_reduces_ground_costs(self):
        strong = make_rates()                                  # yen 20% weak
        neutral = make_rates(latest={"JPY": 125.0})            # yen at average
        with_tailwind = costs.breakdown(
            make_deal(destination="tokyo", nights=7), PROFILE, strong)
        without = costs.breakdown(
            make_deal(destination="tokyo", nights=7), PROFILE, neutral)
        self.assertLess(with_tailwind["ground_usd"], without["ground_usd"])

    def test_unknown_destination_degrades_rather_than_crashes(self):
        deal = make_deal(destination="atlantis")
        trip = costs.breakdown(deal, PROFILE, make_rates())
        self.assertFalse(trip["known"])

    def test_sample_prices_are_in_home_currency(self):
        samples = costs.sample_prices("tokyo", make_rates(), "EUR")
        self.assertTrue(samples)
        labels = [label for label, _v in samples]
        self.assertIn("Beer", labels)


class TestScoring(unittest.TestCase):

    def test_home_airport_beats_a_foreign_one(self):
        rates = make_rates()
        mine = score.score_deal(make_deal(origin="san francisco"), PROFILE, rates)
        theirs = score.score_deal(make_deal(origin="london"), PROFILE, rates)
        self.assertGreater(mine.score, theirs.score)

    def test_wishlist_destination_scores_higher(self):
        rates = make_rates()
        wanted = score.score_deal(make_deal(destination="tokyo"), PROFILE, rates)
        other = score.score_deal(make_deal(destination="seoul"), PROFILE, rates)
        self.assertGreater(wanted.score, other.score)

    def test_over_budget_is_penalised(self):
        tight = dict(PROFILE, max_trip_budget=800)
        deal = score.score_deal(make_deal(price=3000, nights=7), tight, make_rates())
        self.assertIn("over your", " ".join(deal.reasons))

    def test_cheap_fare_reads_as_below_typical(self):
        deal = score.score_deal(
            make_deal(origin="san francisco", destination="seattle", price=90),
            PROFILE, make_rates())
        self.assertTrue(any("below typical" in r for r in deal.reasons))

    def test_assumed_duration_is_disclosed(self):
        deal = score.score_deal(
            make_deal(kind="package", price=249, nights=None, origin=None,
                      destination="new orleans"), PROFILE, make_rates())
        notes = " ".join(deal.reasons)
        if "below typical" in notes:
            self.assertIn("duration assumed", notes)

    def test_stated_duration_is_not_flagged(self):
        deal = score.score_deal(
            make_deal(kind="package", price=249, nights=3, origin=None,
                      destination="new orleans"), PROFILE, make_rates())
        self.assertNotIn("duration assumed", " ".join(deal.reasons))

    def test_avoid_list_excludes(self):
        profile = dict(PROFILE, avoid=["japan"])
        self.assertIsNotNone(score.excluded(make_deal(destination="tokyo"), profile))

    def test_require_reachable_origin_excludes_foreign_departures(self):
        profile = dict(PROFILE, require_reachable_origin=True)
        self.assertIsNotNone(score.excluded(make_deal(origin="london"), profile))
        self.assertIsNone(score.excluded(make_deal(origin="san francisco"), profile))

    def test_score_is_bounded(self):
        for price in (10, 500, 50000):
            deal = score.score_deal(make_deal(price=price), PROFILE, make_rates())
            self.assertGreaterEqual(deal.score, 0)
            self.assertLessEqual(deal.score, 100)

    def test_components_are_recorded_for_audit(self):
        deal = score.score_deal(make_deal(), PROFILE, make_rates())
        self.assertIn("value", deal.trip["components"])
        self.assertIn("reachable", deal.trip["components"])


class TestDedupe(unittest.TestCase):

    def test_same_route_and_price_collapses(self):
        deals = [make_deal(source="a", title="A", url="http://a"),
                 make_deal(source="b", title="B", url="http://b")]
        ranked = score.rank(deals, PROFILE, make_rates())
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].trip.get("also_seen_on"), ["b"])

    def test_different_prices_stay_separate(self):
        deals = [make_deal(price=500, url="http://a"),
                 make_deal(price=900, url="http://b")]
        self.assertEqual(len(score.rank(deals, PROFILE, make_rates())), 2)

    def test_fingerprint_needs_a_usd_price(self):
        # REGRESSION: fingerprinting before the USD price existed fell back to
        # the URL, so nothing ever deduped and eight identical Reykjavik
        # packages filled the top of the ranking.
        priced = make_deal()
        priced.price_usd = 500.0
        unpriced = make_deal()
        self.assertNotEqual(fingerprint(priced), fingerprint(unpriced))

    def test_ranking_is_sorted(self):
        deals = [make_deal(price=p, url="http://%d" % p) for p in (200, 5000, 900)]
        ranked = score.rank(deals, PROFILE, make_rates())
        self.assertEqual([d.score for d in ranked],
                         sorted([d.score for d in ranked], reverse=True))


class TestStore(unittest.TestCase):

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "t.db")
        self.conn = store.connect(self.path)

    def tearDown(self):
        self.conn.close()

    def test_first_run_is_all_new(self):
        deals = [make_deal(url="http://a")]
        deals[0].price_usd = 500.0
        deals[0].fingerprint = fingerprint(deals[0])
        self.assertEqual(store.sync(self.conn, deals), 1)
        self.assertTrue(deals[0].is_new)

    def test_second_sighting_is_not_new(self):
        deal = make_deal(url="http://a")
        deal.price_usd = 500.0
        deal.fingerprint = fingerprint(deal)
        store.sync(self.conn, [deal])
        again = make_deal(url="http://a")
        again.price_usd = 500.0
        again.fingerprint = fingerprint(again)
        self.assertEqual(store.sync(self.conn, [again]), 0)
        self.assertFalse(again.is_new)
        self.assertEqual(again.first_seen, deal.first_seen)

    def test_stats(self):
        deal = make_deal()
        deal.price_usd = 500.0
        deal.fingerprint = fingerprint(deal)
        store.sync(self.conn, [deal])
        store.record_run(self.conn, 10, 5, 1, 1)
        s = store.stats(self.conn)
        self.assertEqual(s["deals"], 1)
        self.assertEqual(s["runs"], 1)


class TestRender(unittest.TestCase):

    def test_writes_self_contained_html(self):
        rates = make_rates()
        deals = score.rank([make_deal(), make_deal(kind="hotel", price=120,
                                                   origin=None, url="http://h")],
                           PROFILE, rates)
        path = os.path.join(tempfile.mkdtemp(), "index.html")
        render.render(deals, PROFILE, rates, {"fetched": 10, "parsed": 2,
                                              "sources": ["test"]}, path)
        with open(path, encoding="utf-8") as fh:
            doc = fh.read()
        self.assertIn("<!doctype html>", doc)
        self.assertIn("Farewatch", doc)
        # Self-contained: nothing to fetch from anywhere.
        self.assertNotIn("<script src", doc)
        self.assertNotIn("<link rel=\"stylesheet\"", doc)
        self.assertIn("prefers-color-scheme", doc)

    def test_escapes_titles(self):
        rates = make_rates()
        deal = make_deal(title='<img src=x onerror="alert(1)">')
        ranked = score.rank([deal], PROFILE, rates)
        path = os.path.join(tempfile.mkdtemp(), "index.html")
        render.render(ranked, PROFILE, rates, {"sources": []}, path)
        with open(path, encoding="utf-8") as fh:
            doc = fh.read()
        self.assertNotIn("<img src=x", doc)
        self.assertIn("&lt;img", doc)

    def test_empty_ranking_still_renders(self):
        path = os.path.join(tempfile.mkdtemp(), "index.html")
        render.render([], PROFILE, make_rates(), {"sources": []}, path)
        self.assertTrue(os.path.exists(path))


REGIONAL_PROFILE = dict(
    PROFILE,
    home_cities=["des moines"],
    home_airports=["DSM", "OMA"],
    unreachable_origins="position",
    positioning={
        "enabled": True,
        "base": "DSM",
        # An illustrative regional nonstop map, not any airport's real one.
        "nonstop_from_base": ["ATL", "ORD", "LAX", "JFK", "MIA", "DFW", "LAS"],
        "max_positioning_usd": 600,
        "self_connect_warning": True,
    },
)


class TestPositioning(unittest.TestCase):
    """Reaching the airport the deal actually leaves from."""

    def curve(self):
        return score.expected_flight_usd

    def test_home_origin_costs_nothing(self):
        deal = make_deal(kind="flight", origin="omaha", destination="tokyo")
        cost = positioning.apply(deal, REGIONAL_PROFILE, make_rates(), self.curve(),
                                 score.home_keys(REGIONAL_PROFILE))
        self.assertEqual(cost, 0.0)
        self.assertIsNone(deal.trip["positioning"])

    def test_nonstop_origin_is_priced(self):
        deal = make_deal(kind="flight", origin="los angeles", destination="tokyo")
        cost = positioning.apply(deal, REGIONAL_PROFILE, make_rates(), self.curve(),
                                 score.home_keys(REGIONAL_PROFILE))
        self.assertGreater(cost, 0)
        self.assertTrue(deal.trip["positioning"]["nonstop"])

    def test_connecting_origin_costs_more_than_nonstop(self):
        """Same distance band, but one needs its own connection."""
        est_nonstop = positioning.estimate("los angeles", REGIONAL_PROFILE, self.curve())
        est_connect = positioning.estimate("seattle", REGIONAL_PROFILE, self.curve())
        self.assertTrue(est_nonstop["nonstop"])
        self.assertFalse(est_connect["nonstop"])
        # Seattle and LA are about equally far from Des Moines, so check the multiplier
        # is doing work by comparing cost per km rather than raw cost.
        from farewatch import places
        lax_rate = est_nonstop["per_person_usd"] / places.distance_km("des moines", "los angeles")
        sea_rate = est_connect["per_person_usd"] / places.distance_km("des moines", "seattle")
        self.assertGreater(sea_rate, lax_rate)

    def test_positioning_scales_with_party(self):
        solo = dict(REGIONAL_PROFILE, travelers=1)
        pair = dict(REGIONAL_PROFILE, travelers=2)
        rates, curve, home = make_rates(), self.curve(), score.home_keys(REGIONAL_PROFILE)
        a = positioning.apply(make_deal(origin="los angeles"), solo, rates, curve, home)
        b = positioning.apply(make_deal(origin="los angeles"), pair, rates, curve, home)
        self.assertAlmostEqual(b, a * 2, places=4)

    def test_itinerary_origins_are_not_positioned(self):
        """"Lisbon to Porto" starts wherever you live, not in Lisbon.

        The parser marks such an origin as not-a-departure, and nothing should
        charge you for a flight to the first stop on a tour.
        """
        deal = make_deal(kind="package", origin="lisbon", destination="porto",
                         origin_is_departure=False)
        cost = positioning.apply(deal, REGIONAL_PROFILE, make_rates(), self.curve(),
                                 score.home_keys(REGIONAL_PROFILE))
        self.assertEqual(cost, 0.0)

    def test_packages_with_a_real_departure_are_positioned(self):
        """"Flights from Vienna" genuinely requires you to be in Vienna."""
        deal = make_deal(kind="package", origin="vienna", destination="athens",
                         origin_is_departure=True)
        cost = positioning.apply(deal, REGIONAL_PROFILE, make_rates(), self.curve(),
                                 score.home_keys(REGIONAL_PROFILE))
        self.assertGreater(cost, 0)

    def test_itinerary_origin_is_reachability_neutral(self):
        value, _note = score.reachable_component(
            make_deal(kind="package", origin="lisbon", origin_is_departure=False),
            score.home_keys(REGIONAL_PROFILE))
        self.assertGreater(value, 0.5)

    def test_positioning_lands_in_the_total(self):
        rates = make_rates()
        near = score.score_deal(make_deal(origin="omaha", destination="tokyo"),
                                REGIONAL_PROFILE, rates)
        far = score.score_deal(make_deal(origin="los angeles", destination="tokyo"),
                               REGIONAL_PROFILE, rates)
        self.assertGreater(far.trip["total_home"], near.trip["total_home"])

    def test_disabled_positioning_costs_nothing(self):
        profile = dict(REGIONAL_PROFILE, positioning=dict(REGIONAL_PROFILE["positioning"],
                                                     enabled=False))
        cost = positioning.apply(make_deal(origin="los angeles"), profile,
                                 make_rates(), self.curve(),
                                 score.home_keys(profile))
        self.assertEqual(cost, 0.0)

    def test_transatlantic_repositioning_is_excluded(self):
        # REGRESSION: the ceiling was checked before scoring priced the leg, so
        # it never fired and $873-per-person repositioning to Prague ranked as
        # though the hop were free.
        deals = [make_deal(origin="prague", destination="bangkok", url="http://p")]
        ranked = score.rank(deals, REGIONAL_PROFILE, make_rates())
        self.assertEqual(ranked, [])

    def test_domestic_repositioning_survives_the_ceiling(self):
        deals = [make_deal(origin="chicago", destination="tokyo", url="http://c")]
        ranked = score.rank(deals, REGIONAL_PROFILE, make_rates())
        self.assertEqual(len(ranked), 1)
        self.assertIsNotNone(ranked[0].trip["positioning"])

    def test_reasons_explain_the_hop_and_its_risk(self):
        deal = score.score_deal(make_deal(origin="chicago", destination="tokyo"),
                                REGIONAL_PROFILE, make_rates())
        joined = " ".join(deal.reasons)
        self.assertIn("to reach Chicago from Des Moines", joined)
        self.assertIn("separate tickets", joined)

    def test_hide_policy_still_works_for_anyone_who_set_it(self):
        profile = dict(REGIONAL_PROFILE)
        profile.pop("unreachable_origins")
        profile["require_reachable_origin"] = True
        self.assertIsNotNone(score.excluded(make_deal(origin="chicago"), profile))


class TestAffiliateLinks(unittest.TestCase):
    """Outbound links can be rewritten through a tracker, but only on purpose."""

    TEMPLATE = "https://prf.hn/click/camref:1011l123/destination:{url}"

    def test_template_wraps_and_encodes(self):
        out = render.affiliate_url("https://x.com/a?b=1", self.TEMPLATE)
        self.assertTrue(out.startswith("https://prf.hn/click/"))
        self.assertIn("https%3A%2F%2Fx.com%2Fa%3Fb%3D1", out)

    def test_no_template_leaves_the_link_alone(self):
        for template in ("", None, "https://tracker.example/no-placeholder"):
            self.assertEqual(render.affiliate_url("https://x.com/a", template),
                             "https://x.com/a")

    def test_report_uses_the_template(self):
        rates = make_rates()
        deals = score.rank([make_deal(source="travelzoo",
                                      url="https://www.travelzoo.com/d/1")],
                           PROFILE, rates)
        path = os.path.join(tempfile.mkdtemp(), "index.html")
        render.render(deals, PROFILE, rates,
                      {"sources": ["travelzoo"],
                       "affiliates": {"travelzoo": self.TEMPLATE}}, path)
        with open(path, encoding="utf-8") as fh:
            doc = fh.read()
        self.assertIn("prf.hn/click", doc)

    def test_report_without_affiliates_keeps_raw_links(self):
        rates = make_rates()
        deals = score.rank([make_deal(url="https://www.travelzoo.com/d/1")],
                           PROFILE, rates)
        path = os.path.join(tempfile.mkdtemp(), "index.html")
        render.render(deals, PROFILE, rates, {"sources": []}, path)
        with open(path, encoding="utf-8") as fh:
            doc = fh.read()
        self.assertIn("https://www.travelzoo.com/d/1", doc)
        self.assertNotIn("prf.hn", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
