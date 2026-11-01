"""What a cruise actually costs, and what it should cost.

Until 2026-11-01 a cruise was priced like a city break at its "destination",
and the destination was whatever place name the headline happened to contain:
every Caribbean sailing was Nassau, the Windward Islands were Amsterdam, the
Mexican Riviera was Mexico City. Its value was judged against $200 a night, a
balcony fare, when every "$599 & up" headline quotes an inside cabin; the 16
Caribbean sailings tracked by then ran a median of $100 a night. So ordinary
fares ranked second, third and fourth of 387 deals as "57-61% below typical",
in the month the author meant to book one.

This module gives a cruise the three things it needs instead:

  * a **region**, which sets what a day ashore costs and what a fare is
    compared against, read from the itinerary words a headline actually uses;
  * a **departure port**, priced from home - a drive to the Gulf, or a flight
    plus the hotel night nobody skips before an embarkation day;
  * the **costs every cruise carries** that a headline never includes: port
    taxes and fees, and the daily gratuity, unless the copy says they are in.

Everything here that is not measured is marked as an estimate where it is used.
"""

import re

from . import places

# --------------------------------------------------------------- regions
#
# Order matters: the first pattern that matches wins, so specific itineraries
# come before the words they contain ("Mexican Riviera" before "Mexico").
# shore: a person's day ashore, mid style, USD - excursions, a meal, transport.
# fare: the inside-cabin fare per person per night a headline in this region
#       is judged against when Farewatch has not tracked enough of its own.
#       Caribbean is measured (median of 16 Travelzoo sailings, 2026-08-29 to
#       11-01); the rest are estimates scaled from it and are labelled so.
# fees: port taxes and fees per person per night, est.
# ports: where sailings in this region usually leave from, cheapest first is
#        decided at pricing time. Used when the headline names no port.
REGIONS = [
    # First: "Portugal & Spain River Cruise" is a river ship, not the Med.
    ("river", r"\briver\b|danube|rhine|seine|douro|mekong|nile", "River",
     {"shore": 30, "fare": 400, "fees": 0, "ports": []}),
    ("panama_canal", r"panama\s+canal", "Panama Canal",
     {"shore": 45, "fare": 105, "fees": 25, "ports": ["florida", "los angeles"]}),
    ("mexican_riviera", r"mexican\s+riviera|sea\s+of\s+cortez|puerto\s+vallarta|cabo",
     "Mexican Riviera",
     {"shore": 40, "fare": 100, "fees": 22, "ports": ["los angeles", "san diego"]}),
    ("baja", r"\bbaja\b|ensenada|catalina", "Baja",
     {"shore": 35, "fare": 100, "fees": 22, "ports": ["los angeles", "san diego"]}),
    ("bahamas", r"bahamas|nassau|bimini|perfect\s+day|cococay", "Bahamas",
     {"shore": 40, "fare": 100, "fees": 28, "ports": ["florida"]}),
    # Same comparison as the rest of the Caribbean, different ports: the
    # southern islands are a week's sail from Florida, not from Mobile.
    ("caribbean", r"southern\s+caribbean|windward|leeward|antilles|aruba|"
                  r"cura[cç]ao|barbados|st\.?\s+lucia",
     "Caribbean",
     {"shore": 40, "fare": 100, "fees": 25, "ports": ["florida"]}),
    ("caribbean", r"caribbean|windward|leeward|antilles|cozumel|jamaica|"
                  r"st\.?\s+(?:thomas|maarten|kitts|lucia)|aruba|cura[cç]ao|"
                  r"barbados|grand\s+cayman|roatan|belize|costa\s+maya|"
                  r"san\s+juan|puerto\s+rico|virgin\s+islands",
     "Caribbean",
     {"shore": 40, "fare": 100, "fees": 25, "ports": ["gulf", "florida"]}),
    ("alaska", r"alaska|inside\s+passage|glacier\s+bay|juneau|ketchikan|skagway",
     "Alaska",
     {"shore": 75, "fare": 140, "fees": 35, "ports": ["seattle", "vancouver"]}),
    ("hawaii", r"hawai|honolulu|maui", "Hawaii",
     {"shore": 70, "fare": 130, "fees": 30, "ports": ["honolulu", "los angeles"]}),
    ("bermuda", r"bermuda", "Bermuda",
     {"shore": 60, "fare": 120, "fees": 30, "ports": ["new york", "baltimore"]}),
    ("canada_ne", r"new\s+england|canada|nova\s+scotia|quebec|maritimes",
     "Canada & New England",
     {"shore": 55, "fare": 120, "fees": 28, "ports": ["new york", "boston"]}),
    ("mediterranean", r"mediterranean|\bmed\b|greek|greece|italy|croatia|spain|"
                      r"france|riviera|adriatic|amalfi|sicily|morocco|portugal|"
                      r"venice|rome|barcelona|athens|naples|m[aá]laga|nice\b",
     "Mediterranean",
     {"shore": 65, "fare": 150, "fees": 25, "ports": ["rome", "barcelona"]}),
    ("northern_europe", r"norway|fjord|baltic|iceland|british\s+isles|scandinav|"
                        r"greenland|northern\s+europe|arctic",
     "Northern Europe",
     {"shore": 75, "fare": 160, "fees": 25, "ports": ["copenhagen", "amsterdam"]}),
    ("asia_pacific", r"japan|asia|vietnam|thailand|cambodia|tahiti|polynesia|"
                     r"australia|new\s+zealand|south\s+pacific|tuamotu",
     "Asia & Pacific",
     {"shore": 60, "fare": 170, "fees": 25, "ports": []}),
    ("transatlantic", r"transatlantic|repositioning", "Transatlantic",
     {"shore": 50, "fare": 80, "fees": 20, "ports": ["florida"]}),
]
_REGION_RE = [(key, re.compile(pattern, re.I), label, info)
              for key, pattern, label, info in REGIONS]
