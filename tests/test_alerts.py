"""Fare alerts: what counts as a change, and where an alert may go.

Change detection is the part that decides whether the author is told about a
real drop or nagged every morning, so most of these tests are about it. The
delivery tests check that nothing leaves the machine unless the profile names
a remote backend, without sending anything anywhere.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import alerts  # noqa: E402
from farewatch.models import Deal  # noqa: E402

CFG = alerts.settings({"alerts": {"new_deal_min_score": 65, "drop_pct": 15,
                                  "track_min_score": 50, "max_per_run": 3}})


def deal(dest="tokyo", price=800.0, score=60.0, kind="flight", origin="chicago",
         nights=7, cabin="economy", title=None):
    d = Deal(source="t", title=title or "%s %s" % (dest, price),
             url="http://x/%s" % dest, kind=kind, price=price, currency="USD",
             destination=dest, origin=origin, cabin=cabin, nights=nights)
    d.price_usd = price
    d.score = score
    d.trip = {"deal_home": price, "nights": nights, "total_home": price * 2}
    return d


def snap(*deals):
    return alerts.snapshot(list(deals))


class Detection(unittest.TestCase):

    def test_first_run_alerts_on_nothing(self):
        self.assertEqual(alerts.detect(None, snap(deal(score=90)), CFG), [])

    def test_unchanged_ranking_is_silent(self):
        s = snap(deal(), deal("lisbon", 500, 70))
        self.assertEqual(alerts.detect(s, s, CFG), [])

    def test_new_route_above_threshold_alerts(self):
        found = alerts.detect(snap(deal()), snap(deal(), deal("lisbon", 400, 66)), CFG)
        self.assertEqual([a.kind for a in found], ["new"])
        self.assertIn("lisbon", found[0].route)

    def test_new_route_below_threshold_is_silent(self):
        found = alerts.detect(snap(deal()), snap(deal(), deal("lisbon", 400, 64.9)), CFG)
        self.assertEqual(found, [])

    def test_drop_at_threshold_alerts(self):
        found = alerts.detect(snap(deal(price=1000)), snap(deal(price=850)), CFG)
        self.assertEqual([a.kind for a in found], ["drop"])
        self.assertAlmostEqual(found[0].drop_pct, 15.0)
        self.assertEqual((found[0].previous, found[0].price), (1000, 850))

    def test_drop_under_threshold_is_silent(self):
        self.assertEqual(
            alerts.detect(snap(deal(price=1000)), snap(deal(price=860)), CFG), [])

    def test_rise_is_silent(self):
        self.assertEqual(
            alerts.detect(snap(deal(price=800)), snap(deal(price=1200)), CFG), [])

    def test_drop_on_untracked_route_is_silent(self):
        # Neither run scored the route as worth watching.
        found = alerts.detect(snap(deal(price=1000, score=40)),
                              snap(deal(price=500, score=45)), CFG)
        self.assertEqual(found, [])

    def test_drop_that_lifts_a_route_into_tracking_alerts(self):
        found = alerts.detect(snap(deal(price=1000, score=40)),
                              snap(deal(price=500, score=55)), CFG)
        self.assertEqual([a.kind for a in found], ["drop"])

    def test_price_drop_is_not_misread_as_new(self):
        # The fingerprint buckets price, so the cheaper fare is a different
        # fingerprint; keyed by route it must still be a drop, not a "new".
        old, new = deal(price=1000, score=70), deal(price=700, score=70)
        new.fingerprint, old.fingerprint = "b", "a"
        found = alerts.detect(snap(old), snap(new), CFG)
        self.assertEqual([a.kind for a in found], ["drop"])

    def test_cabin_and_origin_are_separate_routes(self):
        before = snap(deal(price=1000))
        after = snap(deal(price=1000), deal(price=400, cabin="business", score=70),
                     deal(price=400, origin="denver", score=70))
        found = alerts.detect(before, after, CFG)
        self.assertEqual(sorted(a.kind for a in found), ["new", "new"])

    def test_stays_compare_per_night(self):
        # A 3-night package after a 7-night one is not a 57% drop.
        before = snap(deal(kind="package", price=1400, nights=7, origin=None))
        after = snap(deal(kind="package", price=600, nights=3, origin=None))
        self.assertEqual(alerts.detect(before, after, CFG), [])

    def test_stay_without_nights_is_never_a_drop(self):
        before = snap(deal(kind="hotel", price=1400, nights=None, origin=None))
        after = snap(deal(kind="hotel", price=100, nights=None, origin=None))
        self.assertEqual(alerts.detect(before, after, CFG), [])

    def test_snapshot_keeps_cheapest_and_best_score(self):
        s = snap(deal(price=900, score=80), deal(price=700, score=55))
        (entry,) = s.values()
        self.assertEqual((entry["price"], entry["score"]), (700, 80))

    def test_drops_sort_before_new_and_by_size(self):
        before = snap(deal("tokyo", 1000), deal("paris", 1000))
        after = snap(deal("tokyo", 800), deal("paris", 500),
                     deal("lisbon", 300, 90))
        found = alerts.detect(before, after, CFG)
        self.assertEqual([a.kind for a in found], ["drop", "drop", "new"])
        self.assertGreater(found[0].drop_pct, found[1].drop_pct)

    def test_compose_caps_and_counts_the_rest(self):
        found = [alerts.Alert("new", str(i), "r%d" % i, 70, "t", "u")
                 for i in range(5)]
        title, body, shown = alerts.compose(found, CFG)
        self.assertEqual(title, "Farewatch: 5 fare alerts")
        self.assertEqual(len(shown), 3)
        self.assertTrue(body.endswith("+2 more in the report"))

    def test_settings_default_and_override(self):
        self.assertEqual(alerts.settings({})["backends"], ["toast"])
        self.assertEqual(alerts.settings({"alerts": {"drop_pct": 30}})["drop_pct"], 30)


class Recorder(alerts.Notifier):
    name = "rec"

    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, title, body, shown, report_path=None):
        if self.fail:
            raise RuntimeError("down")
        self.sent.append((title, body))


class RunAndState(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "state.json")
        self.profile = {"alerts": {"drop_pct": 15, "track_min_score": 50}}

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, ranked, backend, **kw):
        return alerts.run(ranked, self.profile, state_path=self.path,
                          log=lambda m: None, backends=[backend], **kw)

    def test_baseline_then_drop_then_quiet(self):
        rec = Recorder()
        self.assertEqual(self.go([deal(price=1000)], rec)[0], [])
        found, failures = self.go([deal(price=700)], rec)
        self.assertEqual(([a.kind for a in found], failures), (["drop"], []))
        self.assertEqual(len(rec.sent), 1)
        # Same price next day: already told, so silent.
        self.assertEqual(self.go([deal(price=700)], rec)[0], [])
        self.assertEqual(len(rec.sent), 1)

    def test_failed_delivery_still_saves_state_and_reports(self):
        self.go([deal(price=1000)], Recorder())
        found, failures = self.go([deal(price=700)], Recorder(fail=True))
        self.assertEqual(len(found), 1)
        self.assertEqual(failures, ["rec: down"])
        self.assertEqual(self.go([deal(price=700)], Recorder())[0], [])

    def test_dry_run_sends_and_saves_nothing(self):
        rec = Recorder()
        self.go([deal(price=1000)], rec, dry_run=True)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(rec.sent, [])

    def test_corrupt_state_is_treated_as_first_run(self):
        with open(self.path, "w") as fh:
            fh.write("{not json")
        self.assertIsNone(alerts.load_state(self.path))


class Delivery(unittest.TestCase):

    def test_default_backends_are_local_only(self):
        built = alerts.notifiers(alerts.settings({}))
        self.assertEqual([n.name for n in built], ["toast"])
        self.assertFalse(any(n.remote for n in built))

    def test_unknown_backend_is_an_error(self):
        with self.assertRaises(ValueError):
            alerts.notifiers({"backends": ["sms"]})

    def test_bad_backend_config_is_reported_not_raised(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "s.json")
        profile = {"alerts": {"backends": ["ntfy"], "ntfy": {}}}
        alerts.run([deal(price=1000)], profile, state_path=path, log=lambda m: None)
        found, failures = alerts.run([deal(price=600)], profile, state_path=path,
                                     log=lambda m: None)
        self.assertEqual(len(found), 1)
        self.assertTrue(failures and failures[0].startswith("config:"))

    def test_ntfy_has_no_default_server_and_wants_https(self):
        with self.assertRaises(ValueError):
            alerts.NtfyNotifier({"topic": "x"})
        with self.assertRaises(ValueError):
            alerts.NtfyNotifier({"server": "http://box.lan", "topic": "x"})
        alerts.NtfyNotifier({"server": "http://box.lan", "topic": "x",
                             "allow_http": True})

    def test_ntfy_request_shape(self):
        sent = []

        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        n = alerts.NtfyNotifier({"server": "https://ntfy.example/", "topic": "fw-abc"},
                                opener=lambda req, timeout: sent.append(req) or Resp(),
                                env={"FAREWATCH_NTFY_TOKEN": "tk"})
        a = alerts.Alert("drop", "k", "flight Tokyo", 70, "t", "http://deal")
        n.send("Farewatch: 1 fare alert", "line one", [a])
        (req,) = sent
        self.assertEqual(req.full_url, "https://ntfy.example/fw-abc")
        self.assertEqual(req.data, b"line one")
        self.assertEqual(req.get_header("Click"), "http://deal")
        self.assertEqual(req.get_header("Authorization"), "Bearer tk")

    def test_email_needs_password_from_environment(self):
        cfg = {"host": "smtp.example", "user": "me@example", "to": "me@example"}
        with self.assertRaises(RuntimeError):
            alerts.EmailNotifier(cfg, env={}).send("t", "b", [])

    def test_email_sends_via_smtp(self):
        calls = []

        class FakeSMTP:
            def __init__(self, host, port):
                calls.append(("open", host, port))

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, user, pw):
                calls.append(("login", user, pw))

            def send_message(self, msg):
                calls.append(("send", msg["To"], msg["Subject"]))

        cfg = {"host": "smtp.example", "user": "me@example", "to": "me@example"}
        n = alerts.EmailNotifier(cfg, smtp_factory=FakeSMTP,
                                 env={"FAREWATCH_SMTP_PASSWORD": "pw"})
        n.send("Farewatch: 1 fare alert", "b",
               [alerts.Alert("new", "k", "l", 70, "t", "u")])
        self.assertEqual(calls, [("open", "smtp.example", 465),
                                 ("login", "me@example", "pw"),
                                 ("send", "me@example", "Farewatch: 1 fare alert")])

    def test_toast_xml_escapes_and_script_quotes(self):
        t = alerts.ToastNotifier()
        xml = t.xml("A & B", "it's <cheap>", r"C:\out\index.html")
        self.assertIn("A &amp; B", xml)
        self.assertIn("&lt;cheap&gt;", xml)
        self.assertIn('launch="file:///C:/out/index.html"', xml)
        self.assertIn("it''s", t.script(xml))

    @unittest.skipUnless(sys.platform.startswith("win"), "toast is Windows-only")
    def test_toast_invokes_windows_powershell(self):
        seen = []

        class Done:
            returncode, stderr = 0, ""

        t = alerts.ToastNotifier(runner=lambda cmd, **kw: seen.append(cmd) or Done())
        t.send("title", "body", [])
        self.assertEqual(seen[0][0], "powershell.exe")
        self.assertIn("-EncodedCommand", seen[0])


if __name__ == "__main__":
    unittest.main()
