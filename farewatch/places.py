"""Turning the place names in a headline into somewhere with a currency and a price level."""

import json
import math
import os
import re

_DATA = None
_MATCHERS = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "destinations.json")

# Words that look like places in a headline but are not the destination.
STOPWORDS = {
    "deal", "deals", "sale", "flash", "cheap", "flight", "flights", "hotel",
    "hotels", "cruise", "cruises", "package", "packages", "economy", "business",
    "first", "class", "return", "roundtrip", "round", "trip", "nonstop",
    "non-stop", "direct", "from", "to", "and", "the", "for", "with", "night",
    "nights", "day", "days", "week", "off", "save", "new", "best", "top",
}


def load(path=None):
    global _DATA, _MATCHERS
    if _DATA is not None and path is None:
        return _DATA
    with open(path or DATA_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    _DATA = data
    _MATCHERS = _build_matchers(data)
    return data


def _build_matchers(data):
    """Name -> city key, longest first so 'New York' wins over 'York'."""
    pairs = []
    for key, city in data["cities"].items():
        pairs.append((key, key))
        # "Rio de Janeiro" is also written "Rio"; handled via aliases, not here.
    for alias, target in data["aliases"].items():
        pairs.append((alias, target))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)

    compiled = []
    for name, key in pairs:
        if name in STOPWORDS:
            continue
        pattern = re.compile(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])")
        compiled.append((pattern, key, len(name)))
    return compiled


def normalise(text):
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[‐-―−]", "-", text)   # dashes to ascii
    text = re.sub(r"[^\w\s\.\-]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def find_all(text):
    """Every place mentioned, as (city_key, start_index), in order of appearance."""
    load()
    norm = normalise(text)
    hits = []
    claimed = []  # spans already taken by a longer name

    for pattern, key, _length in _MATCHERS:
        for m in pattern.finditer(norm):
            span = (m.start(), m.end())
            if any(span[0] < c[1] and c[0] < span[1] for c in claimed):
                continue
            claimed.append(span)
            hits.append((key, span[0]))
    hits.sort(key=lambda h: h[1])

    seen = set()
    out = []
    for key, pos in hits:
        if key not in seen:
            seen.add(key)
            out.append((key, pos))
    return out


def resolve(name):
    """Resolve a single name to a city key, or None."""
    load()
    norm = normalise(name)
    if norm in _DATA["cities"]:
        return norm
    if norm in _DATA["aliases"]:
        return _DATA["aliases"][norm]
    code = norm.upper()
    if len(code) == 3 and code in _DATA["iata"]:
        return _DATA["iata"][code]
    found = find_all(name)
    return found[0][0] if found else None


def city(key):
    load()
    return _DATA["cities"].get(key)


def country(code):
    load()
    return _DATA["countries"].get(code)


def country_of(city_key):
    c = city(city_key)
    return country(c["country"]) if c else None


def currency_of(city_key):
    c = country_of(city_key)
    return c["currency"] if c else None


def label(city_key):
    c = city(city_key)
    if not c:
        return city_key or "?"
    ctry = country(c["country"])
    if ctry and ctry["name"] != c["name"]:
        return "%s, %s" % (c["name"], ctry["name"])
    return c["name"]


def distance_km(a_key, b_key):
    a, b = city(a_key), city(b_key)
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))
