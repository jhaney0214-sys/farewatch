"""Turning a feed headline into a structured deal.

Deal blogs write prose, not data. This module is the messy middle: it decides
what kind of deal a headline describes, pulls the price and what that price
covers, and works out the route. It is deliberately conservative - a deal it
cannot read is dropped rather than guessed at, because a wrong route produces a
confidently wrong trip cost, which is worse than a missing row.
"""

import re

from . import places
from .models import Deal, fingerprint

# --------------------------------------------------------------------------
# price
# --------------------------------------------------------------------------

SYMBOLS = {
    "$": "USD", "US$": "USD", "C$": "CAD", "CA$": "CAD", "A$": "AUD",
    "NZ$": "NZD", "S$": "SGD", "HK$": "HKD", "R$": "BRL",
    "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR",
    "₩": "KRW", "₽": "RUB", "₪": "ILS", "₺": "TRY",
    "฿": "THB", "₱": "PHP", "₫": "VND", "R": "ZAR",
}

CODES = ("USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "SEK", "NOK", "DKK",
         "PLN", "CZK", "HUF", "JPY", "CNY", "HKD", "SGD", "INR", "THB", "MXN",
         "BRL", "ZAR", "AED", "ILS", "TRY", "KRW", "PHP", "MYR", "IDR", "RON")

# Comma-grouped form first: a plain digit run would match "134" of "1349"
# and quietly turn a $1349 cruise into a $134 one.
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"

# Symbol before the number:  $417   €62   US$1,349
_PRICE_PRE = re.compile(
    r"(?<![\w])(US\$|CA\$|C\$|A\$|NZ\$|S\$|HK\$|R\$|[$€£¥₹₩₪₺฿₱₫])"
    r"\s?(" + _NUM + r")")
# Number before the symbol:  1720€   163 £
_PRICE_POST = re.compile(r"(" + _NUM + r")\s?([€£¥])(?![\w])")
# Explicit code:  1349 USD   EUR 250
_PRICE_CODE = re.compile(r"(?:(" + _NUM + r")\s?(" + "|".join(CODES) + r")"
                         r"|(" + "|".join(CODES) + r")\s?(" + _NUM + r"))(?![\w])")

# Things that look like prices but are not.
_NOT_PRICE = re.compile(r"\d+\s?%|\d+[-\s]?star|\b[45]\*")


def _to_float(raw):
    return float(raw.replace(",", "").replace(" ", "").replace(" ", ""))


# A price introduced by one of these is not what the trip costs. "Norway cruises
# incl. $1000 flight credit" is a $1799 cruise, and taking the minimum price in
# the headline would have called it a $1000 one.
_NOT_THE_PRICE = re.compile(
    r"(?:incl|including|reg|was|worth|value|valued|save|saving|savings|credit|"
    r"rebate|voucher|up\s+to|orig|originally|retail|normally)\b[^\w]{0,4}$", re.I)

# ...and the same trap the other way round: "hotel w/$70+ in extras" is a perk,
# not the rate. Checked against the text immediately after the price.
_PRICE_IS_A_PERK = re.compile(
    r"^\+?\s*(?:in\s+|of\s+)?(?:extras?|perks?|credits?|vouchers?|savings?|"
    r"value|onboard|resort\s+credit|food|drinks?|dining|spa)\b", re.I)


def extract_price(text):
    """Lowest credible price in the text, as (amount, currency).

    Deal headlines often quote two fares ("$117 Basic / $197 Regular"). The lower
    one is the headline claim and the one worth ranking on; the upper is an
    upsell. Prices that the copy frames as a saving, a credit or a former price
    are excluded first. Returns (None, None) when nothing parses.
    """
    if not text:
        return None, None
    found = []

    def add(amount, currency, start, end):
        # Look just behind, and just ahead, for the words that change a number
        # from "what you pay" into something else entirely.
        if _NOT_THE_PRICE.search(text[max(0, start - 14):start]):
            return
        if _PRICE_IS_A_PERK.search(text[end:end + 22]):
            return
        found.append((amount, currency))

    for m in _PRICE_PRE.finditer(text):
        cur = SYMBOLS.get(m.group(1).upper()) or SYMBOLS.get(m.group(1))
        if cur:
            add(_to_float(m.group(2)), cur, m.start(), m.end())
    for m in _PRICE_POST.finditer(text):
        cur = SYMBOLS.get(m.group(2))
        if cur:
            add(_to_float(m.group(1)), cur, m.start(), m.end())
    for m in _PRICE_CODE.finditer(text):
        if m.group(1):
            add(_to_float(m.group(1)), m.group(2).upper(), m.start(), m.end())
        else:
            add(_to_float(m.group(4)), m.group(3).upper(), m.start(), m.end())

    # A bare number under 5 is a star rating or a night count far more often than
    # it is a fare, and a six-figure number is a ship tonnage or a year.
    found = [(amt, cur) for amt, cur in found if 5 <= amt < 100000]
    if not found:
        return None, None
    return min(found, key=lambda p: p[0])


