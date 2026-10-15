"""Tell the author when something worth acting on appears, instead of waiting.

A daily report nobody opens is the same as no report. After a refresh this
compares the ranking with the one from the previous alerting run and raises an
alert for only two things:

- a **new deal**: a route that was not in the last run and now scores at or
  above `new_deal_min_score`;
- a **drop**: a route that was in the last run, scoring at least
  `track_min_score`, whose best price has fallen by `drop_pct` percent or more.

Routes are compared, not fingerprints. A fingerprint buckets the price to $25,
so a fare that drops is a *different* fingerprint and would read as "new" -
the one change worth hearing about would be filed under the wrong label.

The first run with no saved state alerts on nothing and only records a
baseline, so switching this on does not dump the whole ranking on you.

Delivery is a small interface with three backends. Only the Windows toast is on
by default, and it never leaves the machine. Email and ntfy send trip data to
someone else's server and stay off until the profile names them.
"""

import base64
import json
import os
import smtplib
import ssl
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from xml.sax.saxutils import escape

from . import places

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "alerts-state.json")

DEFAULTS = {
    "new_deal_min_score": 68.0,
    "drop_pct": 15.0,
    "track_min_score": 50.0,
    "max_per_run": 5,
    # Only "toast" is safe to default: it never leaves this machine.
    "backends": ["toast"],
    "email": {},
    "ntfy": {},
}

REMOTE_BACKENDS = ("email", "ntfy")


def settings(profile):
    """The profile's `alerts` block over the defaults. Nothing is required."""
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in ((profile or {}).get("alerts") or {}).items()
                if not k.startswith("_")})
    return cfg


# --- change detection --------------------------------------------------------

def route_key(deal):
    return "|".join([deal.kind or "other", deal.origin or "?",
                     deal.destination or "?", deal.cabin or "economy"])


def comparable_price(deal):
    """A price that means the same thing on two different days for one route.

    Flights compare on the fare. Stays compare per night, because a 3-night
    and a 7-night package to the same city are not a 57% drop.
    """
    trip = deal.trip or {}
    price = trip.get("deal_home")
    if price is None:
        price = deal.price_usd
    if not price or price <= 0:
        return None
    if deal.kind != "flight":
        nights = trip.get("nights") or deal.nights
        if not nights or nights <= 0:
            return None
        return float(price) / float(nights)
    return float(price)


def snapshot(deals):
    """The best deal on each route: lowest comparable price, and its score."""
    routes = {}
    for deal in deals:
        if not deal.destination:
            continue
        price = comparable_price(deal)
        key = route_key(deal)
        here = {"price": price, "score": round(float(deal.score or 0), 1),
                "title": deal.title, "url": deal.url, "kind": deal.kind,
                "origin": deal.origin, "destination": deal.destination,
                "total": (deal.trip or {}).get("total_home")}
        have = routes.get(key)
        if have is None:
            routes[key] = here
            continue
        # Keep the cheapest offer on the route; the best score seen on it
        # decides whether the route is worth tracking at all.
        best_score = max(have["score"], here["score"])
        if price is not None and (have["price"] is None or price < have["price"]):
            routes[key] = here
        routes[key]["score"] = best_score
    return routes


@dataclass
class Alert:
    kind: str          # "new" | "drop"
    route: str
    label: str
    score: float
    title: str
    url: str
    price: float | None = None
    previous: float | None = None
    drop_pct: float | None = None

    def line(self, currency="USD"):
        if self.kind == "drop":
            return "%s down %.0f%% (%s -> %s)" % (
                self.label, self.drop_pct, _money(self.previous, currency),
                _money(self.price, currency))
        return "New: %s, score %.0f" % (self.label, self.score)


def _label(entry):
    dest = places.label(entry["destination"]) if entry.get("destination") else "?"
    if entry.get("origin"):
        origin = (places.city(entry["origin"]) or {}).get("name", entry["origin"])
        dest = "%s > %s" % (origin, dest)
    return "%s %s" % (entry.get("kind") or "deal", dest)