OTHER = {"shore": 50, "fare": 130, "fees": 25, "ports": []}

# Luxury and all-inclusive lines are a different market: judged against the
# mainstream median, a $3,459 Italy cruise looked 74% overpriced. A tier mark
# keeps them in their own comparison and switches off the add-ons they include.
_LUXURY = re.compile(r"luxury|5-star|five-star|all-inclusive|all\s+inclusive|"
                     r"yacht|expedition|small[\s-]ship|seabourn|silversea|regent|"
                     r"oceania|viking|windstar|ponant|explora", re.I)
LUXURY_FARE_MULT = 3.0

# Gratuities a person a day in a standard cabin, as reported for 2026 (Carnival,
# Princess, Holland America, MSC and Celebrity all raised theirs that year, and
# reports differ on MSC and Celebrity; the line's own page has the final word).
# Virgin Voyages includes them in the fare. GRATUITY_DAILY covers an unnamed line.
GRATUITY_DAILY = 18.0
GRATUITY_BY_LINE = {
    "Carnival": 17.0, "Royal Caribbean": 18.5, "Norwegian": 20.0, "Princess": 18.0,
    "Holland America": 18.0, "MSC": 17.0, "Celebrity": 19.5, "Virgin Voyages": 0.0,
}
# Drinks, wifi and specialty dining once gratuities are counted separately.
ONBOARD_DAILY = {"budget": 10.0, "mid": 45.0, "luxury": 110.0}
# With a drinks package in the fare, most of the onboard spend goes.
ONBOARD_WITH_DRINKS = {"budget": 5.0, "mid": 15.0, "luxury": 40.0}

# A headline "from" fare is the cheapest cabin, an inside one. What a balcony
# costs on the same sailing, as a multiple. Until 2026-11-01 this was a guessed
# 1.6 for everyone. BALCONY_BY_LINE is Cruise Fever's measure of every 2026 cruise
# of 7-14 days from a US port, over 2,000 sailings (published January 2025):
# averages, so one sailing can sit well either side. An unnamed line takes the
# measured median.
CABIN_MULT = {"inside": 1.0, "oceanview": 1.15, "balcony": 1.35, "suite": 3.0}
BALCONY_BY_LINE = {
    "Celebrity": 1.224, "Disney": 1.231, "MSC": 1.279, "Royal Caribbean": 1.309,
    "Princess": 1.344, "Virgin Voyages": 1.347, "Carnival": 1.349, "Norwegian": 1.383,
    "Holland America": 1.432,
}
_CABIN_WORDS = [
    ("suite", re.compile(r"\bsuites?\b|haven|yacht\s+club", re.I)),
    ("balcony", re.compile(r"balcon|verandah?", re.I)),
    ("oceanview", re.compile(r"ocean[\s-]?view|outside\s+cabin|window", re.I)),
    ("inside", re.compile(r"\binside\b|interior", re.I)),
]