# --------------------------------------------------------------------------
# what the price covers
# --------------------------------------------------------------------------

_PER_NIGHT = re.compile(r"per\s+night|/\s?night|a\s+night|per\s+n[ei]ght|nightly", re.I)
_PER_ROOM = re.compile(r"/\s?double|per\s+double|/\s?room|per\s+room|double\s+room", re.I)
# Both boundaries matter on the short forms: "each" without a leading \b matches
# inside "beach", which read a beachfront getaway as a per-person price, and
# "pp" without one matches inside "app".
_PER_PERSON = re.compile(r"\bp\.?\s?p\.?\b|\bper\s+person\b|\bpp\b|\beach\b", re.I)


# What an unlabelled price means, by deal type. These are not guesses: hotel
# deals quote a nightly rate, and package, cruise and flight deals quote one
# person, essentially without exception across these feeds. Reading them all as
# trip totals made a $159 New York hotel look 76% below market.
DEFAULT_BASIS = {
    "flight": "per_person",
    "hotel": "per_room_night",
    "package": "per_person",
    "cruise": "per_person",
}


def extract_basis(text, kind="other", nights=None):
    if _PER_ROOM.search(text):
        return "per_room_night"
    if _PER_NIGHT.search(text):
        return "per_night"
    if _PER_PERSON.search(text):
        return "per_person"
    # A headline that names the length of the stay is quoting the whole stay:
    # "Weeklong Phuket getaway for 2, $779" is not $779 a night. Without a
    # duration the same price is a nightly rate, which is why this is the one
    # place the night count changes what the number means.
    if kind == "hotel" and nights:
        return "total"
    return DEFAULT_BASIS.get(kind, "total")


_NIGHTS = re.compile(r"(\d{1,2})[\s-]*(?:night|nite)s?", re.I)
_DAYS = re.compile(r"(\d{1,2})[\s-]*days?", re.I)

# Travel copy says "weeklong" as often as it says "7-night", and a duration read
# as absent makes an unlabelled price look like a nightly rate.
_WORD_NIGHTS = [
    (re.compile(r"\blong\s+weekend\b", re.I), 3),
    (re.compile(r"\bweekend\b", re.I), 2),
    (re.compile(r"\bweek[\s-]?long\b|\bfor\s+a\s+week\b|\bone[\s-]week\b", re.I), 7),
    (re.compile(r"\bfortnight\b|\btwo[\s-]week\b", re.I), 14),
]


def extract_nights(text):
    m = _NIGHTS.search(text)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 60 else None
    m = _DAYS.search(text)
    if m:
        n = int(m.group(1))
        # A "7-day trip" is six nights, but travel copy uses them interchangeably
        # and the difference is inside our cost model noise.
        return n - 1 if 2 <= n <= 60 else None
    for pattern, nights in _WORD_NIGHTS:
        if pattern.search(text):
            return nights
    return None


# --------------------------------------------------------------------------
# kind
# --------------------------------------------------------------------------

_URL_KIND = [
    # "local" is theatre tickets, spa days and restaurant vouchers. Travelzoo
    # publishes a lot of them in the same feed and none of them are travel.
    ("local", re.compile(r"/entertainment|/local-deal|/restaurant|/spa\b", re.I)),
    ("cruise", re.compile(r"/cruise", re.I)),
    ("package", re.compile(r"/vacation|/package|/holiday|/tour", re.I)),
    ("hotel", re.compile(r"/hotel|/resort|/stay|/lodging", re.I)),
    ("flight", re.compile(r"/flight|/air|/fare", re.I)),
]

