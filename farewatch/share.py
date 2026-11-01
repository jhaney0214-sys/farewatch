"""Send the ranked cruises to the friends' board (Shore Party), and nothing else.

The report itself cannot be shared: it opens with the author's home airports and
carries the budget, the wishlist and every non-cruise deal. So this builds its
own list from an allowlist of deal facts. Reasons are filtered too, because
scoring writes the profile into them ("over your $6,000 budget", "on your list").

Off unless the profile names a `share` block, which is gitignored with the rest
of the profile: {"url": "<board>/api/deals", "key": "<DEALS_KEY>"}. A failed push
is logged and changes nothing: friends keep the last list.
"""

import json
import re
import urllib.error
import urllib.request

from . import places, positioning

# Only value notes travel: they compare a fare with other fares and say nothing
# about the person ranking them.
_VALUE_NOTE = re.compile(r"^(cheaper a night|pricier a night|about typical|est\. \d+% (below|above))")
_LEAD_PRICE = re.compile(r"^\$[\d,]+(?:\s*&\s*up)?\s*--\s*")
_TAIL_PRICE = re.compile(r"\s+for\s+(?:From\s+)?\$[\d,]+(?:\s+for\s+2)?$")

TRAVEL_WORDS = {"drive": "to drive from %s and park",
                "fly": "to fly from %s, with the night before",
                "included": "flights included"}
MAX_DEALS = 80
# Where to check the real price once the line is known. Travelzoo's deal links land
# on its general cruises page, so these do the work its links cannot.
LINE_SITES = {
    "Carnival": "https://www.carnival.com/",
    "Royal Caribbean": "https://www.royalcaribbean.com/",
    "Norwegian": "https://www.ncl.com/",
    "MSC": "https://www.msccruisesusa.com/",
    "Celebrity": "https://www.celebritycruises.com/",
    "Princess": "https://www.princess.com/",
    "Holland America": "https://www.hollandamerica.com/",
    "Virgin Voyages": "https://www.virginvoyages.com/",
    "Disney": "https://disneycruise.disney.go.com/",
}


def tidy(title):
    """Drop the feed's price from a headline; the board shows its own."""
    title = _TAIL_PRICE.sub("", _LEAD_PRICE.sub("", title or ""))
    return (title[:1].upper() + title[1:])[:140]


def home_name(profile):
    """The city the trips to port are figured from, as the board should say it."""
    return (places.city(positioning.base_key(profile) or "") or {}).get("name", "home")


def row(deal, home="home"):
    """One cruise as friends may see it, per person, or None if it cannot be shown."""
    trip = deal.trip or {}
    if deal.kind != "cruise" or not trip.get("known") or not (deal.url or "").startswith("https://"):
        return None
    people = max(1, trip.get("travelers") or 1)
    port = trip.get("cruise_port") or {}
    name = port.get("port_name") or ""
    fare = (trip.get("deal_usd", 0) + trip.get("cabin_uplift_usd", 0)) / people
    extras = (trip.get("ground_usd") or 0) / people
    travel = (port.get("party_usd") or 0) / people
    note = next((r for r in deal.reasons or [] if _VALUE_NOTE.match(r)), "")
    words = TRAVEL_WORDS.get(port.get("how"), "")
    return {
        "title": tidy(deal.title),
        "url": deal.url,
        "line": trip.get("cruise_line") or "",
        "ship": trip.get("ship") or "",
        "dates": trip.get("departs") or "",
        "nights": deal.nights or 0,
        "region": trip.get("region_label") or "",
        "port": name + ("" if not name or port.get("stated") else " (port assumed)"),
        "from_pp": round(deal.price / 2 if deal.basis == "total" else deal.price),
        "balcony_pp": round(fare),
        "extras_pp": round(extras),
        "travel_pp": round(travel),
        "travel": words % home if "%s" in words else words,
        "note": note,
        "source": deal.source,
        "line_url": LINE_SITES.get(trip.get("cruise_line") or "", ""),
    }


def rows(ranked, home="home", limit=MAX_DEALS):
    out = []
    for deal in ranked:
        item = row(deal, home)
        if item:
            out.append(item)
        if len(out) == limit:
            break
    return out


def push(ranked, profile, log=print, opener=urllib.request.urlopen):
    """POST the list to the board. Returns True when it landed; never raises."""
    cfg = (profile or {}).get("share") or {}
    if not cfg.get("url") or not cfg.get("key"):
        return False
    body = json.dumps({"deals": rows(ranked, home_name(profile))}).encode("utf-8")
    request = urllib.request.Request(
        cfg["url"], data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Deals-Key": cfg["key"],
                 "User-Agent": "Farewatch"})
    try:
        with opener(request, timeout=30) as response:
            response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # The URL holds the board's secret, so only the failure's kind is logged.
        log("Share: the board did not take the list (%s)" % type(exc).__name__)
        return False
    log("Share: %d cruises sent to the board" % len(json.loads(body)["deals"]))
    return True