def detect(previous, current, cfg):
    """Alerts for what changed between two snapshots, most important first.

    `previous` of None means there is no saved state: nothing is alerted.
    """
    if previous is None:
        return []
    new_min = float(cfg["new_deal_min_score"])
    drop_min = float(cfg["drop_pct"])
    track_min = float(cfg["track_min_score"])

    alerts = []
    for key, now in current.items():
        before = previous.get(key)
        if before is None:
            if now["score"] >= new_min:
                alerts.append(Alert("new", key, _label(now), now["score"],
                                    now["title"], now["url"], price=now["price"]))
            continue
        if max(before.get("score") or 0, now["score"]) < track_min:
            continue
        old, new = before.get("price"), now["price"]
        if not old or not new or new >= old:
            continue
        pct = 100.0 * (old - new) / old
        if pct >= drop_min:
            alerts.append(Alert("drop", key, _label(now), now["score"],
                                now["title"], now["url"], price=new,
                                previous=old, drop_pct=round(pct, 1)))

    # Drops first (a price you were already watching moved), then by size or
    # score. The cap keeps a feed format change from becoming forty toasts.
    alerts.sort(key=lambda a: (a.kind != "drop", -(a.drop_pct or 0), -a.score))
    return alerts


def load_state(path=None):
    path = path or STATE_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("routes")
    except (OSError, ValueError, AttributeError):
        return None


def save_state(routes, path=None):
    path = path or STATE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"routes": routes}, fh, indent=1, default=str)
    os.replace(tmp, path)


# --- delivery ----------------------------------------------------------------

def _money(value, currency="USD"):
    if value is None:
        return "-"
    sign = "$" if currency == "USD" else currency + " "
    return "%s%s" % (sign, format(int(round(value)), ","))


def compose(alerts, cfg, currency="USD"):
    """(title, body, lines) for a batch, capped at max_per_run lines."""
    cap = max(1, int(cfg.get("max_per_run") or 5))
    shown = alerts[:cap]
    lines = [a.line(currency) for a in shown]
    if len(alerts) > cap:
        lines.append("+%d more in the report" % (len(alerts) - cap))
    n = len(alerts)
    title = "Farewatch: %d fare alert%s" % (n, "" if n == 1 else "s")
    return title, "\n".join(lines), shown


class Notifier:
    name = "base"
    remote = False

    def send(self, title, body, alerts, report_path=None):
        raise NotImplementedError