_KW_CRUISE = re.compile(r"\bcruis\w*|\bsailing\b|\bship\b|\bvoyage\b|\bitinerar\w+\b", re.I)
_KW_PACKAGE = re.compile(
    r"w/\s?flight|with\s+flights|flights?\s*\+|\+\s*flights?|"
    r"\bpackage\b|\ball[\s-]inclusive\b|\bholiday\s+in\b|"
    r"flights?\s+from\s+\w+\s*\+|\bstay\b.{0,30}\bflight|\bflight.{0,30}\bstay\b", re.I)
_KW_HOTEL = re.compile(r"\bhotels?\b|\bresorts?\b|\bstays?\b|\bvillas?\b|\briad\b|"
                       r"\bguesthouse\b|\bhostel\b|\baparthotel\b|\bnights?\b|"
                       # Travelzoo writes "Tulum 5-star for 2" and "beach
                       # getaway", neither of which says hotel, resort or stay.
                       r"\bgetaway\b|\bretreat\b|\binn\b|\blodge\b|\bsuite\b|"
                       r"\d[\s-]?star\b|\boceanfront\b|\bbeachfront\b", re.I)
_KW_FLIGHT = re.compile(r"\bflight\b|\bflights\b|\bfare\b|\bairfare\b|\bround\s?trip\b|"
                        r"\breturn\b|\bnon-?stop\b|\bone[\s-]way\b|\berror\s+fare\b", re.I)

# Deal blogs also publish plain news. These never describe a bookable deal.
_NEWS = re.compile(
    r"\bexplains?\b|\bconfirms?\b|\breveal(s|ed)?\b|\bannounce(s|d)?\b|"
    r"\bsneak\s+peek\b|\bwhat\s+we\s+know\b|\brumors?\b|\bcalls?\s+for\b|"
    r"\breview\b|\bguide\b|\bhow\s+to\b|\bwhy\s+\w+\b|\bnames?\s+new\b|"
    r"\bcaptain\b|\bcrew\b|\bpassenger\s+(dies|dead|rescued|arrested)\b|"
    r"\bdry\s?dock\b|\bchristen\w*\b|\bkeel\b|\bfloat\s?out\b", re.I)


def _classify_text(text):
    # Package first: it looks like both a flight and a hotel, and it is neither.
    if _KW_PACKAGE.search(text):
        return "package"
    if _KW_CRUISE.search(text):
        return "cruise"
    if _KW_FLIGHT.search(text):
        return "flight"
    if _KW_HOTEL.search(text):
        return "hotel"
    return None


def url_kind(url):
    for kind, pattern in _URL_KIND:
        if pattern.search(url or ""):
            return kind
    return None


def classify(title, summary, url, source_kind="mixed", trust_url=True):
    """The kind of deal, from the strongest available signal.

    Whether the URL can be trusted is a per-source fact, set in sources.json.
    Travelzoo files each deal under a real category, so its URL is the best
    signal there is. Fly4Free puts every post under /flight-deals/ including its
    hotel and package deals, so trusting its URL mislabels a third of the feed.

    Where the URL is not trusted the title decides, and the summary is consulted
    only if the title says nothing either way - deal-blog summaries mention
    flights almost universally, so scoring a hotel headline against its summary
    reliably calls it a flight.
    """
    from_url = url_kind(url)

    # "local" is the one URL signal that cannot be taken at face value.
    # Travelzoo files real hotel getaways under /local-deals/ - the phrase means
    # "sold through a local merchant", not "not travel" - so a Tulum resort and
    # a Nutcracker ticket share a path. Let the title arbitrate: if it reads as
    # lodging or a trip, it is one; if it says nothing travel-ish, it is a show.
    if from_url == "local":
        return _classify_text(title) or "local"

    if trust_url and from_url:
        return from_url

    kind = _classify_text(title)
    if kind:
        return kind
    kind = _classify_text(summary or "")
    if kind:
        return kind
    if from_url:
        return from_url
    if source_kind in ("flight", "hotel", "cruise", "package"):
        return source_kind
    return "other"


