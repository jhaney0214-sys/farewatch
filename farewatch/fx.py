"""Exchange rates, and how much of a tailwind they are.

Two free, keyless sources:

  * open.er-api.com   - latest rates for ~160 currencies. Breadth.
  * api.frankfurter.dev - ECB reference rates for ~30 currencies, with history.
                          History is what lets us say a currency is cheap *now*.

The interesting number here is not the rate, it is the deviation from the
trailing year. A destination whose currency has slid 15% against yours is 15%
off on food, hotels and taxis before any deal is applied, and no deal feed
anywhere tells you that.
"""

import json
import os
import time
import urllib.request
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", "cache", "fx.json")

LATEST_URL = "https://open.er-api.com/v6/latest/USD"
SERIES_URL = "https://api.frankfurter.dev/v1/{start}..{end}?base=USD&symbols={symbols}"

# The currencies the ECB publishes, which is what limits the history lookup.
HISTORY_SYMBOLS = [
    "AUD", "BGN", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP",
    "HKD", "HUF", "IDR", "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR",
    "NOK", "NZD", "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "ZAR",
]

MAX_AGE = 12 * 3600
TIMEOUT = 25

# Enough of a move to be worth a traveller changing plans over.
TAILWIND_NOTABLE = 0.04


class Rates:
    """USD-based rates plus a trailing-year average, with graceful degradation."""

    def __init__(self, latest=None, avg_year=None, as_of="", stale=False):
        self.latest = latest or {"USD": 1.0}
        self.avg_year = avg_year or {}
        self.as_of = as_of
        self.stale = stale

    # -- conversion ---------------------------------------------------------

    def to_usd(self, amount, currency):
        if amount is None:
            return None
        cur = (currency or "USD").upper()
        if cur == "USD":
            return float(amount)
        rate = self.latest.get(cur)
        if not rate:
            return None
        return float(amount) / rate

    def convert(self, amount, frm, to):
        usd = self.to_usd(amount, frm)
        if usd is None:
            return None
        to = (to or "USD").upper()
        if to == "USD":
            return usd
        rate = self.latest.get(to)
        return usd * rate if rate else None

    # -- the part that matters ---------------------------------------------

    def tailwind(self, home_currency, dest_currency):
        """How much further your money goes there than it did on average last year.

        +0.12 means your home currency buys 12% more of theirs than the trailing
        year average, so their prices are effectively 12% off for you. Returns
        None when either currency has no history, which is common and fine.
        """
        home = (home_currency or "USD").upper()
        dest = (dest_currency or "USD").upper()
        if home == dest:
            return 0.0
        now_h, now_d = self.latest.get(home), self.latest.get(dest)
        avg_h, avg_d = self.avg_year.get(home), self.avg_year.get(dest)
        if not all((now_h, now_d, avg_h, avg_d)):
            return None
        # Units of dest currency per unit of home currency, now vs the average.
        now_cross = now_d / now_h
        avg_cross = avg_d / avg_h
        if avg_cross <= 0:
            return None
        return now_cross / avg_cross - 1.0

    def describe_tailwind(self, home_currency, dest_currency):
        tw = self.tailwind(home_currency, dest_currency)
        if tw is None or abs(tw) < TAILWIND_NOTABLE:
            return None
        direction = "further" if tw > 0 else "less far"
        return "%s buys %.0f%% %s than its 1-year average vs %s" % (
            home_currency.upper(), abs(tw) * 100, direction, dest_currency.upper())


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "farewatch/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_latest():
    data = _get_json(LATEST_URL)
    if data.get("result") != "success":
        raise RuntimeError("er-api returned %r" % data.get("result"))
    rates = {k.upper(): float(v) for k, v in data["rates"].items() if v}
    rates["USD"] = 1.0
    return rates, data.get("time_last_update_utc", "")


def _fetch_year_average():
    end = date.today()
    start = end - timedelta(days=365)
    url = SERIES_URL.format(start=start.isoformat(), end=end.isoformat(),
                            symbols=",".join(HISTORY_SYMBOLS))
    data = _get_json(url)
    totals, counts = {}, {}
    for _day, day_rates in (data.get("rates") or {}).items():
        for sym, rate in day_rates.items():
            if not rate:
                continue
            totals[sym] = totals.get(sym, 0.0) + float(rate)
            counts[sym] = counts.get(sym, 0) + 1
    avg = {s: totals[s] / counts[s] for s in totals if counts[s] > 5}
    avg["USD"] = 1.0
    return avg


def load(max_age=MAX_AGE, offline=False, log=None):
    """Rates from cache when fresh, otherwise refreshed. Never raises."""
    cached = None
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as fh:
                cached = json.load(fh)
        except (OSError, ValueError):
            cached = None

    fresh = cached and (time.time() - cached.get("fetched_at", 0)) < max_age
    if offline or fresh:
        if cached:
            return Rates(cached.get("latest"), cached.get("avg_year"),
                         cached.get("as_of", ""), stale=not fresh)
        if offline:
            if log:
                log("  ! no cached FX and offline - prices stay in local currency")
            return Rates()

    latest, as_of, avg_year = None, "", None
    try:
        latest, as_of = _fetch_latest()
    except Exception as exc:
        if log:
            log("  ! FX latest failed (%s)" % exc)
    try:
        avg_year = _fetch_year_average()
    except Exception as exc:
        if log:
            log("  ! FX history failed (%s) - tailwind unavailable" % exc)

    if latest is None:
        if cached:
            return Rates(cached.get("latest"), cached.get("avg_year"),
                         cached.get("as_of", ""), stale=True)
        return Rates()

    if avg_year is None and cached:
        avg_year = cached.get("avg_year")

    payload = {"fetched_at": time.time(), "as_of": as_of,
               "latest": latest, "avg_year": avg_year or {}}
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    if log:
        log("  + FX %d rates, %d with 1-year history" % (len(latest), len(avg_year or {})))
    return Rates(latest, avg_year, as_of)
