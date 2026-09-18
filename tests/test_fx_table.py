"""The currency table against the vocabulary it mirrors.

`HISTORY_SYMBOLS` is a hand-written claim about what the ECB publishes. On
2026-09-18 it was one currency out of date - BGN, dropped when Bulgaria
adopted the euro - and nothing had noticed, because the service answers 200
and silently omits an unknown symbol.

**Both sides had exactly thirty entries**, so a count check would have passed.
Only comparing the members found it.

These tests drive `audit_history_symbols` with a stub, so the suite stays
offline. `tools/check_fx.py` is the one that talks to the service.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import fx  # noqa: E402


class TheTableIsAuditable(unittest.TestCase):

    def test_a_table_in_step_reports_nothing(self):
        published = list(fx.HISTORY_SYMBOLS) + ["USD"]
        self.assertEqual(fx.audit_history_symbols(lambda: published), ([], []))

    def test_a_symbol_the_service_dropped_is_reported_stale(self):
        published = [s for s in fx.HISTORY_SYMBOLS if s != "JPY"] + ["USD"]
        stale, unlisted = fx.audit_history_symbols(lambda: published)
        self.assertEqual(stale, ["JPY"])
        self.assertEqual(unlisted, [])

    def test_a_symbol_the_service_added_is_reported_unlisted(self):
        published = list(fx.HISTORY_SYMBOLS) + ["USD", "XYZ"]
        stale, unlisted = fx.audit_history_symbols(lambda: published)
        self.assertEqual(stale, [])
        self.assertEqual(unlisted, ["XYZ"])

    def test_usd_is_never_reported_unlisted(self):
        """Its absence is deliberate - both feeds are USD-based."""
        published = list(fx.HISTORY_SYMBOLS) + ["USD"]
        self.assertNotIn("USD", fx.audit_history_symbols(lambda: published)[1])
        self.assertNotIn("USD", fx.HISTORY_SYMBOLS)

    def test_equal_counts_do_not_hide_a_swap(self):
        """The exact shape of the real defect: 30 against 30, one different."""
        published = [s for s in fx.HISTORY_SYMBOLS if s != "JPY"] + ["USD", "XYZ"]
        self.assertEqual(len(published) - 1, len(fx.HISTORY_SYMBOLS))
        stale, unlisted = fx.audit_history_symbols(lambda: published)
        self.assertEqual((stale, unlisted), (["JPY"], ["XYZ"]))

    def test_a_failed_fetch_raises_rather_than_reporting_clean(self):
        def broken():
            raise OSError("service unreachable")
        with self.assertRaises(OSError):
            fx.audit_history_symbols(broken)


class TheTableItself(unittest.TestCase):

    def test_no_duplicates(self):
        self.assertEqual(len(fx.HISTORY_SYMBOLS), len(set(fx.HISTORY_SYMBOLS)))

    def test_bgn_is_gone_and_stays_gone(self):
        """Bulgaria joined the euro on 2026-01-01; the ECB dropped the lev."""
        self.assertNotIn("BGN", fx.HISTORY_SYMBOLS)

    def test_every_symbol_is_a_three_letter_code(self):
        for code in fx.HISTORY_SYMBOLS:
            self.assertRegex(code, r"^[A-Z]{3}$")


if __name__ == "__main__":
    unittest.main()
