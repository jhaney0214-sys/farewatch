"""Send the deals to the group trip site, with their price history.

The report itself cannot be shared: it opens with the author's home airports and
carries the budget and the wishlist. So this builds its own list from an allowlist
of deal facts. Reasons are filtered too, because scoring writes the profile into
them ("over your $6,000 budget", "on your list"), and the list is ordered by value
alone, since the score is bent toward the author's wishlist and months.

The site shows this list on the author's own trip only (the author's decision,
2026-11-01, after reading the sources' terms). It carries short facts and credits the
source, and never their summaries.

Off unless the profile names a `share` block, which is gitignored with the rest
of the profile: {"url": "<site>/api/deals", "key": "<DEALS_KEY>"}. A failed push
is logged and changes nothing: the site keeps the last list.
"""

import json
import re
import urllib.error
import urllib.request
from datetime import date

from . import places, positioning, store

# Only value notes travel: they compare a fare with other fares and say nothing
# about the person ranking them.
# Fare-model estimates ("est. 57% below typical") stay home: the model is known to be
# rough, and a stranger would read it as a fact.
_VALUE_NOTE = re.compile(r"^(cheaper a night|pricier a night|about typical)")
_TAIL_PRICE = re.compile(r"\s+for\s+(?:From\s+)?\$[\d,]+(?:\s+for\s+2)?$")

TRAVEL_WORDS = {"drive": "to drive from %s and park",
                "fly": "to fly from %s, with the night before",
                "included": "flights included"}
MAX_DEALS = 400
SHARED_KINDS = ("cruise", "package", "hotel", "flight")
# Listings a US group can use. Fly4Free writes for European departures, and its copy
# parses badly: on 2026-11-01 its feed put a news story on the list at $44, a Riga hotel
# among the flights, and emoji and euro prices in the titles. Reddit posts are people's
# own, not listings to republish.
SOURCES = {"travelzoo": "Travelzoo", "dealnews-cruises": "DealNews", "theflightdeal": "The Flight Deal"}
BASIS_WORDS = {"per_person": "per person", "per_night": "a night", "per_room_night": "a night",
               "total": "total"}