_SUMMARY_CABIN = re.compile(r"(?:balcony|verandah?|ocean[\s-]?view)\s+(?:stateroom|cabin)", re.I)
_CABIN_CHOICE = re.compile(r"upgrade|\binside\b|interior|or\s+(?:a\s+)?balcony", re.I)

_FEES_IN = re.compile(r"(?:incl\.?|including|includes|with)\s+(?:all\s+)?"
                      r"(?:taxes|taxes\s+(?:&|and)\s+fees|port\s+fees)", re.I)
_TIPS_IN = re.compile(r"gratuities\s+(?:incl|included)|(?:incl\.?|including|"
                      r"includes|with|free|prepaid)\s+(?:\w+\s+){0,2}gratuities|"
                      r"\btips\b[^.]{0,25}\b(?:included|covered)\b", re.I)
_DRINKS_IN = re.compile(r"(?:incl\.?|including|includes|with|free|plus|&)\s+"
                        r"(?:\w+\s+){0,2}drinks|\bdrinks?\b[^.]{0,30}\b(?:included|covered)\b|"
                        r"open\s+bar|beverage\s+package", re.I)
_FLIGHTS_IN = re.compile(r"w/\s*(?:air|flights?)|with\s+(?:air|flights?)|"
                         r"(?:&|and)\s+(?:air|flights?)\b|flights?\s*(?:&|and)\s*"
                         r"(?:river\s+)?cruise|"
                         r"incl\.?\s+(?:air|flights?)|(?:air|flights?)\s+included|"
                         r"cruise\s*(?:&|and|\+)\s*(?:air|fly)|fly\s*(?:&|and)\s*cruise",
                         re.I)
# A cruise sold with land parts - a tour, rail, a hotel stay - is priced as a
# bundle, and its headline is not a cabin fare to scale.
_BUNDLE = re.compile(r"\btours?\b|\brail\b|\btrain|\bhotel\b|\bstay\b|safari", re.I)
_FLIGHT_CREDIT = re.compile(r"\$\s?(\d[\d,]*)\s+(?:air|flight)\s+credit", re.I)
_ONBOARD_CREDIT = re.compile(r"\$\s?(\d[\d,]*)\s+(?:onboard|on-board|ship\s*board)\s+"
                             r"(?:credit|spend)|\$\s?(\d[\d,]*)\s+obc\b", re.I)

# Perks a Black Friday cruise sale leads with. Read so the card can say what
# the offer is; only drinks, gratuities, onboard credit and flight credit move
# the total, because those are money the party would otherwise spend.
_PERKS = [
    ("drinks included", _DRINKS_IN),
    ("gratuities included", _TIPS_IN),
    ("kids sail free", re.compile(r"kids\s+(?:sail|cruise)\s+free", re.I)),
    ("second guest discounted",
     re.compile(r"(?:2nd|second)\s+guest|bogo|buy\s+one", re.I)),
    ("wifi included", re.compile(r"(?:free|incl\.?|with)\s+wi-?fi", re.I)),
    ("Black Friday", re.compile(r"black\s+friday|cyber\s+(?:monday|week)", re.I)),
]

