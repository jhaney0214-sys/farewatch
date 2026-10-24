"""fw.refresh_dot against a fake DOT: python -m unittest tests.test_dot_refresh"""

import os
import sys
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fw  # noqa: E402
from farewatch import dotfares, positioning  # noqa: E402

PROFILE = {"positioning": {"base": "DSM"}}


class FakeDot:
    """Both build tools, as refresh_dot uses them, publishing `latest`."""

    def __init__(self, latest, fail=False):
        self.latest, self.fail, self.saved = latest, fail, []

    def latest_quarter(self):
        if self.fail:
            raise OSError("no network")
        return self.latest

    def fetch(self, *market):
        return []

    def build(self, rows, *market_and_base):
        q = {"quarters": [self.latest]}
        return dict(q, routes={"a|b": {}}) if not market_and_base else dict(
            q, fares={"x": {}}, base=market_and_base[1], market=market_and_base[0])

    def save(self, table, path=None):
        self.saved.append("fares" if "fares" in table else "routes")


class Refresh(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._check = fw.DOT_CHECK
        fw.DOT_CHECK = os.path.join(self.dir, "dot-check.json")
        dotfares._TABLE = {"quarters": ["2025Q4", "2026Q1"]}
        positioning._FARES = {"base": "des moines", "market": "Des Moines, IA",
                              "quarters": ["2025Q4", "2026Q1"]}

    def tearDown(self):
        fw.DOT_CHECK = self._check
        dotfares._TABLE = {}
        positioning._FARES = {}

    def run_with(self, dot, today=date(2026, 10, 24)):
        return fw.refresh_dot(PROFILE, lambda m: None, today, bp=dot, br=dot)

    def test_a_new_quarter_rebuilds_both_tables(self):
        dot = FakeDot("2026Q2")
        self.assertEqual(self.run_with(dot), ["routes", "positioning"])
        self.assertEqual(dot.saved, ["routes", "fares"])

    def test_current_tables_are_left_alone(self):
        dot = FakeDot("2026Q1")
        self.assertEqual(self.run_with(dot), [])
        self.assertEqual(dot.saved, [])

    def test_dot_is_asked_at_most_once_a_week(self):
        self.run_with(FakeDot("2026Q1"))
        dot = FakeDot("2026Q2")
        self.assertEqual(self.run_with(dot, date(2026, 10, 30)), [])
        self.assertEqual(self.run_with(dot, date(2026, 10, 31)), ["routes", "positioning"])

    def test_a_failed_check_changes_nothing_and_is_retried(self):
        dot = FakeDot("2026Q2", fail=True)
        self.assertEqual(self.run_with(dot), [])
        self.assertFalse(os.path.exists(fw.DOT_CHECK))

    def test_the_positioning_table_is_never_created(self):
        positioning._FARES = {}
        dot = FakeDot("2026Q2")
        self.assertEqual(self.run_with(dot), ["routes"])

    def test_a_changed_base_rebuilds_the_positioning_table(self):
        positioning._FARES = dict(positioning._FARES, base="omaha")
        self.assertEqual(self.run_with(FakeDot("2026Q1")), ["positioning"])


class RejectsIsReadOnly(unittest.TestCase):

    def test_rejects_does_not_record_the_run(self):
        import hashlib
        db = os.path.join(ROOT, "data", "farewatch.db")
        if not os.path.exists(db) or not os.path.isdir(os.path.join(ROOT, "data", "cache", "feeds")):
            self.skipTest("needs a local database and feed cache")
        before = hashlib.sha256(open(db, "rb").read()).hexdigest()
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            fw.main(["rejects", "--offline", "--quiet"])
        self.assertEqual(hashlib.sha256(open(db, "rb").read()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
