# Architecture

Lead-generation pipeline for a web-design business. It finds businesses (Nigeria first, then wider Africa), audits their web presence, scores and classifies them, and drafts personalised first-contact messages whose only goal is to **book a meeting**. Pricing is never sent before the first meeting.

> Read `status.md` for what is done and what to do next. Read `CLAUDE.md` for working rules.

---

## 1. Business model in one paragraph

Businesses with no website, or a poor one, are prospects for a quick site build. The pipeline collects businesses from several sources, checks whether each has a site and how good it is, ranks them, and prepares a short, truthful, specific message (WhatsApp first, email where an address exists). A human reviews and sends. Replies turn into meetings, and the meeting is where the offer and price are discussed.

## 2. Key decisions (and why)

| Decision | Reason |
|---|---|
| Pluggable lead sources behind one interface | Google billing is not yet available (needs a $30 prepayment). The rest of the pipeline must not care where leads came from. |
| Google Places API (New), not scraping Google Maps | Scraping violates Google's ToS and breaks often. The API is cheap at pilot scale. |
| WhatsApp is the primary channel in Nigeria | Most Nigerian SMEs live on WhatsApp and Instagram. Few publish an email. Email is secondary. |
| Human reviews every message before it is sent | Protects sender reputation and brand. Drafts are cheap, mistakes are not. |
| No pricing in outreach | Owner's rule. The message sells the meeting only. |
| Personalisation uses only true, observed facts | Persuasive without being deceptive. Never invent familiarity or claim to have "randomly found" them. |
| SQLite as the store | Single user, small data, zero setup, easy for multiple agents to inspect. |
| Python 3.9-compatible code | System Python is 3.9.6. Use `from __future__ import annotations`; no `X \| Y` runtime unions, no `match`. |

## 3. Stack

- **Language:** Python 3.9+ (venv in `.venv/`)
- **HTTP/HTML:** `requests`, `beautifulsoup4`
- **Storage:** SQLite (`data/leads.db`) via stdlib `sqlite3`
- **Config:** `.env` (secrets, never committed) plus `config/niches.json` (niches, cities, search terms)
- **CLI:** `argparse` in `scraper/cli.py`, run as `python -m scraper <command>`
- **Message drafting:** Anthropic API (Claude) with a template fallback when no key is set
- **Site speed signal:** Google PageSpeed Insights API (free tier, optional key)
- **Later:** small review dashboard (Flask or Streamlit), Gmail API or a sending tool for email

## 4. Project structure

```
business-scraper/
├── CLAUDE.md              # Working rules for any Claude session/agent (read first)
├── architecture.md        # This file
├── status.md              # Phased task list with done markers (source of truth for progress)
├── requirements.txt
├── .env.example           # Names of required secrets, no values
├── .gitignore
├── config/
│   └── niches.json        # Niches, search terms, cities, priority weights
├── scraper/
│   ├── __init__.py
│   ├── __main__.py        # python -m scraper
│   ├── cli.py             # Commands: init-db, collect, import-csv, audit, score, export, ...
│   ├── config.py          # Loads .env and niches.json
│   ├── db.py              # Schema, connection, upsert helpers
│   ├── sources/
│   │   ├── base.py        # Lead dataclass + Source interface
│   │   ├── google_places.py   # Places API (New) text search, with usage cap
│   │   ├── csv_import.py      # Universal import (Apify/Outscraper/manual CSVs)
│   │   └── osm.py             # OpenStreetMap enrichment (thin data; secondary)
│   ├── audit/
│   │   ├── website.py     # Fetch site, HTTPS, mobile viewport, CTA, copyright year, builder
│   │   ├── contacts.py    # Emails, WhatsApp, social links from HTML
│   │   ├── pagespeed.py   # PSI mobile score (optional; needs its own key, keyless quota is shared)
│   │   └── runner.py      # Concurrent audit run, saves to audits, enriches leads
│   ├── scoring.py         # Tier A/B/C/D and lead score with reasons
│   └── outreach/
│       ├── writer.py      # Draft messages (Claude, or template fallback)
│       └── compliance.py  # Suppression list, opt-out wording, per-day caps
├── data/                  # gitignored: leads.db, imports/, exports/
└── tests/
```

Directories are created as their phase is built. `status.md` says which exist.

## 5. Data flow

```
 sources ──► leads ──► audit ──► score/tier ──► draft message ──► human review ──► send ──► events
 (Google,    (dedupe)  (site +    (A/B/C/D)      (WhatsApp /       (approve/edit)   (manual WA link, (reply, meeting,
  CSV, OSM)            contacts)                  email)                              or email)        won, optout)
```

Every stage reads from and writes to SQLite, so stages can run independently and be resumed.

## 6. Data model (SQLite)

- `leads`: id, source, source_id, name, niche, city, country, address, phone, whatsapp, email, website, maps_url, rating, review_count, lat, lon, raw_json, created_at, updated_at. Unique on (source, source_id). Cross-source dedupe by normalised phone, then name+city.
- `audits`: lead_id, audited_at, has_website, website_is_social, http_status, final_url, https, load_ms, psi_mobile, mobile_viewport, title, meta_description, has_cta, copyright_year, builder, emails_found (json), socials (json), error
- `scores`: lead_id, tier, score, reasons (json), scored_at
- `messages`: id, lead_id, channel (whatsapp/email), subject, body, status (draft/approved/sent/skipped), model, created_at, sent_at
- `events`: id, lead_id, type (sent/reply/meeting/won/lost/optout), note, at
- `api_usage`: id, provider, sku, count, at. A ledger so spend can be capped in code as well as in Google Cloud.
- `suppression`: contact, reason, at. Anything here is never messaged again.

