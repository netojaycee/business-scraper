from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from scraper.audit import pagespeed
from scraper.audit.website import audit_url

_AUDIT_COLUMNS = (
    "has_website", "website_is_social", "http_status", "final_url", "https", "load_ms",
    "psi_mobile", "mobile_viewport", "title", "meta_description", "has_cta",
    "copyright_year", "builder", "emails_found", "socials", "error",
)


def _save(conn: sqlite3.Connection, lead_id: int, result: Dict[str, Any]) -> None:
    values = dict(result)
    values["emails_found"] = json.dumps(values["emails_found"])
    values["socials"] = json.dumps(values["socials"])
    cols = ", ".join(_AUDIT_COLUMNS)
    marks = ", ".join("?" for _ in _AUDIT_COLUMNS)
    conn.execute(
        "INSERT OR REPLACE INTO audits (lead_id, %s) VALUES (?, %s)" % (cols, marks),
        [lead_id] + [values.get(c) for c in _AUDIT_COLUMNS],
    )
    # Enrich the lead with contacts found on its site, never overwriting what we have.
    lead = conn.execute("SELECT email, whatsapp FROM leads WHERE id = ?", (lead_id,)).fetchone()
    if not lead["email"] and result["emails_found"]:
        conn.execute("UPDATE leads SET email = ? WHERE id = ?", (result["emails_found"][0], lead_id))
    if not lead["whatsapp"] and result.get("whatsapp_found"):
        conn.execute("UPDATE leads SET whatsapp = ? WHERE id = ?", (result["whatsapp_found"], lead_id))
    conn.commit()


def run_audit(
    conn: sqlite3.Connection,
    limit: int = 50,
    refresh: bool = False,
    workers: int = 5,
    use_pagespeed: bool = False,
    psi_key: str = "",
    niche: str = "",
    city: str = "",
) -> Dict[str, int]:
    where, params = [], []  # type: List[str], List[Any]
    if not refresh:
        where.append("id NOT IN (SELECT lead_id FROM audits)")
    if niche:
        where.append("niche = ?")
        params.append(niche)
    if city:
        where.append("city = ?")
        params.append(city)
    sql = "SELECT id, website FROM leads"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id LIMIT ?"
    rows = conn.execute(sql, params + [limit]).fetchall()

    stats = {"audited": 0, "no_website": 0, "social_only": 0, "errors": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(audit_url, r["website"]): r["id"] for r in rows}
        for fut in as_completed(futures):
            lead_id = futures[fut]
            result = fut.result()
            if use_pagespeed and result["http_status"] and result["http_status"] < 400 \
                    and not result["website_is_social"]:
                result["psi_mobile"] = pagespeed.mobile_score(result["final_url"], psi_key)
            _save(conn, lead_id, result)
            stats["audited"] += 1
            if not result["has_website"]:
                stats["no_website"] += 1
            elif result["website_is_social"]:
                stats["social_only"] += 1
            elif result["error"]:
                stats["errors"] += 1
    return stats
