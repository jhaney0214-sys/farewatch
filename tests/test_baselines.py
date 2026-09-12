"""Learned price baselines.

The scorer shipped with a fare curve fitted by eye. These tests cover the
machinery that lets observed history correct it, the backoff that lets evidence
accumulate at all, and the guards that stop thin or mismatched history from
making things worse.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import baselines, faremodel, fx, score, store  # noqa: E402
from farewatch.models import Deal  # noqa: E402


def make_rates():
    return fx.Rates({"USD": 1.0, "EUR": 0.90, "JPY": 150.0},
                    {"USD": 1.0, "EUR": 0.90, "JPY": 125.0}, as_of="2026-08-27")


def make_deal(**kw):
    base = dict(source="test", title="t", url="http://x", kind="flight",
                price=500.0, currency="USD", destination="tokyo",
                origin="chicago", basis="per_person")
    base.update(kw)
    return Deal(**base)


PROFILE = {
    "home_cities": ["chicago"],
    "home_airports": ["ORD"],
    "home_currency": "USD",
    "travel_style": "mid",
    "travelers": 2,
    "max_trip_budget": 8000,
    "wishlist": [],
    "preferred_months": [],
}


def at_ratio(origin, destination, ratio, cabin="economy"):
    """A price that sits at `ratio` of the modelled fare for that route."""
    return faremodel.expected_flight_usd(origin, destination, cabin) * ratio


def seed(conn, rows):
    """rows: (kind, origin, destination, unit_usd, cabin, nights, basis)."""
    now = "2026-08-01T00:00:00+00:00"
    for i, row in enumerate(rows):
        kind, origin, dest, unit, cabin, nights, basis = row
        conn.execute(
            "INSERT INTO deals (fingerprint, first_seen, last_seen, times_seen,"
            " kind, origin, destination, price_usd, unit_usd, cabin, nights,"
            " basis, title, url, payload)"
            " VALUES (?,?,?,1,?,?,?,?,?,?,?,?,?,?,?)",
            ("fp%d" % i, now, now, kind, origin, dest, unit, unit, cabin,
             nights, basis, "t%d" % i, "http://x/%d" % i, "{}"))
    conn.commit()


class TestFareModel(unittest.TestCase):

    def test_distance_drives_the_curve(self):
        short = faremodel.expected_flight_usd("chicago", "new york")
        long_haul = faremodel.expected_flight_usd("chicago", "tokyo")
        self.assertGreater(long_haul, short)

    def test_cabin_multiplies(self):
        economy = faremodel.expected_flight_usd("chicago", "tokyo", "economy")
        business = faremodel.expected_flight_usd("chicago", "tokyo", "business")
        self.assertAlmostEqual(business / economy, faremodel.CABIN_MULT["business"])

    def test_unknown_route_has_no_model(self):
        self.assertIsNone(faremodel.expected_flight_usd("atlantis", "tokyo"))

    def test_distance_bands_are_ordered_and_stable(self):
        self.assertEqual(faremodel.distance_band("chicago", "new york"), "<1500km")
        self.assertEqual(faremodel.distance_band("chicago", "tokyo"), "<12000km")
        self.assertEqual(faremodel.distance_band("new york", "sydney"), ">=12000km")
        self.assertIsNone(faremodel.distance_band("atlantis", "tokyo"))


class TestNightlyRate(unittest.TestCase):
    """Lodging observations only compare if they mean the same thing."""

    def test_nightly_basis_passes_through(self):
        self.assertEqual(baselines.nightly_rate(159, "per_room_night", None), 159)
        self.assertEqual(baselines.nightly_rate(159, "per_night", 3), 159)

    def test_stay_total_divides_by_nights(self):
        # REGRESSION: a weeklong $779 getaway banked as a nightly rate gave
        # Phuket a $414 "typical night", about eight times the real figure.
        self.assertAlmostEqual(baselines.nightly_rate(779, "total", 7), 111.28, 1)

    def test_stay_total_without_nights_is_unusable(self):
        self.assertIsNone(baselines.nightly_rate(779, "total", None))

    def test_per_person_assumes_a_shared_room(self):
        self.assertAlmostEqual(baselines.nightly_rate(300, "per_person", 3), 200.0)

    def test_junk_is_rejected(self):
        self.assertIsNone(baselines.nightly_rate(0, "per_night", 1))
        self.assertIsNone(baselines.nightly_rate(None, "per_night", 1))
        self.assertIsNone(baselines.nightly_rate(-50, "per_night", 1))


class TestConfidence(unittest.TestCase):
    """History earns influence rather than switching it on."""

    def test_too_few_samples_have_no_say(self):
        self.assertEqual(baselines.confidence(0), 0.0)
        self.assertEqual(baselines.confidence(baselines.MIN_SAMPLES - 1), 0.0)

    def test_reaching_the_threshold_counts_for_something(self):
        # REGRESSION: this returned exactly 0.0, so a level that had just
        # reached MIN_SAMPLES was skipped as though it had no data at all.
        self.assertEqual(baselines.confidence(baselines.MIN_SAMPLES),
                         baselines.MIN_WEIGHT)
        self.assertGreater(baselines.confidence(baselines.MIN_SAMPLES), 0.0)

    def test_plenty_of_samples_take_over(self):
        self.assertEqual(baselines.confidence(baselines.FULL_SAMPLES), 1.0)
        self.assertEqual(baselines.confidence(baselines.FULL_SAMPLES + 50), 1.0)

    def test_confidence_ramps_between(self):
        mid = baselines.confidence(
            (baselines.MIN_SAMPLES + baselines.FULL_SAMPLES) // 2)
        self.assertTrue(0.0 < mid < 1.0)


class TestSample(unittest.TestCase):

    def build(self, ratios):
        s = baselines.Sample()
        for r in ratios:
            s.add(r, r * 100, "2026-08-01T00:00:00+00:00")
        return s

    def test_median_ratio(self):
        self.assertEqual(self.build([0.8, 1.0, 1.2]).median_ratio, 1.0)

    def test_percentile(self):
        s = self.build([0.6, 0.8, 1.0, 1.2])
        self.assertEqual(s.percentile_of(0.5), 1.0)
        self.assertEqual(s.percentile_of(1.5), 0.0)
        self.assertEqual(s.percentile_of(0.9), 0.5)

    def test_cheapest_tracks_raw_price(self):
        self.assertEqual(self.build([0.6, 1.2]).cheapest, 60.0)

    def test_empty_sample_has_no_opinion(self):
        s = baselines.Sample()
        self.assertIsNone(s.median_ratio)
        self.assertIsNone(s.percentile_of(1.0))


class TestRatioFiling(unittest.TestCase):
    """Every observation is filed at several levels of specificity at once."""

    def test_one_fare_lands_at_every_level(self):
        h = baselines.Baselines()
        self.assertTrue(h.add_flight("chicago", "tokyo", "economy",
                                     at_ratio("chicago", "tokyo", 0.8)))
        for level in baselines.FLIGHT_LEVELS:
            self.assertEqual(sum(len(s) for s in h.flights[level].values()), 1,
                             "level %s" % level)

    def test_ratio_is_scale_free(self):
        """The point of storing ratios: a short hop and a long haul compare."""
        h = baselines.Baselines()
        h.add_flight("chicago", "new york", "economy",
                     at_ratio("chicago", "new york", 0.75))
        h.add_flight("chicago", "tokyo", "economy",
                     at_ratio("chicago", "tokyo", 0.75))
        pooled = h.flights["cabin"][("economy",)]
        self.assertEqual(len(pooled), 2)
        for ratio in pooled.ratios:
            self.assertAlmostEqual(ratio, 0.75, places=6)

    def test_absurd_ratios_are_refused(self):
        h = baselines.Baselines()
        self.assertFalse(h.add_flight("chicago", "tokyo", "economy", 5.0))
        self.assertFalse(h.add_flight("chicago", "tokyo", "economy", 500000.0))
        self.assertEqual(len(h.flights["cabin"]), 0)

    def test_unmodellable_route_is_skipped(self):
        h = baselines.Baselines()
        self.assertFalse(h.add_flight(None, "tokyo", "economy", 700))
        self.assertFalse(h.add_flight("atlantis", "tokyo", "economy", 700))

    def test_stays_file_at_city_country_and_global(self):
        h = baselines.Baselines()
        self.assertTrue(h.add_stay("lisbon", 95.0))
        self.assertEqual(len(h.lodging["city"]), 1)
        self.assertEqual(len(h.lodging["country"]), 1)
        self.assertEqual(len(h.lodging["global"]), 1)


class TestBackoff(unittest.TestCase):
    """The change that makes any of this usable: coarser keys catch the misses."""

    def full(self, n=None):
        return n if n is not None else baselines.FULL_SAMPLES

    def test_exact_route_wins_when_it_has_evidence(self):
        h = baselines.Baselines()
        for _ in range(self.full()):
            h.add_flight("chicago", "tokyo", "economy",
                         at_ratio("chicago", "tokyo", 0.7))
        found = h.flight("chicago", "tokyo", "economy")
        self.assertEqual(found.level, "route")

    def test_unseen_route_still_gets_a_baseline(self):
        """The whole reason for the rewrite.

        Under the old exact-route key this route had nothing and the correction
        never fired. Observations from *other* routes of similar length now
        carry it, because they are stored as ratios.
        """
        h = baselines.Baselines()
        for origin in ("chicago", "new york", "dallas", "denver",
                       "atlanta", "boston"):
            h.add_flight(origin, "tokyo", "economy",
                         at_ratio(origin, "tokyo", 0.7))
        found = h.flight("seattle", "tokyo", "economy")
        self.assertTrue(found)
        self.assertIn(found.level, ("destination", "country", "distance", "cabin"))
        self.assertGreater(found.n, 0)

    def test_backoff_reaches_the_distance_band(self):
        h = baselines.Baselines()
        # Long hauls to a variety of places, none of them the one asked about.
        for origin, dest in (("chicago", "tokyo"), ("new york", "tokyo"),
                             ("dallas", "seoul"), ("denver", "seoul"),
                             ("boston", "hong kong"), ("atlanta", "bangkok")):
            h.add_flight(origin, dest, "economy", at_ratio(origin, dest, 0.8))
        found = h.flight("seattle", "taipei", "economy")
        self.assertTrue(found)
        self.assertIn(found.level, ("distance", "cabin"))

    def test_nothing_at_all_is_an_empty_lookup(self):
        found = baselines.Baselines().flight("chicago", "tokyo", "economy")
        self.assertFalse(found)
        self.assertEqual(found.n, 0)
        self.assertIsNone(found.describe("tokyo"))

    def test_cabins_do_not_pool_together(self):
        h = baselines.Baselines()
        for _ in range(baselines.FULL_SAMPLES):
            h.add_flight("chicago", "tokyo", "business",
                         at_ratio("chicago", "tokyo", 0.6, "business"))
        self.assertTrue(h.flight("chicago", "tokyo", "business"))
        self.assertFalse(h.flight("chicago", "tokyo", "economy"))

    def test_level_is_named_in_plain_words(self):
        h = baselines.Baselines()
        for origin in ("chicago", "new york", "dallas", "denver"):
            h.add_flight(origin, "tokyo", "economy", at_ratio(origin, "tokyo", 0.7))
        found = h.flight("seattle", "tokyo", "economy")
        self.assertIn("Tokyo", found.describe("tokyo"))

    def test_hotel_scope_reads_as_in_not_to(self):
        h = baselines.Baselines()
        for _ in range(baselines.FULL_SAMPLES):
            h.add_stay("lisbon", 80.0)
        found = h.stay("lisbon")
        self.assertTrue(found.describe("lisbon", "hotel").startswith("in "))


class TestCalibrate(unittest.TestCase):

    def sample_at(self, ratio, n):
        h = baselines.Baselines()
        for _ in range(n):
            h.add_flight("chicago", "tokyo", "economy",
                         at_ratio("chicago", "tokyo", ratio))
        return h, h.flight("chicago", "tokyo", "economy")

    def test_thin_evidence_leaves_the_model_alone(self):
        h, found = self.sample_at(0.5, baselines.MIN_SAMPLES - 1)
        self.assertFalse(found)
        self.assertEqual(h.calibrate(1000.0, found), 1000.0)

    def test_full_evidence_applies_the_ratio(self):
        h, found = self.sample_at(0.5, baselines.FULL_SAMPLES)
        self.assertEqual(found.weight, 1.0)
        self.assertAlmostEqual(h.calibrate(1000.0, found), 500.0)

    def test_partial_evidence_moves_part_way(self):
        h, found = self.sample_at(0.5, baselines.MIN_SAMPLES + 2)
        adjusted = h.calibrate(1000.0, found)
        self.assertTrue(500.0 < adjusted < 1000.0)

    def test_correction_is_a_multiplier_not_a_replacement(self):
        """Route shape survives; only the systematic error is removed."""
        h, found = self.sample_at(0.5, baselines.FULL_SAMPLES)
        short = faremodel.expected_flight_usd("chicago", "new york")
        long_haul = faremodel.expected_flight_usd("chicago", "tokyo")
        self.assertGreater(h.calibrate(long_haul, found),
                           h.calibrate(short, found))

    def test_missing_model_survives(self):
        h, found = self.sample_at(0.5, baselines.FULL_SAMPLES)
        self.assertIsNone(h.calibrate(None, found))


class TestLoadFromDatabase(unittest.TestCase):

    def setUp(self):
        self.conn = store.connect(os.path.join(tempfile.mkdtemp(), "t.db"))

    def tearDown(self):
        self.conn.close()

    def test_flights_and_stays_both_load(self):
        seed(self.conn, [
            ("flight", "chicago", "tokyo", 900, "economy", None, "per_person"),
            ("hotel", None, "lisbon", 95, None, None, "per_room_night"),
        ])
        h = baselines.load(self.conn)
        self.assertEqual(len(h.flights["cabin"][("economy",)]), 1)
        self.assertEqual(len(h.lodging["city"]["lisbon"]), 1)

    def test_lodging_is_normalised_before_filing(self):
        seed(self.conn, [
            ("hotel", None, "phuket", 50, None, None, "per_room_night"),
            ("hotel", None, "phuket", 700, None, 7, "total"),
        ])
        self.assertEqual(sorted(baselines.load(self.conn).lodging["city"]["phuket"].prices),
                         [50.0, 100.0])

    def test_unusable_lodging_rows_are_dropped_not_guessed(self):
        seed(self.conn, [
            ("hotel", None, "phuket", 50, None, None, "per_room_night"),
            ("hotel", None, "phuket", 700, None, None, "total"),
        ])
        self.assertEqual(baselines.load(self.conn).lodging["city"]["phuket"].prices,
                         [50.0])

    def test_old_observations_fall_out_of_the_window(self):
        seed(self.conn, [
            ("flight", "chicago", "tokyo", 900, "economy", None, "per_person")])
        self.assertFalse(baselines.load(self.conn, window_days=0)
                         .flight("chicago", "tokyo", "economy"))

    def test_empty_database_is_harmless(self):
        h = baselines.load(self.conn)
        self.assertEqual(h.summary()["ready"], 0)
        self.assertFalse(h.flight("chicago", "tokyo"))

    def test_no_connection_is_harmless(self):
        self.assertEqual(baselines.load(None).summary()["ready"], 0)

    def test_summary_counts_ready_levels(self):
        seed(self.conn, [
            ("flight", "chicago", "tokyo", 900 + i * 10, "economy", None,
             "per_person") for i in range(baselines.MIN_SAMPLES)])
        summary = baselines.load(self.conn).summary()
        self.assertGreater(summary["ready"], 0)
        self.assertEqual(summary["flight_route_ready"], 1)


class TestDivergences(unittest.TestCase):
    """Reporting where the authored cost data looks wrong, never rewriting it."""

    def setUp(self):
        self.conn = store.connect(os.path.join(tempfile.mkdtemp(), "t.db"))

    def tearDown(self):
        self.conn.close()

    def test_extremes_are_reported_first(self):
        seed(self.conn, [
            ("hotel", None, "male", 60, None, None, "per_room_night")
        ] * baselines.MIN_SAMPLES + [
            ("hotel", None, "tampa", 150, None, None, "per_room_night")
        ] * baselines.MIN_SAMPLES)
        rows = baselines.divergences(baselines.load(self.conn),
                                     {"male": 150.0, "tampa": 157.0}.get)
        self.assertEqual(rows[0]["destination"], "male")
        self.assertLess(rows[0]["ratio"], 0.6)

    def test_thin_evidence_is_ignored(self):
        seed(self.conn, [
            ("hotel", None, "male", 60, None, None, "per_room_night")])
        self.assertEqual(
            baselines.divergences(baselines.load(self.conn), lambda d: 150.0), [])

    def test_missing_authored_value_is_skipped(self):
        seed(self.conn, [
            ("hotel", None, "male", 60, None, None, "per_room_night")
        ] * baselines.MIN_SAMPLES)
        self.assertEqual(
            baselines.divergences(baselines.load(self.conn), lambda d: None), [])


class TestHistoryChangesScoring(unittest.TestCase):

    def history_at(self, ratio, n=None, dest="tokyo"):
        h = baselines.Baselines()
        for i in range(n or baselines.FULL_SAMPLES):
            origin = ("chicago", "new york", "dallas", "denver",
                      "atlanta", "boston")[i % 6]
            h.add_flight(origin, dest, "economy", at_ratio(origin, dest, ratio))
        return h

    def test_history_corrects_a_wrong_fare_curve(self):
        """The point of the whole exercise.

        The straight-line model expects about $236 for New York to Punta Cana,
        so an entirely ordinary $323 fare reads as "above typical". Observations
        showing fares really run above the line move the expectation to match.
        """
        args = dict(origin="new york", destination="punta cana", price=323)
        history = self.history_at(1.4, dest="punta cana")

        without = score.score_deal(make_deal(**args), PROFILE, make_rates())
        with_history = score.score_deal(make_deal(**args), PROFILE, make_rates(),
                                        history=history)
        self.assertTrue(any("above typical" in r for r in without.reasons))
        self.assertFalse(any("above typical" in r for r in with_history.reasons))

    def test_percentile_wording_replaces_the_guessed_discount(self):
        history = self.history_at(1.0)
        deal = score.score_deal(
            make_deal(price=at_ratio("chicago", "tokyo", 0.4)),
            PROFILE, make_rates(), history=history)
        joined = " ".join(deal.reasons)
        self.assertIn("tracked", joined)
        self.assertNotIn("below typical", joined)

    def test_the_note_names_the_evidence_level(self):
        history = self.history_at(1.0)
        deal = score.score_deal(
            make_deal(price=at_ratio("chicago", "tokyo", 0.4)),
            PROFILE, make_rates(), history=history)
        self.assertIn("Tokyo", " ".join(deal.reasons))

    def test_a_pricey_deal_is_labelled_as_such(self):
        history = self.history_at(0.7)
        deal = score.score_deal(
            make_deal(price=at_ratio("chicago", "tokyo", 1.5)),
            PROFILE, make_rates(), history=history)
        self.assertIn("pricier than most", " ".join(deal.reasons))

    def test_thin_history_keeps_the_model_wording(self):
        history = self.history_at(1.0, n=baselines.MIN_SAMPLES - 1)
        deal = score.score_deal(
            make_deal(price=at_ratio("chicago", "tokyo", 0.4)),
            PROFILE, make_rates(), history=history)
        self.assertNotIn("tracked", " ".join(deal.reasons))

    def test_provenance_is_recorded_for_audit(self):
        history = self.history_at(1.0)
        deal = score.score_deal(
            make_deal(price=at_ratio("chicago", "tokyo", 0.4)),
            PROFILE, make_rates(), history=history)
        baseline = deal.trip["baseline"]
        self.assertEqual(baseline["history_weight"], 1.0)
        self.assertGreater(baseline["samples"], 0)
        self.assertIn(baseline["level"], baselines.FLIGHT_LEVELS)

    def test_uncalibrated_claims_are_labelled_estimates(self):
        """A price-check proved the bare curve wrong by 40% on a real route.

        Asiana LAX-BKK was posted at $741; the real market fare was $742 and
        Google rated it typical, where the curve called it 25% below. An
        unbacked figure is still worth showing, but not to the percent without
        saying what it is.
        """
        deal = score.score_deal(
            make_deal(price=at_ratio("chicago", "tokyo", 0.4)),
            PROFILE, make_rates(), history=None)
        joined = " ".join(deal.reasons)
        self.assertIn("est.", joined)

    def test_history_backed_claims_carry_no_estimate_hedge(self):
        deal = score.score_deal(
            make_deal(price=at_ratio("chicago", "tokyo", 0.4)),
            PROFILE, make_rates(), history=self.history_at(1.0))
        joined = " ".join(deal.reasons)
        self.assertIn("tracked", joined)
        self.assertNotIn("est.", joined)

    def test_scoring_without_history_still_works(self):
        deal = score.score_deal(make_deal(), PROFILE, make_rates(), history=None)
        self.assertGreater(deal.score, 0)

    def test_rank_accepts_history(self):
        ranked = score.rank([make_deal(price=400)], PROFILE, make_rates(),
                            self.history_at(1.0))
        self.assertEqual(len(ranked), 1)


class TestStoreMigration(unittest.TestCase):
    """An existing database keeps its history across a schema bump."""

    def test_migration_is_idempotent(self):
        conn = store.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.assertEqual(store.migrate(conn), [])
        columns = {row[1] for row in conn.execute("PRAGMA table_info(deals)")}
        for column in ("unit_usd", "cabin", "nights", "basis"):
            self.assertIn(column, columns)
        conn.close()

    def test_backfill_recovers_columns_from_payload(self):
        import json
        conn = store.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        payload = json.dumps({"cabin": "business", "nights": 5, "basis": "total",
                              "trip": {"unit_usd": 1234.0}})
        conn.execute(
            "INSERT INTO deals (fingerprint, first_seen, last_seen, times_seen,"
            " kind, destination, title, url, payload)"
            " VALUES ('f','2026-08-01T00:00:00+00:00','2026-08-01T00:00:00+00:00',"
            " 1,'flight','tokyo','t','u',?)", (payload,))
        conn.commit()
        self.assertEqual(store.backfill(conn), 1)
        row = conn.execute("SELECT unit_usd, cabin, nights, basis FROM deals"
                           " WHERE fingerprint = 'f'").fetchone()
        self.assertEqual(row["unit_usd"], 1234.0)
        self.assertEqual(row["cabin"], "business")
        self.assertEqual(row["nights"], 5)
        self.assertEqual(row["basis"], "total")
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