# Roundups and category pages carry a price but sell nothing in particular.
# "$999 & up -- Thailand travel offers and trip inspiration" is a landing page,
# and taking its price as a Bangkok hotel rate poisoned that destination.
_NOT_AN_OFFER = re.compile(
    r"trip\s+inspiration|travel\s+offers|more\s+deals|deals?\s+(?:&|and)\s+more|"
    r"(?:&|and)\s+more\b|inspiration\b|browse\b|explore\s+(?:our|more)\b", re.I)


def looks_like_an_offer(title):
    return not _NOT_AN_OFFER.search(title or "")


def looks_like_news(title, summary=""):
    return bool(_NEWS.search("%s %s" % (title, summary)))


# --------------------------------------------------------------------------
# cabin
# --------------------------------------------------------------------------

def extract_cabin(text):
    low = text.lower()
    if "first class" in low or re.search(r"\bfirst\b(?!\s+time)", low) and "class" in low:
        if "first class" in low:
            return "first"
    if "business class" in low or "business-class" in low or re.search(r"\bbiz\b", low):
        return "business"
    if "premium economy" in low or "premium-economy" in low:
        return "premium"
    return "economy"


_ROUNDTRIP = re.compile(r"round\s?trip|\breturn\b|r/t\b|\bboth\s+ways\b|and\s+vice\s+versa", re.I)


# --------------------------------------------------------------------------
# route
# --------------------------------------------------------------------------

_PRICE_STRIP = re.compile(
    r"(US\$|CA\$|C\$|A\$|NZ\$|S\$|HK\$|R\$|[$€£¥₹₩₪₺฿₱₫])"
    r"\s?" + _NUM + r"|(" + _NUM + r")\s?[€£¥]")

_FROM_TO = re.compile(r"\bfrom\b(.{1,70}?)\bto\b(.{1,70})", re.I | re.S)
_TO_ONLY = re.compile(r"^(.{1,90}?)\bto\b(.{1,90})", re.I | re.S)
_FROM_ONLY = re.compile(r"\bfrom\b(.{1,70})", re.I | re.S)


def _first_place(text, exclude=None):
    for key, _pos in places.find_all(text or ""):
        if key != exclude:
            return key
    return None


def extract_route_detailed(title, kind="flight"):
    """(origin, destination, origin_is_departure).

    The third value is the one that matters downstream. An origin found after
    the word "from" is a place you must actually depart from, and reaching it
    costs money. An origin found any other way may just be the first stop on an
    itinerary - "Lisbon to Porto: 6-night trip w/air" starts wherever you live,
    not in Lisbon - and charging for a flight to it would be nonsense.
    """
    text = _PRICE_STRIP.sub(" ", title)

    # 1. "from A to B" - the clearest signal there is, and unambiguously a
    #    departure city.
    m = _FROM_TO.search(text)
    if m:
        origin = _first_place(m.group(1))
        dest = _first_place(m.group(2), exclude=origin)
        if dest:
            return origin, dest, True

    # 2. "A to B" with no "from". For a flight that is a route; for a package it
    #    is as likely to be the itinerary, so it is not treated as a departure.
    m = _TO_ONLY.search(text)
    if m:
        origin = _first_place(m.group(1))
        dest = _first_place(m.group(2), exclude=origin)
        if origin and dest:
            return origin, dest, kind == "flight"

    # 3. "Airline: A - B", which is how The Flight Deal writes every headline.
    if kind == "flight":
        segment = text.rsplit(": ", 1)[-1] if ": " in text else text
        segment = places.normalise(segment)
        parts = [p.strip() for p in re.split(r"\s-\s|\s-$", segment) if p.strip()]
        if len(parts) == 2:
            origin = _first_place(parts[0])
            dest = _first_place(parts[1], exclude=origin)
            if origin and dest:
                return origin, dest, True

    # 4. "... from A" with the destination stated elsewhere. Also a departure.
    m = _FROM_ONLY.search(text)
    if m:
        origin = _first_place(m.group(1))
        if origin:
            dest = _first_place(text, exclude=origin)
            if dest:
                return origin, dest, True

    # 5. Fall back to mention order, which is right for hotels and cruises and
    #    usually right for flights. Never a reliable departure signal.
    found = [k for k, _ in places.find_all(text)]
    if not found:
        return None, None, False
    if kind == "flight" and len(found) >= 2:
        return found[0], found[1], True
    return None, found[0], False


