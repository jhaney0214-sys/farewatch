"""Build data/route_fares.json: what passengers paid on every big US city pair.

    python tools/build_routes.py

The deal card's value note for a flight used to be "est. 37% below typical",
against the fare curve, which is fitted by eye and labelled an estimate because
it has been measured wrong. For a US domestic route there is a measured
alternative: DOT's Consumer Airfare Report, Table 6, the average each-way fare
paid in every contiguous-state city-pair market with 10+ passengers a day. This
writes the latest four quarters of it, matched to Farewatch's cities, so the
card can say what a deal is against what people actually paid.

It is public data and names nobody, so unlike positioning_fares.json it is
tracked; rebuild it when DOT publishes a quarter (about two quarters behind).
Same source and the same matching rules as tools/build_positioning.py.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from farewatch import places  # noqa: E402
from farewatch.dotfares import PATH as OUT, route_key  # noqa: E402
import build_positioning as bp  # noqa: E402

def fetch():
    # More years than four quarters need, newest first, so the page cap can
    # only ever cut the oldest rows.
    where = "year >= '%d'" % (date.today().year - 2)
    url = bp.ENDPOINT + "?" + urllib.parse.urlencode({
        "$select": "year, quarter, city1, city2, nsmiles, passengers, fare, fare_low",
        "$where": where, "$order": "year DESC, quarter DESC", "$limit": 50000})
    req = urllib.request.Request(url, headers={"User-Agent": "farewatch"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def city_key(label):
    key = places.resolve(label.split(",")[0].split("/")[0].split(" (")[0])
    return key if key and (places.city(key) or {}).get("country") == "US" else None


def build(rows):
    """Pure: DOT Table 6 rows -> the route_fares table."""
    periods = sorted({(r["year"], r["quarter"]) for r in rows}, reverse=True)[:bp.QUARTERS]
    totals = {}
    for r in rows:
        if (r["year"], r["quarter"]) not in periods:
            continue
        t = totals.setdefault((r["city1"], r["city2"]), {
            "pax": 0.0, "low": 0.0, "avg": 0.0, "miles": int(float(r["nsmiles"]))})
        pax = float(r["passengers"])
        t["pax"] += pax
        t["low"] += pax * float(r["fare_low"])
        t["avg"] += pax * float(r["fare"])

    routes, best = {}, {}
    for (c1, c2), t in totals.items():
        a, b = city_key(c1), city_key(c2)
        if not a or not b or a == b:
            continue
        km = places.distance_km(a, b)
        dot_km = t["miles"] * bp.KM_PER_MILE
        if not km or not dot_km:
            continue
        error = abs(km - dot_km) / dot_km
        if error > bp.DISTANCE_TOLERANCE:
            continue
        key = route_key(a, b)
        # Sarasota resolves to Tampa; Tampa's own market is the one to keep.
        if key in best and best[key] <= error:
            continue
        best[key] = error
        routes[key] = {
            "markets": [c1, c2],
            "roundtrip_low_usd": round(2 * t["low"] / t["pax"], 2),
            "roundtrip_avg_usd": round(2 * t["avg"] / t["pax"], 2),
            "passengers_per_day": round(t["pax"] / len(periods), 1),
        }
    return {
        "_": ("Built by tools/build_routes.py from DOT's Consumer Airfare Report, "
              "Table 6. Round trip = 2x the average each-way fare, passenger-"
              "weighted; low = on each market's lowest-fare carrier."),
        "source": bp.ENDPOINT,
        "built_on": date.today().isoformat(),
        "quarters": ["%sQ%s" % p for p in sorted(periods)],
        "routes": dict(sorted(routes.items())),
    }


def main():
    table = build(fetch())
    if not table["routes"]:
        raise SystemExit("no routes matched")
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=0)
        fh.write("\n")
    print("%d routes over %s-%s -> %s" % (len(table["routes"]), table["quarters"][0],
                                         table["quarters"][-1], os.path.relpath(OUT, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
