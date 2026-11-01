"""Watching particular cruises up to a sale, and saying whether the sale is real.

Built 2026-11-01 for the author's Black Friday cruise. A sale price means
something only against what the same sailing cost before the sale, and the
deal feeds never show the same sailing twice. So this keeps two kinds of watch:

  * **Sailings**, priced by hand. The cruise lines' own pages are the only
    place a specific sailing's price lives, and they are closed to scripts:
    Royal Caribbean and Celebrity disallow /booking/ in robots.txt, NCL its
    search results, and Carnival's sister brand Cunard forbids automated
    scraping in its terms. So the author looks the price up (half a minute)
    and records it with `fw.py watch price`; this keeps the dated history,
    prices the all-in the same way the ranking does, and on the sale days
    says whether the sale beat the November low.
  * **Feed watches**: a region, a length, ports and an all-in ceiling, checked
    against every cruise each refresh. Matches lead the report, and a new
    match raises an alert with the rest.

State is data/watch.json (gitignored: it names the trips you are planning).
"""

import json
import os
from datetime import date, datetime

from . import cruise
from .models import Deal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "watch.json")

# Thanksgiving 2026 is Thursday 26 November; the cruise lines' Black Friday
# sales run from about then through Cyber Monday (30 November) and often a day
# past it. `fw.py watch sale` changes the window.
DEFAULT_SALE = {"name": "Black Friday", "start": "2026-11-26", "end": "2026-12-01"}

# How much under the pre-sale low a sale price must be to count as a sale.
# Within this the two are the same price on a different day.
REAL_SALE_PCT = 3.0
# Pre-sale prices this far back count; older ones belong to another season.
LOOKBACK_DAYS = 45


def load(path=None):
    try:
        with open(path or PATH, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    state.setdefault("sale", dict(DEFAULT_SALE))
    state.setdefault("sailings", [])
    state.setdefault("feeds", [])
    state.setdefault("alerted", {})
    state.setdefault("reminded", [])
    return state


def save(state, path=None):
    path = path or PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, path)


def _next_id(items):
    return max([int(i["id"]) for i in items] or [0]) + 1


def _day(text):
    return date.fromisoformat(text) if text else None


# --------------------------------------------------------------- sailings

def add_sailing(state, name, price, basis="per_person", nights=None, port=None,
                cabin="balcony", url="", when=None):
    """A sailing to watch, with its first price. Returns the new entry."""
    entry = {"id": _next_id(state["sailings"]), "name": name, "url": url,
             "nights": nights, "port": port, "cabin": cabin, "prices": []}
    state["sailings"].append(entry)
    record_price(state, entry["id"], price, basis, when)
    return entry


def find(state, sailing_id):
    for entry in state["sailings"]:
        if int(entry["id"]) == int(sailing_id):
            return entry
    return None


def record_price(state, sailing_id, price, basis="per_person", when=None):
    """Record a price seen for a sailing. One price a day: a second on the
    same day replaces the first, since it is a correction, not a new sighting."""
    entry = find(state, sailing_id)
    if entry is None:
        raise KeyError("no sailing %s" % sailing_id)
    when = (when or date.today()).isoformat()
    per_person = float(price) / 2.0 if basis == "total" else float(price)
    entry["prices"] = [p for p in entry["prices"] if p["date"] != when]
    entry["prices"].append({"date": when, "per_person": per_person})
    entry["prices"].sort(key=lambda p: p["date"])
    return entry


def drop_sailing(state, sailing_id):
    before = len(state["sailings"])
    state["sailings"] = [s for s in state["sailings"] if int(s["id"]) != int(sailing_id)]
    return len(state["sailings"]) < before


def verdict(entry, sale, today=None):
    """What the price history says, as {"state", "text", ...}.

    states: "empty", "before" (the sale has not started), "waiting" (the sale
    is on and no price has been recorded in it), "real", "same", "worse".
    """
    today = today or date.today()
    start, end = _day(sale["start"]), _day(sale["end"])
    name = sale.get("name", "the sale")
    prices = [(date.fromisoformat(p["date"]), p["per_person"]) for p in entry["prices"]]
    if not prices:
        return {"state": "empty", "text": "no price recorded"}
    before = [(d, p) for d, p in prices
              if d < start and (start - d).days <= LOOKBACK_DAYS]
    during = [(d, p) for d, p in prices if start <= d <= end]
    low_day, low = min(before, key=lambda x: x[1]) if before else (None, None)

    if not during:
        if today < start:
            last_day, last = prices[-1]
            text = "$%s a person on %s" % (format(int(round(last)), ","), last_day.strftime("%b %d"))
            if low is not None and low < last:
                text += "; low so far $%s on %s" % (format(int(round(low)), ","),
                                                    low_day.strftime("%b %d"))
            text += ". %s starts %s: record its price then." % (name, start.strftime("%b %d"))
            return {"state": "before", "text": text, "low": low}
        return {"state": "waiting",
                "text": "%s is on (until %s) and no sale price is recorded yet."
                        % (name, end.strftime("%b %d")), "low": low}

    sale_day, sale_low = min(during, key=lambda x: x[1])
    money = lambda v: "$%s" % format(int(round(v)), ",")  # noqa: E731
    if low is None:
        return {"state": "same",
                "text": "%s price %s, but nothing recorded in the %d days before it to "
                        "compare with." % (name, money(sale_low), LOOKBACK_DAYS),
                "sale": sale_low}
    pct = 100.0 * (low - sale_low) / low
    if pct >= REAL_SALE_PCT:
        return {"state": "real", "pct": pct, "sale": sale_low, "low": low,
                "text": "A real sale: %s a person, %.0f%% under its pre-sale low of %s (%s)."
                        % (money(sale_low), pct, money(low), low_day.strftime("%b %d"))}
    if pct > -REAL_SALE_PCT:
        return {"state": "same", "pct": pct, "sale": sale_low, "low": low,
                "text": "No better than before: %s a person against %s on %s."
                        % (money(sale_low), money(low), low_day.strftime("%b %d"))}
    return {"state": "worse", "pct": pct, "sale": sale_low, "low": low,
            "text": "Pricier in the sale: %s a person against %s on %s."
                    % (money(sale_low), money(low), low_day.strftime("%b %d"))}


