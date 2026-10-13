"""The hand-written country costs against the World Bank's price levels.

    python tools/check_costs.py            # fetch, then report
    python tools/check_costs.py --offline  # from the cached copy

Five of the 150 countries in `data/destinations.json` carry measured prices.
The rest were written by hand. This does not measure them. It asks a narrower
question that can be answered for nearly all of them at once: does a country's
row sit where its general price level says it should, relative to the others?

The price level is the World Bank's PPP conversion factor over the official
exchange rate (indicators PA.NUS.PPP and PA.NUS.FCRF, latest year both exist),
with the United States at 1. Food, getting around and a hotel night are each
fitted against it on a log scale across every country, and a row more than a
factor of two off its line is listed.

Read the list as "look here first", not as "this is wrong". The measured
countries miss the same lines by up to a factor of two themselves (Bangkok's
taxis and transit), because tourist prices are not the general price level. A
row that is far out is either a real exception, a typing slip, or a figure
that went stale when a currency fell.
"""

import argparse
import json
import math
import os
import statistics
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "destinations.json")
CACHE = os.path.join(ROOT, "data", "cache", "worldbank-price-level.json")
API = ("https://api.worldbank.org/v2/country/all/indicator/%s"
       "?format=json&date=2019:2030&per_page=5000")
BASE = "US"
#: What each part of a trip is read from in a country's row.
PARTS = (("food", ("meal_cheap", "meal_mid_two", "beer")),
         ("getting around", ("transit", "taxi_km")),
         ("hotel", ("hotel_mid",)))
#: A row this far off its line is listed.
FACTOR = 2.0


def price_levels(ppp, rate):
    """{country: (level, year)} from two {country: {year: value}} tables."""
    out = {}
    for code, by_year in ppp.items():
        years = sorted(set(by_year) & set(rate.get(code, {})), key=int)
        if years and rate[code][years[-1]]:
            out[code] = (by_year[years[-1]] / rate[code][years[-1]], int(years[-1]))
    return out


def relative(row, base, fields):
    """A country's prices over the base country's, as one geometric mean.

    A price of zero is left out: beer is 0 where it is not sold."""
    ratios = [row[f] / base[f] for f in fields if row.get(f, 0) > 0 and base.get(f, 0) > 0]
    if not ratios:
        return None
    return math.exp(statistics.mean(math.log(r) for r in ratios))


def fit(points):
    """Least squares of log y on log x. Returns (slope, intercept, r squared)."""
    xs = [math.log(x) for x, _ in points]
    ys = [math.log(y) for _, y in points]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    spread = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / spread
    intercept = my - slope * mx
    left = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    total = sum((y - my) ** 2 for y in ys)
    return slope, intercept, (1 - left / total) if total else 0.0


def check(countries, levels):
    """Per part: the fit, and each country's row over what the line expects."""
    base = countries[BASE]
    out = {}
    for name, fields in PARTS:
        rows = [(code, levels[code][0], relative(row, base, fields))
                for code, row in sorted(countries.items())
                if code != BASE and code in levels]
        rows = [r for r in rows if r[2]]
        slope, intercept, r2 = fit([(level, rel) for _, level, rel in rows])
        off = {code: rel / math.exp(intercept + slope * math.log(level))
               for code, level, rel in rows}
        out[name] = {"slope": slope, "at_base": math.exp(intercept), "r2": r2, "off": off}
    return out


def flagged(result, factor=FACTOR):
    """{country: {part: ratio}} for rows more than `factor` off any line."""
    out = {}
    for name, part in result.items():
        for code, ratio in part["off"].items():
            if ratio > factor or ratio < 1 / factor:
                out.setdefault(code, {})[name] = ratio
    return out


def report(countries, levels):
    result = check(countries, levels)
    missing = sorted(c for c in countries if c not in levels)
    lines = ["%d countries, %d with a World Bank price level (none for %s)"
             % (len(countries), len(countries) - len(missing), ", ".join(missing) or "nobody"),
             ""]
    for name, part in result.items():
        lines.append("%-15s slope %.2f, r2 %.2f; a country at the US price level is "
                     "written at %.2f of the US row"
                     % (name, part["slope"], part["r2"], part["at_base"]))
    measured = sorted(c for c, row in countries.items() if row.get("verified") and c != BASE)
    lines += ["", "the measured countries against the same lines (row / expected):"]
    for code in measured:
        lines.append("  %s  %s" % (code, "  ".join(
            "%s %.2f" % (name, part["off"][code])
            for name, part in result.items() if code in part["off"])))
    flags = flagged(result)
    lines += ["", "more than a factor of %g off a line, %d of %d:"
              % (FACTOR, len(flags), len(countries) - len(missing))]
    for code in sorted(flags, key=lambda c: -max(abs(math.log(v)) for v in flags[c].values())):
        lines.append("  %s %-22s %s%s" % (
            code, countries[code]["name"][:22],
            "  ".join("%s %.2f" % (n, v) for n, v in flags[code].items()),
            "   (measured)" if countries[code].get("verified") else ""))
    return "\n".join(lines)


def _table(indicator):
    request = urllib.request.Request(API % indicator,
                                     headers={"User-Agent": "farewatch check_costs"})
    with urllib.request.urlopen(request, timeout=90) as response:
        body = json.load(response)
    if len(body) < 2 or body[1] is None:
        raise SystemExit("World Bank returned no data for %s: %s" % (indicator, body[0]))
    out = {}
    for row in body[1]:
        if row["value"] is not None:
            out.setdefault(row["country"]["id"], {})[row["date"]] = row["value"]
    return out


def fetch(offline=False):
    if not offline:
        tables = {"ppp": _table("PA.NUS.PPP"), "rate": _table("PA.NUS.FCRF")}
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(tables, handle)
        os.replace(CACHE + ".tmp", CACHE)
    if not os.path.isfile(CACHE):
        raise SystemExit("no cached World Bank tables at %s" % CACHE)
    with open(CACHE, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    tables = fetch(args.offline)
    with open(DATA, encoding="utf-8") as handle:
        countries = json.load(handle)["countries"]
    print(report(countries, price_levels(tables["ppp"], tables["rate"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
