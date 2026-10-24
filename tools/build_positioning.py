"""Build data/positioning_fares.json: what people actually pay to leave your base.

    python tools/build_positioning.py              # base from config/profile.json
    python tools/build_positioning.py --market "Portland, ME"

The positioning leg used to be priced on the fare curve, and the curve is a
line fitted to deal-blog postings. Deal fares are the cheapest fares there are,
and a hop out of a regional airport is not a deal fare. Measured against DOT's
Consumer Airfare Report for one regional base over four quarters, the curve
priced its nonstop hops at a median of a third of what the cheapest carrier in
each market actually collected (range 1.1x to 7.4x), so every positioned deal
had been ranked on a total several hundred dollars too low.

The source is DOT's Table 6 (every contiguous-state city-pair market with at
least 10 passengers a day), served free and keyless from data.transportation.gov.
Its fares are one-way averages with round trips split in half, so a round trip
here is twice the figure. Of its two fares this keeps `fare_low`, the average
paid on the market's lowest-fare carrier: closer to what someone shopping pays
than the all-carrier average, which carries business and last-minute tickets.
It is still an average paid, not a quote, and it lags by about two quarters.

The output names your home airport, so it is gitignored, like your profile.
"""

import argparse
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from farewatch import faremodel, places, positioning  # noqa: E402
import fw  # noqa: E402

ENDPOINT = "https://data.transportation.gov/resource/yj5y-b2ir.json"
QUARTERS = 4
# DOT's nonstop miles against our great-circle distance. Wider than rounding
# needs, narrow enough to tell Portland, Oregon from Portland, Maine.
DISTANCE_TOLERANCE = 0.15
KM_PER_MILE = 1.609344


def fetch(market):
    # The table runs back to 1996, so an unfiltered market overflows any page;
    # three years newest-first always holds the latest four quarters.
    quoted = market.replace("'", "''")
    where = "(city1 = '%s' OR city2 = '%s') AND year >= '%d'" % (
        quoted, quoted, date.today().year - 3)
    url = ENDPOINT + "?" + urllib.parse.urlencode(
        {"$where": where, "$order": "year DESC, quarter DESC", "$limit": 5000})
    req = urllib.request.Request(url, headers={"User-Agent": "farewatch"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def find_market(name):
    """DOT's market label for a city name, e.g. 'Des Moines, IA'."""
    where = "city1 like '%s,%%' OR city2 like '%s,%%'" % (name, name)
    url = ENDPOINT + "?" + urllib.parse.urlencode(
        {"$select": "city1, city2", "$where": where, "$limit": 200})
    req = urllib.request.Request(url, headers={"User-Agent": "farewatch"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        rows = json.load(resp)
    labels = {c for r in rows for c in (r["city1"], r["city2"])
              if c.startswith(name + ",")}
    return sorted(labels)


def match_city(label, base, miles):
    """The city key a DOT market label means, checked against its distance."""
    key = places.resolve(label.split(",")[0].split("/")[0].split(" (")[0])
    if not key or (places.city(key) or {}).get("country") != "US":
        return None, None
    km = places.distance_km(base, key)
    if not km:
        return None, None
    error = abs(km - miles * KM_PER_MILE) / (miles * KM_PER_MILE)
    return (key, error) if error <= DISTANCE_TOLERANCE else (None, None)


def build(rows, market, base):
    """Pure: DOT rows for one market -> the positioning_fares table."""
    periods = sorted({(r["year"], r["quarter"]) for r in rows}, reverse=True)[:QUARTERS]
    totals = {}
    for r in rows:
        if (r["year"], r["quarter"]) not in periods:
            continue
        other = r["city2"] if r["city1"] == market else r["city1"]
        t = totals.setdefault(other, {"pax": 0.0, "low": 0.0, "avg": 0.0,
                                      "miles": int(float(r["nsmiles"])),
                                      "carriers": set()})
        pax = float(r["passengers"])
        t["pax"] += pax
        t["low"] += pax * float(r["fare_low"])
        t["avg"] += pax * float(r["fare"])
        t["carriers"].add(r.get("carrier_low") or "")

    fares, unmatched, best = {}, [], {}
    for label, t in totals.items():
        key, error = match_city(label, base, t["miles"])
        if not key:
            unmatched.append(label)
            continue
        # Two markets can resolve to one city (Sarasota is an alias of Tampa);
        # the one whose distance agrees best is the city itself.
        if key in best and best[key] <= error:
            unmatched.append(label)
            continue
        best[key] = error
        fares[key] = {
            "market": label,
            "roundtrip_usd": round(2 * t["low"] / t["pax"], 2),
            "roundtrip_all_carriers_usd": round(2 * t["avg"] / t["pax"], 2),
            "low_fare_carriers": sorted(c for c in t["carriers"] if c),
            "passengers_per_day": round(t["pax"] / len(periods), 1),
        }

    ratios = [f["roundtrip_usd"] / faremodel.expected_flight_usd(base, k)
              for k, f in fares.items()]
    return {
        "_": ("Built by tools/build_positioning.py from DOT's Consumer Airfare "
              "Report, Table 6. Round trip = 2x the one-way fare paid on each "
              "market's lowest-fare carrier, passenger-weighted."),
        "source": ENDPOINT,
        "built_on": date.today().isoformat(),
        "base": base,
        "market": market,
        "quarters": ["%sQ%s" % p for p in sorted(periods)],
        "curve_multiplier": round(statistics.median(ratios), 3) if ratios else None,
        "markets": len(fares),
        "unmatched": sorted(unmatched),
        "fares": dict(sorted(fares.items())),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", default=None)
    ap.add_argument("--market", help="DOT's label for your city, e.g. 'Des Moines, IA'")
    ap.add_argument("--out", default=positioning.FARES_PATH)
    args = ap.parse_args()

    profile = fw.load_profile(args.profile)
    base = positioning.base_key(profile)
    if not base:
        raise SystemExit("no positioning.base in the profile; set your home airport first")

    market = args.market
    if not market:
        labels = find_market(places.city(base)["name"])
        if len(labels) != 1:
            raise SystemExit("DOT has %s for %s; pass one with --market"
                             % (labels or "no market", places.city(base)["name"]))
        market = labels[0]

    table = build(fetch(market), market, base)
    if not table["fares"]:
        raise SystemExit("no markets matched for %s" % market)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1)
        fh.write("\n")
    print("%s: %d markets over %s, the curve x%.2f at the median; %d unmatched -> %s"
          % (market, table["markets"], table["quarters"][0] + "-" + table["quarters"][-1],
             table["curve_multiplier"], len(table["unmatched"]),
             os.path.relpath(args.out, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
