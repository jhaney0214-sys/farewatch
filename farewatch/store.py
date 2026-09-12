"""Remembering what we have already seen.

Two jobs. First, "new since last run" is the single most useful label on a deal
digest, and it needs state to exist. Second, a price history per route is what
eventually lets the value model stop guessing - every run quietly banks the
data, whether or not anything reads it yet.
"""

import json
import os
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
    return conn


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