def extract_route(title, kind="flight"):
    """(origin_key, destination_key), either of which may be None."""
    origin, dest, _departure = extract_route_detailed(title, kind)
    return origin, dest


# --------------------------------------------------------------------------
# deadline
# --------------------------------------------------------------------------

_MONTHS = ("january|february|march|april|may|june|july|august|september|"
           "october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
_DEADLINE = re.compile(
    r"(?:book\s+by|ends?|expires?|through|until|valid\s+(?:through|until))\s+"
    r"((?:" + _MONTHS + r")\.?\s+\d{1,2}|\d{1,2}\s+(?:" + _MONTHS + r"))", re.I)


def extract_deadline(text):
    m = _DEADLINE.search(text or "")
    return m.group(1).strip() if m else None


# --------------------------------------------------------------------------
# entry -> Deal
# --------------------------------------------------------------------------

# Why an entry did not become a deal. Kept as named constants because the drop
# rate runs around 40% and a single opaque counter cannot tell you whether that
# is junk being correctly rejected or a parser quietly rotting as a feed drifts.
REJECT_NO_TITLE = "no title"
REJECT_NOT_TRAVEL = "not a travel deal"
REJECT_NO_PRICE = "no price in the headline"
REJECT_NEWS = "reads as news, not an offer"
REJECT_NO_DESTINATION = "destination not recognised"
REJECT_NOT_SPECIFIC = "not a specific offer"


def build_detailed(entry):
    """(Deal, None) on success, (None, reason) on rejection."""
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    url = entry.get("link", "")
    if not title:
        return None, REJECT_NO_TITLE

    kind = classify(title, summary, url, entry.get("source_kind", "mixed"),
                    trust_url=entry.get("trust_url_kind", True))
    if kind in ("local", "other"):
        return None, REJECT_NOT_TRAVEL

    # Price from the title first. Summaries mention unrelated prices constantly
    # ("rooms from $99" inside an article about something else), so they are only
    # consulted when the title has nothing.
    price, currency = extract_price(title)
    basis_text = title
    if price is None:
        price, currency = extract_price(summary)
        basis_text = "%s %s" % (title, summary)
    if price is None:
        return None, REJECT_NO_PRICE

    if not looks_like_an_offer(title):
        return None, REJECT_NOT_SPECIFIC

    if looks_like_news(title, summary) and kind != "flight":
        return None, REJECT_NEWS

    nights = extract_nights(basis_text)
    origin, destination, departure = extract_route_detailed(title, kind)
    if destination is None:
        origin, destination, departure = extract_route_detailed(
            "%s %s" % (title, summary), kind)
    if destination is None:
        return None, REJECT_NO_DESTINATION

    deal = Deal(
        source=entry.get("source", "?"),
        title=title,
        url=url,
        published=entry.get("published", ""),
        summary=summary,
        kind=kind,
        price=price,
        currency=currency,
        basis=extract_basis(basis_text, kind, nights),
        origin=origin,
        origin_is_departure=departure,
        destination=destination,
        nights=nights,
        roundtrip=bool(_ROUNDTRIP.search(title)),
        cabin=extract_cabin(title),
    )
    deal.trip["deadline"] = extract_deadline(basis_text)
    deal.fingerprint = fingerprint(deal)
    return deal, None


def build(entry):
    """Turn a feed entry into a Deal, or None if it is not a readable deal."""
    return build_detailed(entry)[0]


def build_all(entries):
    """(deals, rejects). Each reject records why, so the loss is inspectable."""
    deals, rejects = [], []
    for entry in entries:
        deal, reason = build_detailed(entry)
        if deal is None:
            rejects.append({
                "reason": reason,
                "title": entry.get("title", ""),
                "source": entry.get("source", "?"),
                "url": entry.get("link", ""),
            })
            continue
        deals.append(deal)
    return deals, rejects
