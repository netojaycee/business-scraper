from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import List, Optional

from scraper import db
from scraper.audit.runner import run_audit
from scraper.config import DATA_DIR, env, env_int, load_niches
from scraper.scoring import run_scoring
from scraper.sources import google_places
from scraper.sources.csv_import import CsvImport

EXPORT_COLUMNS = [
    "id", "tier", "score", "name", "niche", "city", "phone", "whatsapp", "wa_link",
    "email", "website", "rating", "review_count", "reasons", "maps_url", "address",
]


def _ingest(conn, leads) -> dict:
    counts = {"inserted": 0, "merged": 0}
    for lead in leads:
        _id, status = db.upsert_lead(conn, lead)
        counts[status] += 1
    return counts


def cmd_init_db(args, conn) -> int:
    db.init_db(conn)
    print("Database ready at %s" % (DATA_DIR / "leads.db"))
    return 0


def cmd_import_csv(args, conn) -> int:
    leads = CsvImport().fetch(
        path=args.path, niche=args.niche, city=args.city,
        country=args.country, source=args.source,
    )
    counts = _ingest(conn, leads)
    print("Imported: %(inserted)d new, %(merged)d merged into existing leads." % counts)
    return 0


def cmd_collect(args, conn) -> int:
    cfg = load_niches()
    if args.niche not in cfg["niches"]:
        print("Unknown niche '%s'. Options: %s" % (args.niche, ", ".join(cfg["niches"])))
        return 2
    if args.city not in cfg["cities"]:
        print("Unknown city '%s'. Options: %s" % (args.city, ", ".join(cfg["cities"])))
        return 2
    city_cfg = cfg["cities"][args.city]
    areas = None if args.no_areas else city_cfg.get("areas")
    queries = google_places.build_queries(cfg["niches"][args.niche]["queries"], args.city, areas)
    max_run = args.max_requests or env_int("PLACES_MAX_REQUESTS_PER_RUN", 50)
    max_day = env_int("PLACES_MAX_REQUESTS_PER_DAY", 150)
    bound = google_places.estimate_requests(len(queries), args.max_pages)
    used = db.usage_today(conn, google_places.PROVIDER)

    print("Plan: %d queries, up to %d requests (pages), per-run cap %d, used today %d/%d"
          % (len(queries), bound, max_run, used, max_day))
    if args.dry_run:
        for q in queries[:10]:
            print("  -", q)
        if len(queries) > 10:
            print("  ... and %d more" % (len(queries) - 10))
        return 0

    try:
        source = google_places.GooglePlaces(
            env("GOOGLE_PLACES_API_KEY"), conn, max_run, max_day,
        )
        leads = source.fetch(args.niche, args.city, city_cfg["country"], queries, args.max_pages)
        counts = _ingest(conn, leads)
    except google_places.SpendCapReached as exc:
        print("Stopped by spend guard: %s" % exc)
        return 3
    except google_places.PlacesError as exc:
        print("Places error: %s" % exc)
        return 1
    print("Collected: %(inserted)d new, %(merged)d merged. Requests made: " % counts
          + str(source.requests_made))
    return 0


def cmd_audit(args, conn) -> int:
    stats = run_audit(
        conn, limit=args.limit, refresh=args.refresh, workers=args.workers,
        use_pagespeed=args.pagespeed, psi_key=env("PAGESPEED_API_KEY"),
        niche=args.niche, city=args.city,
    )
    print("Audited %(audited)d (no website %(no_website)d, social-only %(social_only)d, "
          "errors %(errors)d)" % stats)
    return 0


def cmd_score(args, conn) -> int:
    counts = run_scoring(conn)
    print("Scored: " + ", ".join("%s=%d" % (t, n) for t, n in counts.items()))
    return 0