# A deal is shared only if it can send people to the company's own website (the author's
# rule, 2026-11-01): no web searches, and no deal sites standing in for one. A cruise goes
# to its line's search, since the lines' booking pages are closed to scripts and a link
# cannot reach the one sailing. Some of these sites turn scripts away, but open for people.
COMPANY_SITES = {
    "Carnival": "https://www.carnival.com/cruise-search",
    "Royal Caribbean": "https://www.royalcaribbean.com/cruises",
    "Norwegian": "https://www.ncl.com/vacations",
    "MSC": "https://www.msccruisesusa.com/",
    "Celebrity": "https://www.celebritycruises.com/cruises",
    "Princess": "https://www.princess.com/cruise-search/",
    "Holland America": "https://www.hollandamerica.com/en/us/find-a-cruise",
    "Virgin Voyages": "https://www.virginvoyages.com/book/voyage-planner/find-a-voyage",
    "Disney": "https://disneycruise.disney.go.com/",
    "Cunard": "https://www.cunard.com/en-us",
    "Costa": "https://www.costacruises.com/",
    "Margaritaville at Sea": "https://www.margaritavilleatsea.com/",
    "Viking": "https://www.vikingcruises.com/oceans/search-cruises/index.html",
    "Oceania": "https://www.oceaniacruises.com/",
    "Regent Seven Seas": "https://www.rssc.com/",
    "Seabourn": "https://www.seabourn.com/en/us/find-a-cruise",
    "Silversea": "https://www.silversea.com/destinations.html",
    "Azamara": "https://www.azamara.com/",
    "Windstar": "https://www.windstarcruises.com/",
    "Explora": "https://www.explorajourneys.com/",
    "Crystal": "https://www.crystalcruises.com/",
    "Ponant": "https://us.ponant.com/",
    "Hurtigruten": "https://www.hurtigruten.com/",
    "Lindblad": "https://www.expeditions.com/",
    "American Cruise Lines": "https://www.americancruiselines.com/",
    "Atlas Ocean Voyages": "https://www.atlasoceanvoyages.com/",
    "Celestyal": "https://celestyal.com/",
    "CroisiEurope": "https://www.croisieuroperivercruises.com/",
    "Avalon Waterways": "https://www.avaloncruises.com/",
    "AmaWaterways": "https://www.amawaterways.com/",
    "Uniworld": "https://www.uniworld.com/",
    "Delta": "https://www.delta.com/",
    "American": "https://www.aa.com/",
    "United": "https://www.united.com/",
    "Southwest": "https://www.southwest.com/",
    "Alaska": "https://www.alaskaair.com/",
    "JetBlue": "https://www.jetblue.com/",
    "Frontier": "https://www.flyfrontier.com/",
    "Breeze": "https://www.flybreeze.com/",
    "Allegiant": "https://www.allegiantair.com/",
    "Sun Country": "https://www.suncountry.com/",
    "Hawaiian": "https://www.hawaiianairlines.com/",
    "Air Canada": "https://www.aircanada.com/",
    "WestJet": "https://www.westjet.com/",
    "British Airways": "https://www.britishairways.com/",
    "Virgin Atlantic": "https://www.virginatlantic.com/",
    "Lufthansa": "https://www.lufthansa.com/",
    "Air France": "https://www.airfrance.us/",
    "KLM": "https://www.klm.com/",
    "Aer Lingus": "https://www.aerlingus.com/",
    "Icelandair": "https://www.icelandair.com/",
    "Turkish Airlines": "https://www.turkishairlines.com/",
    "Emirates": "https://www.emirates.com/",
    "Qatar Airways": "https://www.qatarairways.com/",
    "Korean Air": "https://www.koreanair.com/",
    "Cathay Pacific": "https://www.cathaypacific.com/",
    "Copa": "https://www.copaair.com/",
    "Hyatt": "https://www.hyatt.com/",
    "Hilton": "https://www.hilton.com/",
    "Marriott": "https://www.marriott.com/",
    "IHG": "https://www.ihg.com/",
    "RIU": "https://www.riu.com/",
    "Iberostar": "https://www.iberostar.com/",
    "Sandals": "https://www.sandals.com/",
    "Club Med": "https://www.clubmed.us/",
    "Palace Resorts": "https://www.palaceresorts.com/",
    "Hard Rock Hotels": "https://hotel.hardrock.com/",
}
# How The Flight Deal writes an airline, where it differs from the name above.
AIRLINE_WORDS = {"KLM Royal Dutch": "KLM", "Copa Air": "Copa", "Copa Airlines": "Copa", "Air France KLM": "Air France"}
# Brands named in a stay's copy. Names that are also ordinary words ("Beaches", "Palace")
# only count in the form no one would write by accident.
_BRANDS = [("Hyatt", r"\bHyatt\b"), ("Hilton", r"\bHilton\b"), ("Marriott", r"\bMarriott\b"),
           ("IHG", r"\bKimpton\b|\bInterContinental\b"), ("RIU", r"\bRIU\b|\bRiu\s+[A-Z]"),
           ("Iberostar", r"\bIberostar\b"), ("Sandals", r"\bSandals\s+[A-Z]|\bSandals\s+Resorts?\b"),
           ("Club Med", r"\bClub Med\b"), ("Palace Resorts", r"\bPalace Resorts\b"),
           ("Hard Rock Hotels", r"\bHard Rock\b")]
_BRAND_RE = [(n, re.compile(p)) for n, p in _BRANDS]


def company(deal):
    """Who sells this, as far as the copy says, or "" when it does not."""
    trip = deal.trip or {}
    if deal.kind == "cruise":
        return trip.get("cruise_line") or ""
    if deal.kind == "flight":
        head = (deal.title or "").split(":")[0].strip()
        return AIRLINE_WORDS.get(head, head) if ":" in (deal.title or "") else ""
    text = "%s %s" % (deal.title or "", deal.summary or "")
    return next((name for name, pattern in _BRAND_RE if pattern.search(text)), "")


def tidy(title):
    """Drop the feed's price from a headline; the site shows its own."""
    title = _TAIL_PRICE.sub("", store.LEAD_PRICE.sub("", title or ""))
    return (title[:1].upper() + title[1:])[:140]


def home_name(profile):
    """The city the trips to port are figured from, as the site should say it."""
    return (places.city(positioning.base_key(profile) or "") or {}).get("name", "home")


