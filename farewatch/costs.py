"""What a deal actually costs you, once you have landed.

The headline price is the part everyone quotes and the smaller half of the truth.
A $300 fare to Zurich and a $400 fare to Bangkok are not a $100 difference: seven
days of food, transit and a bed cost roughly $1,500 in the first case and $450 in
the second, so the "expensive" fare is $650 cheaper to actually take.

That gap is the whole reason this module exists. It also applies the currency
tailwind from fx.py, because on-the-ground costs are the part of a trip that
exchange rates actually move - the fare is already quoted in your own money.
"""

from . import places

STYLES = ("budget", "mid", "luxury")

# What a night at sea costs beyond the fare: gratuities, drinks, excursions, wifi.
CRUISE_ONBOARD_DAILY = {"budget": 25.0, "mid": 70.0, "luxury": 160.0}

# Fallback trip lengths when a headline does not say. Chosen to match how each
# kind of deal is usually taken rather than to be flattering.
DEFAULT_NIGHTS = {"flight": 7, "hotel": 3, "package": 7, "cruise": 7, "other": 5}


def nights_for(deal, profile):
    if deal.nights:
        return deal.nights
    override = (profile.get("default_nights") or {}).get(deal.kind)
    return override or DEFAULT_NIGHTS.get(deal.kind, 5)


def daily_rates(dest_key, style="mid"):
    """(ground_per_day, lodging_per_night) in USD for a destination, or (None, None)."""
    city = places.city(dest_key)
    country = places.country_of(dest_key)
    if not city or not country:
        return None, None
    mult = city["mult"]
    return (country["ground_daily"][style] * mult,
            country["lodging"][style] * mult)


def price_as_total(deal, nights, travelers):
    """Normalise a headline price to what the whole party actually pays.

    Deal copy quotes four different things and only labels three of them, so
    getting this wrong is the difference between a bargain and a mirage.
    """
    price = deal.price
    if price is None:
        return None
    if deal.basis == "per_person":
        return price * travelers
    if deal.basis == "per_night":
        return price * nights * travelers
    if deal.basis == "per_room_night":
        # A double room holds two people; a third traveller needs a second room.
        rooms = max(1, (travelers + 1) // 2)
        return price * nights * rooms
    return price


def breakdown(deal, profile, rates):
    """Full all-in cost of taking this deal, in the profile's home currency.

    Returns a dict of numbers plus the assumptions used to get them, because a
    trip cost you cannot audit is a trip cost you will not trust.
    """
    style = profile.get("travel_style", "mid")
    if style not in STYLES:
        style = "mid"
    travelers = max(1, int(profile.get("travelers", 1)))
    home = (profile.get("home_currency") or "USD").upper()
    nights = nights_for(deal, profile)

    ground_day, lodging_night = daily_rates(deal.destination, style)
    dest_currency = places.currency_of(deal.destination)

    out = {
        "style": style,
        "travelers": travelers,
        "nights": nights,
        "home_currency": home,
        "dest_currency": dest_currency,
        "known": ground_day is not None,
    }

    # --- the deal itself ---------------------------------------------------
    # Two different numbers, both needed. The unit price is what the source
    # quoted and what a reader recognises; the party total is what leaves your
    # account. Showing one under the other's label is how a $819 fare gets
    # displayed as "$1,638 per person".
    out["unit_usd"] = rates.to_usd(deal.price, deal.currency)
    total_price = price_as_total(deal, nights, travelers)
    deal.price_usd = rates.to_usd(total_price, deal.currency)
    if deal.price_usd is None:
        out["known"] = False
        return out
    out["deal_usd"] = deal.price_usd

    if not out["known"]:
        out["total_usd"] = deal.price_usd
        out["total_home"] = rates.convert(deal.price_usd, "USD", home)
        return out

    # --- currency tailwind -------------------------------------------------
    tailwind = rates.tailwind(home, dest_currency)
    out["tailwind"] = tailwind
    out["tailwind_note"] = rates.describe_tailwind(home, dest_currency)
    # A home currency that buys 12% more of theirs makes their prices 12% off.
    fx_factor = 1.0 / (1.0 + tailwind) if tailwind else 1.0
    out["fx_factor"] = fx_factor

    # --- on the ground -----------------------------------------------------
    ground = ground_day * nights * travelers * fx_factor
    out["ground_usd"] = ground

    if deal.kind == "flight":
        lodging = lodging_night * nights * max(1, (travelers + 1) // 2) * fx_factor
        out["lodging_usd"] = lodging
        out["lodging_included"] = False
    elif deal.kind == "cruise":
        # The fare covers the bed and the food; the rest is what gets you
        # ashore and what you drink once you are back on board.
        lodging = 0.0
        out["lodging_usd"] = 0.0
        out["lodging_included"] = True
        onboard = CRUISE_ONBOARD_DAILY[style] * nights * travelers
        out["onboard_usd"] = onboard
        # A cruise feeds you, so the shoreside ground estimate is mostly excursions.
        out["ground_usd"] = ground = ground * 0.45
        out["ground_usd"] += onboard
        ground = out["ground_usd"]
    else:  # hotel, package
        lodging = 0.0
        out["lodging_usd"] = 0.0
        out["lodging_included"] = True

    total_usd = deal.price_usd + ground + lodging
    out["total_usd"] = total_usd
    out["per_day_usd"] = total_usd / max(1, nights)

    for key in ("deal", "unit", "ground", "lodging", "total", "per_day", "onboard"):
        usd = out.get(key + "_usd")
        if usd is not None:
            out[key + "_home"] = rates.convert(usd, "USD", home)

    return out


def add_cost(trip, key, usd, rates):
    """Add a line item to a finished breakdown and re-total it.

    Exists so that costs computed after the fact - a positioning flight, say -
    land in the same totals as everything else instead of being bolted on at
    display time where the ranking would never see them.
    """
    if not usd or not trip.get("known"):
        return trip
    home = trip.get("home_currency", "USD")
    trip[key + "_usd"] = trip.get(key + "_usd", 0.0) + usd
    trip["total_usd"] = trip.get("total_usd", 0.0) + usd
    trip["per_day_usd"] = trip["total_usd"] / max(1, trip.get("nights") or 1)
    for name in (key, "total", "per_day"):
        value = trip.get(name + "_usd")
        if value is not None:
            trip[name + "_home"] = rates.convert(value, "USD", home)
    return trip


def sample_prices(dest_key, rates, home_currency="USD"):
    """A few real prices at the destination, for the 'what does a beer cost' question."""
    country = places.country_of(dest_key)
    city = places.city(dest_key)
    if not country or not city:
        return []
    mult = city["mult"]
    tailwind = rates.tailwind(home_currency, country["currency"])
    fx_factor = 1.0 / (1.0 + tailwind) if tailwind else 1.0

    items = [
        ("Cheap meal", country["meal_cheap"]),
        ("Dinner for two", country["meal_mid_two"]),
        ("Beer", country["beer"]),
        ("Transit ticket", country["transit"]),
        ("Hotel night (mid)", country["hotel_mid"]),
    ]
    out = []
    for label, usd in items:
        if not usd:
            continue
        local = rates.convert(usd * mult * fx_factor, "USD", home_currency)
        if local is not None:
            out.append((label, local))
    return out