## 7. Lead sources

| Source | Status | Notes |
|---|---|---|
| **Google Places API (New)** | Built when key available. **Blocked on billing** (the $30 prepayment). | `POST places:searchText`, field mask `places.id,displayName,formattedAddress,nationalPhoneNumber,internationalPhoneNumber,websiteUri,rating,userRatingCount,googleMapsUri,businessStatus,types`. Phone/website/rating are in a higher billing tier, so a per-run request cap and the `api_usage` ledger are mandatory. |
| **CSV import** | First to build | Accepts exports from Apify/Outscraper or hand-built sheets. Flexible column-name mapping. Makes the pipeline usable with zero Google spend. |
| **OpenStreetMap (Overpass)** | Tested 2026-10-06, thin; no collector built | Nigeria has only 24 estate agents (6 with phone), about 2,400 schools (32 with phone). Use for website-presence cross-checks, not as the main lead source. Needs a real `User-Agent` header or it returns 406. |
| **Nigerian directories** | Unresolved | VConnect, BusinessList.ng, Finelib, Nigeria Yellow Pages. First probe used guessed URLs (404/unreachable); Kompass blocked bots. Needs a manual look at real page structure. |
| **Facebook/Instagram pages** | Future | WhatsApp numbers live here. Manual or semi-manual. |

### Google Cloud state (as of 2026-10-06)
- Project: `business-scraper`, ID `business-scraper-510800`
- Places API (New): enabled
- Billing account: **none linked**. The owner has no billing accounts. Google asks for a $30 prepayment in Nigeria.
- Before any real run: create an API key restricted to Places API (New), set a daily quota cap, set a budget alert. The owner enters card details; Claude never does.

## 8. Website audit and scoring

### Audit signals
No website, or the "website" is just a Facebook/Instagram/linktree link. For real sites: reachable, HTTPS valid, load time, mobile viewport tag, PageSpeed mobile score, visible call-to-action (call/WhatsApp/book/contact), copyright year, site-builder fingerprint (Wix, Weebly, Blogger, free-subdomain), contact info present.

### Tiers
| Tier | Meaning | Angle in first message |
|---|---|---|
| **A** | No website (or social-only) | "People searching for you can't find a site" |
| **B** | Poor site: unreachable/no HTTPS/no mobile viewport/slow/stale/no CTA | One specific, verifiable problem |
| **C** | Acceptable site | Low priority |
| **D** | Strong site | Skip |

### Lead score
Within tier, rank by `rating × log(review_count)` × niche weight from `config/niches.json`. A highly rated business with many reviews and no site is the best lead: it has demand and can afford to pay.

## 9. Outreach rules

- Goal of every message: a short call or visit. **No pricing.**
- 60–100 words. One specific true observation about their business, one line of credibility, one low-friction ask.
- Reference real data only (their rating, review count, a measured load time, a missing page).
- Do not claim to have built something that does not exist. If a preview/mockup is offered, it must actually be built first.
- Every email carries a clear opt-out and the sender's physical address. WhatsApp messages carry an easy "reply STOP". Honour `suppression` always.
- Send small: roughly 30–50 messages per channel per day while the sender number/domain is new. Email needs a dedicated sending domain with SPF, DKIM and DMARC before volume.
- Legal context, not legal advice: Nigeria's Data Protection Act 2023 applies to personal data; CAN-SPAM (US), GDPR/PECR (EU/UK) and CASL (Canada) apply when targeting those regions. Start in Nigeria only and review before expanding.

## 10. Niches and geography

- **Phase 1 geography:** Lagos, then Abuja, Port Harcourt. Then other Nigerian cities. Then Ghana, Kenya, South Africa and beyond.
- **Priority niches** (high value per customer, present on Maps, often weak online): real estate agencies, private schools, clinics/dental, hotels and short-lets, event venues/planners, law and accounting firms, logistics/travel, solar installers, car dealers.
- **Ecommerce:** deferred. Nigerian online sellers are mostly Instagram-only and rarely appear on Maps; reach them via Instagram search later.
- Start with one niche in one city (real estate and private schools in Lagos/Abuja), get replies, then widen.

## 11. Secrets and safety

- Secrets only in `.env` (gitignored). `.env.example` lists the names.
- Never commit `data/`. It holds scraped contact data.
- Never print API keys in logs or docs.
- Spend guard: code-level request cap per run plus a ledger, on top of the Cloud-side quota and budget alert.

## 12. Environment variables

```
GOOGLE_PLACES_API_KEY=      # restricted to Places API (New)
PAGESPEED_API_KEY=          # optional, raises PSI rate limit
ANTHROPIC_API_KEY=          # optional, enables Claude drafting; template fallback otherwise
SENDER_NAME=
SENDER_BUSINESS=
SENDER_ADDRESS=             # required in email footers
SENDER_WHATSAPP=
PLACES_MAX_REQUESTS_PER_RUN=50
PLACES_MAX_REQUESTS_PER_DAY=150   # second guard, summed from the api_usage ledger
```

## 13. Extending

- **New source:** subclass `Source` in `scraper/sources/`, yield `Lead` objects, register in `cli.py`. Nothing else changes.
- **New niche or city:** edit `config/niches.json`, then run `collect`.
- **New audit signal:** add a column to `audits`, extend `audit/website.py`, adjust `scoring.py`, add a line to `status.md`.