def _logged_price(deal):
    unit = (deal.trip or {}).get("unit_usd") or 0
    return unit / 2 if deal.kind == "cruise" and deal.basis == "total" else unit


def _common(deal, history):
    trip = deal.trip or {}
    title = tidy(deal.title)
    line = company(deal)
    ship = trip.get("ship") or ""
    key = store.deal_key(deal.url, deal.title)
    return {
        "key": key,
        "kind": deal.kind,
        "title": title,
        "url": deal.url,
        "go_url": COMPANY_SITES[line],
        "line": line,
        "ship": ship,
        "nights": deal.nights or 0,
        "source": SOURCES.get(deal.source, deal.source),
        # A deal new since the last logged pull starts its history at today's price.
        "history": history.get(key) or [[date.today().isoformat(), round(_logged_price(deal))]],
        "note": next((r for r in deal.reasons or [] if _VALUE_NOTE.match(r)), ""),
    }


def row(deal, home="home", history=None):
    """One deal as a group may see it, or None if it cannot be shown."""
    trip = deal.trip or {}
    if deal.kind not in SHARED_KINDS or not trip.get("unit_usd") or not (deal.url or "").startswith("https://"):
        return None
    if deal.source not in SOURCES:
        return None
    if company(deal) not in COMPANY_SITES:
        return None
    out = _common(deal, history or {})
    if deal.kind == "cruise":
        people = max(1, trip.get("travelers") or 1)
        port = trip.get("cruise_port") or {}
        name = port.get("port_name") or ""
        words = TRAVEL_WORDS.get(port.get("how"), "")
        out.update({
            "dates": trip.get("departs") or "",
            "region": trip.get("region_label") or "",
            "port": name + ("" if not name or port.get("stated") else " (port assumed)"),
            "from_pp": round(deal.price / 2 if deal.basis == "total" else deal.price),
            "balcony_pp": round((trip.get("deal_usd", 0) + trip.get("cabin_uplift_usd", 0)) / people),
            "extras_pp": round((trip.get("ground_usd") or 0) / people),
            "travel_pp": round((port.get("party_usd") or 0) / people),
            "travel": words % home if "%s" in words else words,
            "price_word": "per person, est.",
        })
    else:
        # What the ad quotes, as it quotes it. Costing a stay or a fare would need
        # to know where the group lives, and strangers' groups do not say.
        out.update({
            "dates": "",
            "region": places.label(deal.destination) or "",
            "port": places.label(deal.origin) if deal.kind == "flight" and deal.origin else "",
            "from_pp": round(trip["unit_usd"]),
            "balcony_pp": round(trip["unit_usd"]),
            "extras_pp": 0,
            "travel_pp": 0,
            "travel": "",
            "price_word": BASIS_WORDS.get(deal.basis, ""),
        })
    return out


def _drop_share(history):
    if len(history) < 2 or not history[0][1]:
        return 0.0
    return max(0.0, (history[0][1] - history[-1][1]) / history[0][1])


def rows(ranked, home="home", limit=MAX_DEALS, history=None):
    """Biggest price drops first, then value; never the author's wishlist-bent score."""
    out = []
    seen = set()
    for deal in sorted(ranked, key=lambda d: -float((d.parts or {}).get("value", 0.5))):
        item = row(deal, home, history)
        if item and item["key"] not in seen:
            seen.add(item["key"])
            out.append(item)
    out.sort(key=lambda i: _drop_share(i["history"]), reverse=True)
    return out[:limit]


def push(ranked, profile, log=print, opener=urllib.request.urlopen, history=None):
    """POST the list to the site. Returns True when it landed; never raises."""
    cfg = (profile or {}).get("share") or {}
    if not cfg.get("url") or not cfg.get("key"):
        return False
    if history is None:
        conn = store.connect()
        history = store.price_history(conn)
        conn.close()
    deals = rows(ranked, home_name(profile), history=history)
    request = urllib.request.Request(
        cfg["url"], data=json.dumps({"deals": deals}).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "X-Deals-Key": cfg["key"],
                 "User-Agent": "Farewatch"})
    try:
        with opener(request, timeout=30) as response:
            response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # The URL holds a group's secret, so only the failure's kind is logged.
        log("Share: the site did not take the list (%s)" % type(exc).__name__)
        return False
    log("Share: %d deals sent to the site" % len(deals))
    return True
