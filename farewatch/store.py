"""Remembering what we have already seen.

Two jobs. First, "new since last run" is the single most useful label on a deal
digest, and it needs state to exist. Second, a price history per route is what
eventually lets the value model stop guessing - every run quietly banks the
data, whether or not anything reads it yet.
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "farewatch.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    fingerprint TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    times_seen  INTEGER NOT NULL DEFAULT 1,
    kind        TEXT,
    origin      TEXT,
    destination TEXT,
    price_usd   REAL,
    unit_usd    REAL,
    cabin       TEXT,
    nights      INTEGER,
    basis       TEXT,
    title       TEXT,
    url         TEXT,
    payload     TEXT
);
CREATE INDEX IF NOT EXISTS deals_route ON deals (origin, destination);
CREATE INDEX IF NOT EXISTS deals_seen  ON deals (last_seen);

CREATE TABLE IF NOT EXISTS price_log (
    deal_key TEXT NOT NULL,
    date     TEXT NOT NULL,
    price    REAL NOT NULL,
    PRIMARY KEY (deal_key, date)
);

CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at    TEXT NOT NULL,
    fetched   INTEGER,
    parsed    INTEGER,
    ranked    INTEGER,
    new_deals INTEGER
);
"""


# Columns added after the first release. SQLite has no "ADD COLUMN IF NOT
# EXISTS", so they are applied by inspection - cheap, and it means an existing
# database keeps its history instead of being thrown away for a schema bump.
MIGRATIONS = {
    "unit_usd": "ALTER TABLE deals ADD COLUMN unit_usd REAL",
    "cabin": "ALTER TABLE deals ADD COLUMN cabin TEXT",
    "nights": "ALTER TABLE deals ADD COLUMN nights INTEGER",
    "basis": "ALTER TABLE deals ADD COLUMN basis TEXT",
}


def migrate(conn):
    have = {row[1] for row in conn.execute("PRAGMA table_info(deals)")}
    applied = []
    for column, sql in MIGRATIONS.items():
        if column not in have:
            conn.execute(sql)
            applied.append(column)
    if applied:
        conn.commit()
        backfill(conn)
    return applied


def backfill(conn):
    """Recover the new columns from the payload JSON already on each row.

    Every row has always stored the whole deal as JSON, so the history the new
    columns need was there the entire time - it just was not queryable. Reading
    it back means a database collected before the columns existed keeps all of
    its value instead of only counting from the next run onward.
    """
    rows = conn.execute(
        "SELECT fingerprint, payload FROM deals WHERE unit_usd IS NULL"
        "   AND payload IS NOT NULL").fetchall()
    recovered = 0
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            continue
        trip = payload.get("trip") or {}
        unit = trip.get("unit_usd")
        if unit is None:
            continue
        conn.execute(
            "UPDATE deals SET unit_usd = ?, cabin = ?, nights = ?, basis = ?"
            " WHERE fingerprint = ?",
            (unit, payload.get("cabin"),
             payload.get("nights") or trip.get("nights"),
             payload.get("basis"), row["fingerprint"]))
        recovered += 1
    if recovered:
        conn.commit()
    return recovered


def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    if conn.execute("SELECT 1 FROM price_log LIMIT 1").fetchone() is None:
        backfill_prices(conn)
    rekey_prices(conn)
    return conn


# ---------------------------------------------------------------- price log
_DEAL_ID = re.compile(r"-(\d{6,})/?(?:[?#].*)?$|/(\d{6,})\.html")
# A lone hyphen needs a space after it, so "$500-off stay" keeps its words.
LEAD_PRICE = re.compile(r"^\$[\d,]+(?:\s*-\s*\$[\d,]+)?(?:\s*&\s*up)?\s*(?:--|[–—]|-\s)\s*")


def deal_key(url, title):
    """What stays the same when a deal's price changes.

    A fingerprint moves with the price, which is why it cannot carry a history.
    Travelzoo and DealNews number their deals in the URL, and that number survives
    a new price; anything else falls back to its headline without the price.
    """
    found = _DEAL_ID.search(url or "")
    if found:
        return found.group(1) or found.group(2)
    return "t:" + LEAD_PRICE.sub("", title or "").strip().lower()[:120]


def rekey_prices(conn):
    """Move price history logged under a key that still held its price (before
    2026-11-01, a range or a dash other than "--"), so it joins the deal's own."""
    for (old,) in conn.execute("SELECT DISTINCT deal_key FROM price_log WHERE deal_key LIKE 't:$%'").fetchall():
        new = "t:" + LEAD_PRICE.sub("", old[2:])
        if new != old:
            conn.execute("INSERT OR IGNORE INTO price_log SELECT ?, date, price FROM price_log WHERE deal_key = ?", (new, old))
            conn.execute("DELETE FROM price_log WHERE deal_key = ?", (old,))
    conn.commit()