# --------------------------------------------------------------- ports
#
# Where a sailing leaves from, and how to get there from home. Drive miles are
# one way, by road, from the author's home, measured on OSRM's road router
# (2026-11-01); a port with no drive figure is reached by air. `air` is the airport
# city key to fly into.
PORTS = {
    "mobile": {"name": "Mobile", "drive_miles": 356, "air": None},
    "new orleans": {"name": "New Orleans", "drive_miles": 441, "air": "new orleans"},
    "galveston": {"name": "Galveston", "drive_miles": 786, "air": "houston"},
    "tampa": {"name": "Tampa", "drive_miles": 635, "air": "tampa"},
    "port canaveral": {"name": "Port Canaveral", "drive_miles": 670, "air": "orlando"},
    "jacksonville": {"name": "Jacksonville", "drive_miles": 525, "air": "jacksonville"},
    "miami": {"name": "Miami", "drive_miles": 841, "air": "miami"},
    "fort lauderdale": {"name": "Fort Lauderdale", "drive_miles": 818,
                        "air": "fort lauderdale"},
    "los angeles": {"name": "Los Angeles", "drive_miles": None, "air": "los angeles"},
    "san diego": {"name": "San Diego", "drive_miles": None, "air": "san diego"},
    "seattle": {"name": "Seattle", "drive_miles": None, "air": "seattle"},
    "vancouver": {"name": "Vancouver", "drive_miles": None, "air": "vancouver"},
    "honolulu": {"name": "Honolulu", "drive_miles": None, "air": "honolulu"},
    "new york": {"name": "New York", "drive_miles": None, "air": "new york"},
    "boston": {"name": "Boston", "drive_miles": None, "air": "boston"},
    "baltimore": {"name": "Baltimore", "drive_miles": None, "air": "baltimore"},
    "rome": {"name": "Rome (Civitavecchia)", "drive_miles": None, "air": "rome"},
    "barcelona": {"name": "Barcelona", "drive_miles": None, "air": "barcelona"},
    "copenhagen": {"name": "Copenhagen", "drive_miles": None, "air": "copenhagen"},
    "amsterdam": {"name": "Amsterdam", "drive_miles": None, "air": "amsterdam"},
}
# Where each line actually sails from. Pricing a Holland America cruise as a drive
# to Mobile was the cheap answer and a wrong one: only Carnival sails from Mobile
# (year-round Carnival Valor from May 2027). From 2027 sailing listings and
# deployment news, 2026-11-01; a partial picture, so a port the copy names always wins.
LINE_PORTS = {
    "Carnival": ["mobile", "new orleans", "galveston", "tampa", "port canaveral",
                 "jacksonville", "miami", "los angeles", "san diego", "seattle",
                 "new york", "baltimore"],
    "Royal Caribbean": ["new orleans", "galveston", "tampa", "port canaveral", "miami",
                        "fort lauderdale", "los angeles", "seattle", "vancouver",
                        "new york", "baltimore", "boston"],
    "Norwegian": ["new orleans", "galveston", "port canaveral", "miami",
                  "los angeles", "seattle", "vancouver", "new york", "boston"],
    "MSC": ["galveston", "port canaveral", "miami", "new york", "baltimore"],
    "Celebrity": ["fort lauderdale", "miami", "los angeles", "seattle", "vancouver"],
    "Princess": ["galveston", "fort lauderdale", "los angeles", "san diego", "seattle",
                 "vancouver"],
    "Holland America": ["fort lauderdale", "san diego", "seattle", "vancouver", "boston"],
    "Virgin Voyages": ["miami", "san juan"],
    "Disney": ["port canaveral", "galveston", "fort lauderdale", "san diego", "vancouver"],
}
# Port groups a headline names instead of a port.
PORT_GROUPS = {
    "florida": ["tampa", "port canaveral", "jacksonville", "miami", "fort lauderdale"],
    "gulf": ["mobile", "new orleans", "galveston", "tampa"],
}
_PORT_WORDS = [
    ("florida", r"from\s+florida|florida\s+(?:round|departure)"),
    ("gulf", r"from\s+(?:the\s+)?gulf"),
    ("mobile", r"\bmobile\b"),
    ("new orleans", r"new\s+orleans"),
    ("galveston", r"galveston|from\s+texas|from\s+houston"),
    ("tampa", r"\btampa\b"),
    ("port canaveral", r"canaveral|orlando"),
    ("jacksonville", r"jacksonville"),
    ("miami", r"\bmiami\b"),
    ("fort lauderdale", r"lauderdale|port\s+everglades"),
    ("los angeles", r"los\s+angeles|long\s+beach|san\s+pedro"),
    ("san diego", r"san\s+diego"),
    ("seattle", r"seattle"),
    ("vancouver", r"vancouver"),
    ("new york", r"new\s+york|\bnyc\b|cape\s+liberty|bayonne"),
    ("baltimore", r"baltimore"),
    ("boston", r"\bboston\b"),
]
_PORT_RE = [(key, re.compile(pattern, re.I)) for key, pattern in _PORT_WORDS]

# Embarkation day: a hotel the night before for anyone who flies, and a taxi
# or shuttle each way between airport and terminal for the party.
# The deal-fitted curve prices the cheapest fares a blog posts; a regional
# traveller's real ticket across an ocean connects and costs more, est. twice.
INTERNATIONAL_MULT = 2.0
HOTEL_NIGHT_BEFORE = {"budget": 110.0, "mid": 180.0, "luxury": 320.0}
TRANSFER_PARTY = 70.0