def as_deal(entry):
    """The sailing as a Deal at its latest price, so it can be costed like one."""
    last = entry["prices"][-1]["per_person"] if entry["prices"] else None
    words = [entry["name"], entry.get("cabin") or "balcony", "cruise"]
    summary = ("from %s" % entry["port"]) if entry.get("port") else ""
    return Deal(source="watch", title=" ".join(words), url=entry.get("url") or "",
                kind="cruise", price=last, currency="USD", basis="per_person",
                nights=entry.get("nights"), summary=summary)


def all_in(entry, profile, rates, fare_curve):
    """The sailing's all-in at its latest price, by the ranking's own rules."""
    from . import costs
    deal = as_deal(entry)
    if deal.price is None:
        return None
    trip = costs.breakdown(deal, profile, rates)
    deal.trip.update(trip)
    port = cruise.getting_there(deal, profile, fare_curve, trip.get("nights") or 7)
    total = trip.get("total_usd") or 0.0
    if port:
        total += port.get("party_usd") or 0.0
    return {"total_usd": total, "port": port, "trip": trip}


# --------------------------------------------------------------- feed watches

def add_feed(state, name, regions=None, min_nights=None, max_nights=None,
             max_all_in=None, ports=None):
    entry = {"id": _next_id(state["feeds"]), "name": name,
             "regions": [r.lower() for r in (regions or [])],
             "min_nights": min_nights, "max_nights": max_nights,
             "max_all_in": max_all_in, "ports": [p.lower() for p in (ports or [])]}
    state["feeds"].append(entry)
    return entry


def drop_feed(state, feed_id):
    before = len(state["feeds"])
    state["feeds"] = [f for f in state["feeds"] if int(f["id"]) != int(feed_id)]
    return len(state["feeds"]) < before


def _port_group(port_key):
    for group, members in cruise.PORT_GROUPS.items():
        if port_key in members:
            return group
    return None


def matches(feed, deal):
    """True when a ranked cruise fits a feed watch."""
    if deal.kind != "cruise":
        return False
    trip = deal.trip or {}
    if feed.get("regions") and trip.get("region") not in feed["regions"]:
        return False
    if feed.get("min_nights") and (not deal.nights or deal.nights < feed["min_nights"]):
        return False
    if feed.get("max_nights") and (not deal.nights or deal.nights > feed["max_nights"]):
        return False
    if feed.get("max_all_in") and (trip.get("total_usd") or 0) > feed["max_all_in"]:
        return False
    if feed.get("ports"):
        port = (trip.get("cruise_port") or {}).get("port")
        if port not in feed["ports"] and _port_group(port) not in feed["ports"]:
            return False
    return True


def feed_matches(state, ranked):
    """{feed id: [deals]} for every feed watch, best score first."""
    return {f["id"]: [d for d in ranked if matches(f, d)] for f in state["feeds"]}


def new_matches(state, found):
    """Matches not alerted before, as [(feed, deal)], and marks them alerted."""
    out = []
    for feed in state["feeds"]:
        seen = set(state["alerted"].get(str(feed["id"]), []))
        for deal in found.get(feed["id"], []):
            if deal.fingerprint and deal.fingerprint not in seen:
                out.append((feed, deal))
                seen.add(deal.fingerprint)
        state["alerted"][str(feed["id"])] = sorted(seen)
    return out


def needs_reminder(state, today=None):
    """Sailings with no price today, on a sale day not yet reminded about."""
    today = today or date.today()
    sale = state["sale"]
    if not (_day(sale["start"]) <= today <= _day(sale["end"])):
        return []
    if today.isoformat() in state["reminded"]:
        return []
    return [s for s in state["sailings"]
            if not any(p["date"] == today.isoformat() for p in s["prices"])]


def describe_feed(feed):
    bits = []
    if feed.get("regions"):
        bits.append("/".join(feed["regions"]))
    if feed.get("min_nights") or feed.get("max_nights"):
        bits.append("%s-%s nights" % (feed.get("min_nights") or "?", feed.get("max_nights") or "?"))
    if feed.get("ports"):
        bits.append("from " + "/".join(feed["ports"]))
    if feed.get("max_all_in"):
        bits.append("all-in under $%s" % format(int(feed["max_all_in"]), ","))
    return ", ".join(bits) or "every cruise"


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M")