class ToastNotifier(Notifier):
    """A Windows toast through Windows PowerShell's WinRT bridge. Local only.

    Uses PowerShell's own registered app id, so no shortcut or registration is
    needed. Clicking the toast opens the report.
    """
    name = "toast"
    APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"

    def __init__(self, runner=None):
        self.runner = runner or subprocess.run

    def xml(self, title, body, report_path=None):
        texts = "".join("<text>%s</text>" % escape(t)
                        for t in [title] + body.split("\n")[:3])
        launch = ""
        if report_path:
            uri = "file:///" + report_path.replace("\\", "/")
            launch = ' activationType="protocol" launch="%s"' % escape(uri, {'"': "&quot;"})
        return ('<toast%s><visual><binding template="ToastGeneric">%s'
                "</binding></visual></toast>" % (launch, texts))

    def script(self, xml):
        quoted = xml.replace("'", "''")
        return "\n".join([
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null",
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null",
            "$x = New-Object Windows.Data.Xml.Dom.XmlDocument",
            "$x.LoadXml('%s')" % quoted,
            "$t = New-Object Windows.UI.Notifications.ToastNotification $x",
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('%s').Show($t)"
            % self.APP_ID,
        ])

    def send(self, title, body, alerts, report_path=None):
        if not sys.platform.startswith("win"):
            raise RuntimeError("toast needs Windows")
        script = self.script(self.xml(title, body, report_path))
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        # Windows PowerShell 5.1 specifically: PowerShell 7 cannot load WinRT
        # types this way.
        result = self.runner(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError("toast failed: %s" % (result.stderr or "").strip()[:200])


class EmailNotifier(Notifier):
    """Email to yourself over SMTP. The password comes from an environment
    variable, never from the profile, so it is not sitting in a JSON file."""
    name = "email"
    remote = True

    def __init__(self, cfg, smtp_factory=None, env=None):
        self.cfg = cfg or {}
        self.smtp_factory = smtp_factory
        self.env = os.environ if env is None else env
        for need in ("host", "user", "to"):
            if not self.cfg.get(need):
                raise ValueError("alerts.email needs '%s'" % need)

    def message(self, title, body, alerts):
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = self.cfg.get("from") or self.cfg["user"]
        msg["To"] = self.cfg["to"]
        links = "\n".join("- %s\n  %s" % (a.title, a.url) for a in alerts)
        msg.set_content(body + "\n\n" + links + "\n")
        return msg

    def send(self, title, body, alerts, report_path=None):
        var = self.cfg.get("password_env") or "FAREWATCH_SMTP_PASSWORD"
        password = self.env.get(var)
        if not password:
            raise RuntimeError("alerts.email: set %s to the SMTP password" % var)
        port = int(self.cfg.get("port") or 465)
        factory = self.smtp_factory
        if factory is None:
            if port == 465:
                factory = lambda h, p: smtplib.SMTP_SSL(  # noqa: E731
                    h, p, context=ssl.create_default_context(), timeout=30)
            else:
                factory = lambda h, p: smtplib.SMTP(h, p, timeout=30)  # noqa: E731
        with factory(self.cfg["host"], port) as smtp:
            if port != 465:
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(self.cfg["user"], password)
            smtp.send_message(self.message(title, body, alerts))


class NtfyNotifier(Notifier):
    """A push to an ntfy server - your own, or the public ntfy.sh.

    There is deliberately no default server: on ntfy.sh a topic is readable by
    anyone who knows its name, so pointing trip data there has to be a choice.
    """
    name = "ntfy"
    remote = True

    def __init__(self, cfg, opener=None, env=None):
        self.cfg = cfg or {}
        self.opener = opener or urllib.request.urlopen
        self.env = os.environ if env is None else env
        for need in ("server", "topic"):
            if not self.cfg.get(need):
                raise ValueError("alerts.ntfy needs '%s'" % need)
        if not str(self.cfg["server"]).startswith("https://") \
                and not self.cfg.get("allow_http"):
            raise ValueError("alerts.ntfy server must be https:// "
                             "(set allow_http for a LAN-only server)")

    def request(self, title, body, alerts):
        url = "%s/%s" % (str(self.cfg["server"]).rstrip("/"), self.cfg["topic"])
        headers = {"Title": title.encode("ascii", "replace").decode("ascii"),
                   "Tags": "airplane"}
        if alerts and alerts[0].url:
            headers["Click"] = alerts[0].url
        token = self.env.get(self.cfg.get("token_env") or "FAREWATCH_NTFY_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        return urllib.request.Request(url, data=body.encode("utf-8"),
                                      headers=headers, method="POST")

    def send(self, title, body, alerts, report_path=None):
        with self.opener(self.request(title, body, alerts), timeout=30) as resp:
            if getattr(resp, "status", 200) >= 300:
                raise RuntimeError("ntfy answered %s" % resp.status)


def notifiers(cfg, **overrides):
    """Build the backends the profile names. Unknown names are an error, so a
    typo does not silently mean no alerts."""
    out = []
    for name in cfg.get("backends") or []:
        if name == "toast":
            out.append(overrides.get("toast") or ToastNotifier())
        elif name == "email":
            out.append(overrides.get("email") or EmailNotifier(cfg.get("email")))
        elif name == "ntfy":
            out.append(overrides.get("ntfy") or NtfyNotifier(cfg.get("ntfy")))
        else:
            raise ValueError("unknown alert backend %r (toast, email, ntfy)" % name)
    return out


def run(ranked, profile, report_path=None, state_path=None, log=print,
        dry_run=False, backends=None):
    """Detect, deliver, then save state. Returns the alerts raised.

    State is saved even when delivery fails: a broken mail setup should not
    turn into the same alert every morning once it is fixed. Failures are
    logged and reported in the return so the caller can exit non-zero.
    """
    cfg = settings(profile)
    currency = (profile.get("home_currency") or "USD").upper()
    previous = load_state(state_path)
    current = snapshot(ranked)
    alerts = detect(previous, current, cfg)

    failures = []
    if previous is None:
        log("Alerts: no saved state yet; %s a baseline of %d routes"
            % ("would record" if dry_run else "recorded", len(current)))
    elif not alerts:
        log("Alerts: nothing changed enough to mention")
    else:
        title, body, shown = compose(alerts, cfg, currency)
        log("%s\n%s" % (title, body))
        chosen = []
        if not dry_run:
            try:
                chosen = backends if backends is not None else notifiers(cfg)
            except ValueError as exc:
                failures.append("config: %s" % exc)
                log("Alerts not sent: %s" % exc)
            for notifier in chosen:
                try:
                    notifier.send(title, body, shown, report_path)
                except Exception as exc:  # one bad backend never stops the rest
                    failures.append("%s: %s" % (notifier.name, exc))
                    log("Alert via %s failed: %s" % (notifier.name, exc))
    if not dry_run:
        save_state(current, state_path)
    return alerts, failures