_BOARD_AT_HEADLINE = {"river", "mediterranean", "northern_europe", "asia_pacific"}
# A country's name resolves to its capital, and no ship leaves from these.
_INLAND = {"madrid"}


def _text(deal):
    return "%s %s" % (deal.title or "", deal.summary or "")


def region(deal):
    """(key, label, info) for the sailing, from its title first, then summary."""
    for text in (deal.title or "", _text(deal)):
        for key, pattern, label, info in _REGION_RE:
            if pattern.search(text):
                return key, label, info
    return "other", "cruise", OTHER


def is_luxury(deal):
    return bool(_LUXURY.search(deal.title or ""))


def cabin(deal):
    """The cabin the headline price is for: inside unless the copy says otherwise.

    The title wins. A summary counts only when it names one cabin outright:
    DealNews' "$1,116 for 2" MSC deal says "oceanview balcony stateroom" there,
    and scaling that fare up again counted the balcony twice. Mentions of an
    upgrade, or of an inside fare beside it, describe a choice, not this price.
    """
    for name, pattern in _CABIN_WORDS:
        if pattern.search(deal.title or ""):
            return name
    summary = deal.summary or ""
    if _SUMMARY_CABIN.search(summary) and not _CABIN_CHOICE.search(summary):
        return "balcony" if re.search(r"balcon|verandah?", summary, re.I) else "oceanview"
    return "inside"


# Most headlines name an itinerary and no line, so the summary's ship or private
# island often says it instead. A ship or island belongs to exactly one line, so
# these are read as facts. A generic word never counts: "Costa Maya" is a port,
# "Costa Rica" a country and "Norway" not Norwegian, so a line's own name needs
# its full form or a ship's name after it.
_LINE_NAMES = [
    # (line, pattern, case-sensitive). Names that are also ordinary words need
    # their capital and a word that only a cruise line would put after them.
    ("Carnival", r"Carnival\s+(?:Cruise|[A-Z][a-z]+)", True),
    ("Royal Caribbean", r"royal\s+caribbean", False),
    ("Norwegian", r"Norwegian\s+(?:Cruise|[A-Z][a-z]+)|\bNCL\b", True),
    ("MSC", r"\bMSC\b", True),
    ("Celebrity", r"Celebrity\s+(?:Cruise|[A-Z][a-z]+)", True),
    ("Princess", r"Princess\s+Cruise|\b(?:Caribbean|Enchanted|Sky|Regal|Royal|Majestic|"
                 r"Discovery|Sun|Star|Grand|Emerald|Ruby|Island|Coral|Crown|Sapphire|"
                 r"Diamond)\s+Princess\b", True),
    ("Holland America", r"holland\s+america", False),
    ("Virgin Voyages", r"virgin\s+voyages", False),
    ("Disney", r"Disney\s+(?:Cruise|[A-Z][a-z]+)", True),
    ("Costa", r"costa\s+cruises", False),
    ("Cunard", r"cunard", False),
    ("Oceania", r"oceania\s+cruises|Oceania\s+[A-Z][a-z]+", True),
    ("Viking", r"Viking\s+(?:Cruises|River|Ocean|Expedition)", True),
    ("Regent Seven Seas", r"regent\s+seven", False),
    ("Seabourn", r"seabourn", False),
    ("Silversea", r"silversea|silver\s+(?:muse|moon|dawn|nova|ray|spirit)", False),
    ("Azamara", r"azamara", False),
    ("Windstar", r"windstar", False),
    ("Explora", r"Explora\s+(?:Journeys|[IV]+)", True),
    ("Ponant", r"ponant", False),
    ("Hurtigruten", r"hurtigruten", False),
    ("Havila", r"havila", False),
    ("Avalon Waterways", r"\bAvalon\b", True),
    ("Uniworld", r"uniworld", False),
    ("AmaWaterways", r"amawaterways", False),
    ("CroisiEurope", r"croisieurope", False),
    ("Atlas Ocean Voyages", r"atlas\s+ocean", False),
    ("Celestyal", r"celestyal", False),
    ("Margaritaville at Sea", r"margaritaville\s+at\s+sea", False),
    ("Crystal", r"Crystal\s+(?:Cruises|Symphony|Serenity)", True),
    ("Lindblad", r"lindblad", False),
    ("American Cruise Lines", r"american\s+cruise\s+lines", False),
]
_LINE_RE = [(name, re.compile(p, 0 if exact else re.I)) for name, p, exact in _LINE_NAMES]
# Only ships whose names are not also places: Holland America's Rotterdam,
# Volendam and Zaandam are left out because river cruises stop at those towns.
_SHIPS = {
    "Holland America": ["Eurodam", "Nieuw Statendam", "Nieuw Amsterdam", "Koningsdam",
                        "Oosterdam", "Westerdam", "Noordam", "Zuiderdam"],
    "Royal Caribbean": ["Icon of the Seas", "Star of the Seas", "Utopia of the Seas",
                        "Wonder of the Seas", "Symphony of the Seas", "Harmony of the Seas",
                        "Allure of the Seas", "Oasis of the Seas", "Quantum of the Seas",
                        "Ovation of the Seas", "Anthem of the Seas", "Odyssey of the Seas",
                        "Spectrum of the Seas", "Freedom of the Seas", "Liberty of the Seas",
                        "Independence of the Seas", "Mariner of the Seas", "Navigator of the Seas",
                        "Explorer of the Seas", "Adventure of the Seas", "Voyager of the Seas",
                        "Radiance of the Seas", "Brilliance of the Seas", "Serenade of the Seas",
                        "Jewel of the Seas", "Vision of the Seas", "Rhapsody of the Seas",
                        "Enchantment of the Seas", "Grandeur of the Seas"],
    "Virgin Voyages": ["Scarlet Lady", "Valiant Lady", "Resilient Lady", "Brilliant Lady"],
}
_SHIP_RE = [(line, ship, re.compile(r"\b" + ship + r"\b"))
            for line, ships in _SHIPS.items() for ship in ships]
