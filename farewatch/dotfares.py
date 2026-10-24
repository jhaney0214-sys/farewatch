"""What passengers actually paid on a US domestic route, from DOT.

tools/build_routes.py writes data/route_fares.json from DOT's Consumer Airfare
Report. This reads it. A deal fare is not judged against it - deals run at about
0.4x what the cheapest carrier averages, so as an expectation it would score
nearly every deal at the cap - but it is the one measured market price the card
can quote, where the fare curve can only estimate.
"""

import json
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "route_fares.json")
_TABLE = None


def route_key(a, b):
    return "|".join(sorted((a, b)))


def load(path=None):
    """The table, or {} when it has not been built."""
    global _TABLE
    if _TABLE is not None and path is None:
        return _TABLE
    try:
        with open(path or PATH, encoding="utf-8") as fh:
            table = json.load(fh)
    except (OSError, ValueError):
        table = {}
    if path is None:
        _TABLE = table
    return table


def lookup(origin, destination, table=None):
    """The route row for a city pair, either direction, or None."""
    if not origin or not destination:
        return None
    table = load() if table is None else table
    return (table.get("routes") or {}).get(route_key(origin, destination))