def _per_person(price, kind, basis):
    return price / 2.0 if kind == "cruise" and basis == "total" else price


def backfill_prices(conn):
    """Start the log from every price already seen, so it begins with history.

    Each row is what a deal cost the day it first appeared at that price, which is
    exact for a change and says nothing about the days between.
    """
    rows = conn.execute("SELECT url, title, kind, basis, unit_usd, first_seen FROM deals"
                        " WHERE unit_usd IS NOT NULL ORDER BY first_seen").fetchall()
    for r in rows:
        conn.execute("INSERT OR IGNORE INTO price_log VALUES (?,?,?)",
                     (deal_key(r["url"], r["title"]), r["first_seen"][:10],
                      _per_person(r["unit_usd"], r["kind"], r["basis"])))
    conn.commit()


def log_prices(conn, deals, day=None):
    """Today's price for every deal in this pull. One a day: the last pull wins."""
    day = day or _now()[:10]
    for deal in deals:
        unit = (deal.trip or {}).get("unit_usd")
        if unit is None:
            continue
        conn.execute("INSERT OR REPLACE INTO price_log VALUES (?,?,?)",
                     (deal_key(deal.url, deal.title), day, _per_person(unit, deal.kind, deal.basis)))
    conn.commit()


def price_history(conn, keep=40):
    """{deal_key: [[date, price], ...]}: the first sighting, then each change."""
    out = {}
    for r in conn.execute("SELECT deal_key, date, price FROM price_log ORDER BY deal_key, date"):
        points = out.setdefault(r["deal_key"], [])
        if not points or round(points[-1][1]) != round(r["price"]):
            points.append([r["date"], round(r["price"])])
    # Keep the first price: "since it first appeared" is the point of the log.
    return {k: (v if len(v) <= keep else v[:1] + v[-(keep - 1):]) for k, v in out.items()}


def _now():
    return datetime.now(timezone.utc).isoformat()


def sync(conn, deals):
    """Record this run's deals, setting is_new on the ones we had not seen.

    A deal already in the table keeps its original first_seen, which is what
    makes "new" mean new rather than "present in the current feed".
    """
    now = _now()
    new_count = 0
    for deal in deals:
        row = conn.execute(
            "SELECT first_seen, times_seen FROM deals WHERE fingerprint = ?",
            (deal.fingerprint,)).fetchone()
        if row is None:
            deal.is_new = True
            deal.first_seen = now
            new_count += 1
            conn.execute(
                "INSERT INTO deals (fingerprint, first_seen, last_seen, times_seen,"
                " kind, origin, destination, price_usd, unit_usd, cabin, nights,"
                " basis, title, url, payload)"
                " VALUES (?,?,?,1,?,?,?,?,?,?,?,?,?,?,?)",
                (deal.fingerprint, now, now, deal.kind, deal.origin,
                 deal.destination, deal.price_usd,
                 (deal.trip or {}).get("unit_usd"), deal.cabin,
                 (deal.trip or {}).get("nights"), deal.basis,
                 deal.title, deal.url,
                 json.dumps(deal.to_dict(), default=str)))
        else:
            deal.is_new = False
            deal.first_seen = row["first_seen"]
            conn.execute(
                "UPDATE deals SET last_seen = ?, times_seen = ?, price_usd = ?,"
                " unit_usd = ?, cabin = ?, nights = ?, basis = ?, payload = ?"
                " WHERE fingerprint = ?",
                (now, row["times_seen"] + 1, deal.price_usd,
                 (deal.trip or {}).get("unit_usd"), deal.cabin,
                 (deal.trip or {}).get("nights"), deal.basis,
                 json.dumps(deal.to_dict(), default=str), deal.fingerprint))
    conn.commit()
    log_prices(conn, deals)
    return new_count


def record_run(conn, fetched, parsed, ranked, new_deals):
    conn.execute(
        "INSERT INTO runs (ran_at, fetched, parsed, ranked, new_deals)"
        " VALUES (?,?,?,?,?)", (_now(), fetched, parsed, ranked, new_deals))
    conn.commit()


def route_history(conn, origin, destination, limit=20):
    rows = conn.execute(
        "SELECT first_seen, price_usd, title FROM deals"
        " WHERE origin IS ? AND destination = ? AND price_usd IS NOT NULL"
        " ORDER BY first_seen DESC LIMIT ?",
        (origin, destination, limit)).fetchall()
    return [dict(r) for r in rows]


def stats(conn):
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(first_seen) AS since FROM deals").fetchone()
    runs = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()
    return {"deals": row["n"], "since": row["since"], "runs": runs["n"]}