_ISLANDS = [
    ("Holland America", r"half\s+moon\s+cay"),
    ("Royal Caribbean", r"perfect\s+day\s+at\s+cococay|cococay|labadee"),
    ("Carnival", r"celebration\s+key|mahogany\s+bay|amber\s+cove"),
    ("Norwegian", r"great\s+stirrup\s+cay|harvest\s+caye"),
    ("MSC", r"ocean\s+cay"),
    ("Disney", r"castaway\s+cay|lookout\s+cay"),
    ("Princess", r"princess\s+cays"),
]
_ISLAND_RE = [(line, re.compile(p, re.I)) for line, p in _ISLANDS]
# "MSC Grandiosa", "Carnival Firenze": the ship's name, where the copy gives it.
_NAMED_SHIP = re.compile(r"\b((?:MSC|Carnival|Norwegian|Celebrity|Disney)\s+[A-Z][a-z]+)\b")
_NOT_SHIP_WORDS = {"Cruise", "Cruises", "Caribbean", "Sea", "Line", "Bahamas", "Northern",
                   "Southern", "Eastern", "Western", "Alaska", "Europe", "Mediterranean", "Sale"}


def line(deal):
    """(cruise line, ship) as far as the copy says; either can be None."""
    text = "%s %s" % (deal.title or "", deal.summary or "")
    found, ship = None, None
    for name, pattern in _LINE_RE:
        if pattern.search(text):
            found = name
            break
    for owner, name, pattern in _SHIP_RE:
        if pattern.search(text) and found in (None, owner):
            found, ship = owner, name
            break
    if not found:
        for owner, pattern in _ISLAND_RE:
            if pattern.search(text):
                found = owner
                break
    if not ship:
        m = _NAMED_SHIP.search(text)
        if m and m.group(1).split()[-1] not in _NOT_SHIP_WORDS:
            ship = m.group(1)
    return found, ship


_DEPARTING = re.compile(r"depart\w*\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
                        r"\s+\d{1,2}(?:,\s*\d{4})?)")


def departure(deal):
    """The sailing date, where the copy states one, or None."""
    m = _DEPARTING.search(deal.summary or "")
    return m.group(1) if m else None


def wanted_cabin(profile):
    want = (profile.get("cruise_cabin") or "balcony").lower()
    return want if want in CABIN_MULT else "balcony"


