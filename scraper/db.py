from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

from scraper.config import DATA_DIR, DB_PATH
from scraper.sources.base import Lead

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  dedupe_key TEXT,
  name TEXT NOT NULL,
  niche TEXT, city TEXT, country TEXT, address TEXT,
  phone TEXT, whatsapp TEXT, email TEXT, website TEXT, maps_url TEXT,
  rating REAL, review_count INTEGER, lat REAL, lon REAL,
  raw_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_leads_dedupe ON leads(dedupe_key);

CREATE TABLE IF NOT EXISTS audits (
  lead_id INTEGER PRIMARY KEY REFERENCES leads(id),
  audited_at TEXT DEFAULT CURRENT_TIMESTAMP,
  has_website INTEGER, website_is_social INTEGER,
  http_status INTEGER, final_url TEXT, https INTEGER, load_ms INTEGER,
  psi_mobile INTEGER, mobile_viewport INTEGER,
  title TEXT, meta_description TEXT, has_cta INTEGER,
  copyright_year INTEGER, builder TEXT,
  emails_found TEXT, socials TEXT, error TEXT
);

CREATE TABLE IF NOT EXISTS scores (
  lead_id INTEGER PRIMARY KEY REFERENCES leads(id),
  tier TEXT, score REAL, reasons TEXT,
  scored_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER REFERENCES leads(id),
  channel TEXT, subject TEXT, body TEXT,
  status TEXT DEFAULT 'draft', model TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, sent_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER REFERENCES leads(id),
  type TEXT, note TEXT,
  at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT, sku TEXT, count INTEGER DEFAULT 1,
  at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS suppression (
  contact TEXT PRIMARY KEY, reason TEXT,
  at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

_MERGE_FIELDS = (
    "niche", "city", "country", "address", "phone", "whatsapp", "email",
    "website", "maps_url", "rating", "review_count", "lat", "lon",
)


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _empty(value: object) -> bool:
    return value is None or value == ""


def upsert_lead(conn: sqlite3.Connection, lead: Lead) -> Tuple[int, str]:
    """Insert a lead or merge it into an existing one.

    Returns (lead_id, status) where status is 'inserted' or 'merged'.
    Same (source, source_id): newer non-empty values overwrite.
    Same dedupe_key from another source: only empty fields are filled.
    """
    key = lead.dedupe_key()
    row = conn.execute(
        "SELECT * FROM leads WHERE source = ? AND source_id = ?",
        (lead.source, lead.source_id),
    ).fetchone()
    overwrite = row is not None
    if row is None and key:
        row = conn.execute(
            "SELECT * FROM leads WHERE dedupe_key = ? ORDER BY id LIMIT 1", (key,)
        ).fetchone()

    if row is None:
        cur = conn.execute(
            """INSERT INTO leads (source, source_id, dedupe_key, name, niche, city,
               country, address, phone, whatsapp, email, website, maps_url, rating,
               review_count, lat, lon, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                lead.source, lead.source_id, key, lead.name, lead.niche, lead.city,
                lead.country, lead.address, lead.phone, lead.whatsapp, lead.email,
                lead.website, lead.maps_url, lead.rating, lead.review_count,
                lead.lat, lead.lon, json.dumps(lead.raw, default=str),
            ),
        )
        conn.commit()
        return int(cur.lastrowid), "inserted"

    updates = {}
    for field in _MERGE_FIELDS:
        new = getattr(lead, field)
        if _empty(new):
            continue
        if overwrite or _empty(row[field]):
            updates[field] = new
    if not row["dedupe_key"] and key:
        updates["dedupe_key"] = key
    if updates:
        sets = ", ".join("%s = ?" % k for k in updates)
        conn.execute(
            "UPDATE leads SET %s, updated_at = CURRENT_TIMESTAMP WHERE id = ?" % sets,
            list(updates.values()) + [row["id"]],
        )
        conn.commit()
    return int(row["id"]), "merged"


def record_usage(conn: sqlite3.Connection, provider: str, sku: str, count: int = 1) -> None:
    conn.execute(
        "INSERT INTO api_usage (provider, sku, count) VALUES (?,?,?)",
        (provider, sku, count),
    )
    conn.commit()


def usage_today(conn: sqlite3.Connection, provider: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(count), 0) AS n FROM api_usage "
        "WHERE provider = ? AND date(at) = date('now')",
        (provider,),
    ).fetchone()
    return int(row["n"])
