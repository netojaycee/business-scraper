from __future__ import annotations

import datetime
import json
import math
import sqlite3
from typing import Any, Dict, List, Mapping, Tuple

from scraper.config import load_niches

# Statuses that usually mean our checker was blocked, not that the site is down.
BOT_BLOCK_STATUSES = (401, 403, 429, 503, 999)
WEAK_BUILDERS = ("weebly", "blogger", "free-subdomain", "google-business-site")
TIER_BASE = {"A": 100.0, "B": 70.0, "C": 30.0, "D": 0.0}


def classify(audit: Mapping[str, Any], year: int = 0) -> Tuple[str, int, List[str]]:
    """Return (tier, issue_points, reasons) from an audit row."""
    year = year or datetime.date.today().year
    if not audit["has_website"]:
        return "A", 0, ["No website listed"]
    if audit["website_is_social"]:
        return "A", 0, ["Only a social/link page, no real website"]

    status = audit["http_status"]
    if status is None:
        # Keep the raw error in the audits table; this text may end up in outreach,
        # and one failed check is not proof the site is down. Re-check before claiming it.
        return "B", 3, ["Website did not load when checked (re-check before mentioning)"]
    if status in BOT_BLOCK_STATUSES:
        return "C", 0, ["Site blocked the automated check (HTTP %d); verify by hand" % status]
    if status >= 400:
        return "B", 3, ["Website returns an error (HTTP %d)" % status]

    points, reasons = 0, []
    if audit["https"] == 0:
        points += 2
        reasons.append("No valid HTTPS (browsers show 'Not secure')")
    if audit["mobile_viewport"] == 0:
        points += 3
        reasons.append("Not mobile-friendly (no mobile viewport)")
    if audit["psi_mobile"] is not None and audit["psi_mobile"] < 50:
        points += 2
        reasons.append("Slow on mobile (PageSpeed %d/100)" % audit["psi_mobile"])
    elif audit["load_ms"] is not None and audit["load_ms"] > 4000:
        points += 2
        reasons.append("Slow to load (%.1fs)" % (audit["load_ms"] / 1000.0))
    if audit["copyright_year"] and audit["copyright_year"] <= year - 3:
        points += 2
        reasons.append("Looks outdated (copyright %d)" % audit["copyright_year"])
    if audit["has_cta"] == 0:
        points += 1
        reasons.append("No clear call/WhatsApp/contact action")
    if audit["builder"] in WEAK_BUILDERS:
        points += 1
        reasons.append("Built on %s" % audit["builder"])

    if points >= 3:
        return "B", points, reasons
    if points >= 1:
        return "C", points, reasons
    return "D", 0, ["No significant problems found"]


def lead_score(lead: Mapping[str, Any], tier: str, points: int, niche_weight: float) -> float:
    """Tier base + demand signal + contactability. Higher is a better lead."""
    score = TIER_BASE[tier] + points * 3
    rating = lead["rating"] or 0.0
    reviews = lead["review_count"] or 0
    score += rating * math.log1p(reviews) * niche_weight
    reachable = 0
    if lead["whatsapp"] or lead["phone"]:
        reachable += 5
    if lead["email"]:
        reachable += 5
    if reachable == 0:
        score -= 30.0  # cannot be contacted yet
    return round(score + reachable, 1)


def run_scoring(conn: sqlite3.Connection) -> Dict[str, int]:
    niches = load_niches()["niches"]
    rows = conn.execute(
        """SELECT l.*, a.has_website, a.website_is_social, a.http_status, a.https,
                  a.load_ms, a.psi_mobile, a.mobile_viewport, a.has_cta,
                  a.copyright_year, a.builder, a.error
           FROM leads l JOIN audits a ON a.lead_id = l.id"""
    ).fetchall()
    counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for row in rows:
        tier, points, reasons = classify(row)
        weight = niches.get(row["niche"] or "", {}).get("weight", 0.8)
        score = lead_score(row, tier, points, weight)
        conn.execute(
            "INSERT OR REPLACE INTO scores (lead_id, tier, score, reasons) VALUES (?,?,?,?)",
            (row["id"], tier, score, json.dumps(reasons)),
        )
        counts[tier] += 1
    conn.commit()
    return counts
