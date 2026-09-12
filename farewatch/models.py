"""The Deal record that every other module reads or writes."""

import hashlib
import re
from dataclasses import dataclass, field, asdict

KINDS = ("flight", "hotel", "package", "cruise", "other")

# What a headline price actually covers. Getting this wrong is the fastest way to
# rank a deal badly, so it is explicit rather than inferred at scoring time.
BASIS = ("total", "per_person", "per_night", "per_room_night")


@dataclass
class Deal:
    source: str
    title: str
    url: str
    published: str = ""
    summary: str = ""

    kind: str = "other"
    price: float | None = None
    currency: str | None = None
    price_usd: float | None = None
    basis: str = "total"

    origin: str | None = None          # canonical city key, or None
    # True when the origin was stated as a departure ("flights from Vienna")
    # rather than inferred from mention order or an itinerary ("Lisbon to Porto").
    origin_is_departure: bool = True
    destination: str | None = None     # canonical city key, or None
    nights: int | None = None
    roundtrip: bool = False
    cabin: str = "economy"             # economy | premium | business | first

    fingerprint: str = ""
    first_seen: str = ""
    is_new: bool = True

    score: float = 0.0
    reasons: list = field(default_factory=list)
    trip: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


_PUNCT = re.compile(r"[^a-z0-9]+")


def fingerprint(deal):
    """Stable identity for a deal, so the same fare on four blogs collapses to one.

    Deliberately ignores the source and the exact wording: the same route at the
    same price is the same opportunity no matter who wrote it up. Falls back to
    the URL when a deal has no route or price to key on, which keeps unparsed
    items from all colliding into a single row.
    """
    if deal.destination and deal.price_usd:
        bucket = int(round(deal.price_usd / 25.0))  # tolerate small price drift
        parts = [deal.kind, deal.origin or "?", deal.destination, str(bucket)]
    else:
        parts = ["url", deal.url or _PUNCT.sub("-", deal.title.lower())]
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