def cmd_export(args, conn) -> int:
    where, params = [], []  # type: List[str], list
    if args.tier:
        where.append("s.tier = ?")
        params.append(args.tier.upper())
    if args.niche:
        where.append("l.niche = ?")
        params.append(args.niche)
    if args.city:
        where.append("l.city = ?")
        params.append(args.city)
    if args.contactable:
        where.append("(l.phone != '' OR l.whatsapp != '' OR l.email != '')")
    sql = ("SELECT l.*, s.tier, s.score, s.reasons FROM leads l JOIN scores s ON s.lead_id = l.id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.score DESC LIMIT ?"
    rows = conn.execute(sql, params + [args.limit]).fetchall()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        for r in rows:
            wa = "".join(ch for ch in (r["whatsapp"] or "") if ch.isdigit())
            writer.writerow({
                "id": r["id"], "tier": r["tier"], "score": r["score"], "name": r["name"],
                "niche": r["niche"], "city": r["city"], "phone": r["phone"],
                "whatsapp": r["whatsapp"], "wa_link": ("https://wa.me/" + wa) if wa else "",
                "email": r["email"], "website": r["website"], "rating": r["rating"],
                "review_count": r["review_count"],
                "reasons": "; ".join(json.loads(r["reasons"] or "[]")),
                "maps_url": r["maps_url"], "address": r["address"],
            })
    print("Wrote %d leads to %s" % (len(rows), out))
    return 0


def cmd_stats(args, conn) -> int:
    total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    print("Leads: %d" % total)
    for label, sql in (
        ("By source", "SELECT source, COUNT(*) FROM leads GROUP BY source"),
        ("By niche", "SELECT COALESCE(niche,'?'), COUNT(*) FROM leads GROUP BY niche"),
        ("By tier", "SELECT tier, COUNT(*) FROM scores GROUP BY tier ORDER BY tier"),
    ):
        rows = conn.execute(sql).fetchall()
        if rows:
            print("%s: %s" % (label, ", ".join("%s=%d" % (r[0], r[1]) for r in rows)))
    print("Places requests today: %d" % db.usage_today(conn, google_places.PROVIDER))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scraper", description="Lead pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Create the database").set_defaults(fn=cmd_init_db)

    s = sub.add_parser("import-csv", help="Import leads from a CSV/JSON file")
    s.add_argument("path")
    s.add_argument("--niche", default="")
    s.add_argument("--city", default="")
    s.add_argument("--country", default="Nigeria")
    s.add_argument("--source", default="csv")
    s.set_defaults(fn=cmd_import_csv)

    s = sub.add_parser("collect", help="Collect leads from Google Places (needs key + billing)")
    s.add_argument("--niche", required=True)
    s.add_argument("--city", required=True)
    s.add_argument("--max-pages", type=int, default=google_places.MAX_PAGES)
    s.add_argument("--max-requests", type=int, default=0, help="Override per-run cap")
    s.add_argument("--no-areas", action="store_true", help="Search the whole city, not per area")
    s.add_argument("--dry-run", action="store_true", help="Show the plan and stop")
    s.set_defaults(fn=cmd_collect)

    s = sub.add_parser("audit", help="Audit lead websites")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--workers", type=int, default=5)
    s.add_argument("--refresh", action="store_true", help="Re-audit already audited leads")
    s.add_argument("--pagespeed", action="store_true", help="Add PageSpeed mobile score (slow)")
    s.add_argument("--niche", default="")
    s.add_argument("--city", default="")
    s.set_defaults(fn=cmd_audit)

    sub.add_parser("score", help="Score and tier audited leads").set_defaults(fn=cmd_score)

    s = sub.add_parser("export", help="Export scored leads to CSV")
    s.add_argument("--tier", default="")
    s.add_argument("--niche", default="")
    s.add_argument("--city", default="")
    s.add_argument("--contactable", action="store_true", help="Only leads with a phone or email")
    s.add_argument("--limit", type=int, default=500)
    s.add_argument("--out", default=str(DATA_DIR / "exports" / "leads.csv"))
    s.set_defaults(fn=cmd_export)

    sub.add_parser("stats", help="Show counts").set_defaults(fn=cmd_stats)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    conn = db.connect()
    db.init_db(conn)  # idempotent; keeps every command safe on a fresh checkout
    try:
        return args.fn(args, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