def cabin_factor(deal, profile):
    """What to multiply the headline fare by to price the cabin you would book.

    A luxury fare is already for a good cabin, and an all-inclusive line's
    entry suite is the product, so neither is scaled.
    """
    if is_luxury(deal) or region(deal)[0] == "river" or flights_included(deal) \
            or _BUNDLE.search(deal.title or ""):
        return 1.0
    mult = dict(CABIN_MULT)
    known = BALCONY_BY_LINE.get(line(deal)[0])
    if known:
        mult["balcony"] = known
    return max(1.0, mult[wanted_cabin(profile)] / mult[cabin(deal)])


def perks(deal):
    text = _text(deal)
    return [name for name, pattern in _PERKS if pattern.search(text)]


def _dollars(match):
    for group in match.groups():
        if group:
            return float(group.replace(",", ""))
    return 0.0


def onboard_credit(deal):
    m = _ONBOARD_CREDIT.search(_text(deal))
    return _dollars(m) if m else 0.0


def flight_credit(deal):
    m = _FLIGHT_CREDIT.search(_text(deal))
    return _dollars(m) if m else 0.0


def flights_included(deal):
    return bool(_FLIGHTS_IN.search(deal.title or ""))


def stated_port(deal):
    """A port or port group the copy names, or None."""
    for text in (deal.title or "", _text(deal)):
        for key, pattern in _PORT_RE:
            if pattern.search(text):
                return key
    return None


def candidate_ports(deal):
    """(ports, stated): the ports to price, and whether the copy named them."""
    named = stated_port(deal)
    owner = line(deal)[0]
    sails_from = LINE_PORTS.get(owner)
    if named and named not in PORT_GROUPS:
        return [named], True
    if named:
        ports, stated = PORT_GROUPS[named], True
    else:
        ports, stated = [], False
        for group in region(deal)[2]["ports"]:
            ports.extend(PORT_GROUPS.get(group, [group]))
    # Sailings abroad board near the place the headline names, and a river ship
    # or far-off sailing has no usual US port at all.
    key = region(deal)[0]
    if not named and (key in _BOARD_AT_HEADLINE or not ports) and deal.destination \
            and deal.destination not in _INLAND \
            and (places.city(deal.destination) or {}).get("iata"):
        return [deal.destination], False
    if sails_from:
        ports = [p for p in ports if p in sails_from] or ports
    elif not named:
        # Nobody but Carnival sails from Mobile, and an unnamed line is not
        # evidence for the one port that would make the trip look cheapest.
        ports = [p for p in ports if p != "mobile"]
    return ports, stated


def _drive_option(port, info, profile, nights, travelers):
    from . import positioning
    cfg = positioning.config(profile)
    miles = info.get("drive_miles")
    if not miles:
        return None
    hours = miles * 2 / positioning.ROAD_MPH
    usd = miles * 2 * float(cfg["drive_cost_per_mile"]) \
        + float(cfg["parking_per_day"]) * (nights + 1)
    # A drive over about nine hours one way means a night on the road each way.
    if miles / positioning.ROAD_MPH > 9:
        usd += 2 * HOTEL_NIGHT_BEFORE.get(profile.get("travel_style", "mid"), 180.0)
    return {"port": port, "how": "drive", "party_usd": usd,
            "weighed_usd": usd + hours * float(cfg["drive_hour_usd"]),
            "drive_hours": hours}


def _fly_option(port, info, profile, nights, travelers, fare_curve, credit_pp):
    from . import positioning
    airport = info.get("air")
    if not airport:
        return None
    home = places.resolve((positioning.config(profile).get("base") or ""))
    if airport == home:
        return None
    est = positioning.estimate(airport, profile, fare_curve)
    if est is not None and est["source"] != "measured" \
            and (places.city(airport) or {}).get("country") != "US":
        curve = fare_curve(home, airport, "economy")
        if curve:
            est = dict(est, per_person_usd=curve * INTERNATIONAL_MULT, source="modelled")
    via = positioning.via_alternate(airport, profile, nights)
    air_party = None
    detail = None
    if est is not None:
        air_party = est["per_person_usd"] * travelers
        detail = {"source": est["source"], "nonstop": est["nonstop"], "via": None}
    if via and (air_party is None or via["party_usd"] < air_party):
        air_party = via["party_usd"]
        detail = {"source": "measured", "nonstop": False, "via": via["via"]}
    if air_party is None:
        return None
    credit = min(credit_pp * travelers, air_party)
    style = profile.get("travel_style", "mid")
    usd = air_party - credit + HOTEL_NIGHT_BEFORE.get(style, 180.0) + TRANSFER_PARTY
    out = {"port": port, "how": "fly", "party_usd": usd, "weighed_usd": usd,
           "air_party_usd": air_party, "flight_credit_usd": credit}
    out.update(detail)
    return out


def getting_there(deal, profile, fare_curve, nights):
    """The cheapest honest way from home to the ship and back, or None.

    Each candidate port is priced both ways where both exist - drive (fuel,
    wear, parking, a motel each way past nine hours) or fly (DOT fares, the
    hotel the night before, a transfer) - and the cheapest after weighing drive
    hours is kept. A headline that names no port is priced from the ports its
    region usually sails from, and says so.
    """
    if flights_included(deal):
        return {"port": None, "how": "included", "party_usd": 0.0,
                "weighed_usd": 0.0, "stated": True}
    travelers = max(1, int(profile.get("travelers", 1)))
    ports, stated = candidate_ports(deal)
    credit_pp = flight_credit(deal)
    best = None
    for port in ports:
        info = PORTS.get(port)
        if not info and places.city(port):
            info = {"name": places.label(port), "drive_miles": None, "air": port}
        if not info:
            continue
        for option in (_drive_option(port, info, profile, nights, travelers),
                       _fly_option(port, info, profile, nights, travelers,
                                   fare_curve, credit_pp)):
            if option and (best is None or option["weighed_usd"] < best["weighed_usd"]):
                best = option
    if best is not None:
        best["stated"] = stated
        best["port_name"] = (PORTS.get(best["port"]) or {}).get("name") \
            or places.label(best["port"])
    return best


def costs(deal, profile, nights):
    """The cruise's own costs beyond the fare, per party, in USD.

    Returns a dict the breakdown folds in: the cabin uplift, fees, gratuities,
    onboard and shore spend, and the onboard credit taken off.
    """
    style = profile.get("travel_style", "mid")
    travelers = max(1, int(profile.get("travelers", 1)))
    key, label, info = region(deal)
    luxury = is_luxury(deal)
    text = _text(deal)
    allin = luxury and re.search(r"all[\s-]inclusive", text, re.I)

    fees = 0.0 if (_FEES_IN.search(text) or allin) else info["fees"] * nights * travelers
    daily_tip = GRATUITY_BY_LINE.get(line(deal)[0], GRATUITY_DAILY)
    tips = 0.0 if (_TIPS_IN.search(text) or allin) else daily_tip * nights * travelers
    drinks = bool(_DRINKS_IN.search(text) or allin)
    onboard = (ONBOARD_WITH_DRINKS if drinks else ONBOARD_DAILY)[style] * nights * travelers
    # Not every day is a port day; about two in three on a typical itinerary.
    shore_mult = {"budget": 0.5, "mid": 1.0, "luxury": 1.8}[style]
    shore = info["shore"] * shore_mult * nights * travelers * 0.65
    obc = min(onboard_credit(deal), onboard + shore)
    return {
        "region": key, "region_label": label, "luxury": luxury,
        "cruise_line": line(deal)[0], "ship": line(deal)[1], "departs": departure(deal),
        "cabin": cabin(deal), "cabin_wanted": wanted_cabin(profile),
        "cabin_factor": cabin_factor(deal, profile),
        "fees_usd": fees, "gratuities_usd": tips, "onboard_usd": onboard,
        "shore_usd": shore, "onboard_credit_usd": obc,
        "drinks_included": drinks, "perks": perks(deal),
    }


def per_person(unit_usd, basis):
    """A headline fare as one person's. A cruise quoted as a total is DealNews'
    "From $1,116 for 2" - the only way the parser marks one - so it halves."""
    return unit_usd / 2.0 if basis == "total" else unit_usd


def expected_fare_per_night(deal):
    """The modelled inside-cabin fare a night for this sailing, est."""
    info = region(deal)[2]
    fare = float(info["fare"])
    if is_luxury(deal):
        fare *= LUXURY_FARE_MULT
    return fare


def comparable(deal_title, other_title):
    """True when two cruise headlines belong in the same price comparison."""
    class _T:
        def __init__(self, title):
            self.title, self.summary = title, ""
    a, b = _T(deal_title), _T(other_title)
    return region(a)[0] == region(b)[0] and is_luxury(a) == is_luxury(b)
