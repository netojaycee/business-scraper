# Status

Legend: `[ ]` todo · `[~]` in progress (tag, date) · `[x]` done · `[!]` blocked

Last updated: 2026-10-06 (end of session 1; see "Where we stopped")

## Where we stopped (end of session 1, 2026-10-06)
**State:** Phases 1-4 are built, tested (29 unit tests) and pushed to `origin/main`. The pipeline runs end to end on CSV input: import, dedupe, audit, score, export. It has only been run on a fictional 5-row fixture. **No real leads exist yet and no real Google call has ever been made.**

**Why we stopped:** there is no lead source yet.
- Google Places is built but blocked: no billing account (needs the owner's **$30 prepayment**), so no API key, no quota cap, no budget alert (P0-6 to P0-8).
- OpenStreetMap is too thin for Nigeria (24 estate agents, 6 with phone).
- Nigerian directories are unresearched (first probe used guessed URLs).

**Owner decision needed (pick one, in this order of preference):**
1. Pay the $30 and complete billing in the Cloud console (`business-scraper-510800`), then tell Claude. Claude then does P0-7, P0-8, P2-3b.
2. Sign up for the free tier of Apify or Outscraper, export a Google Maps CSV for "real estate agency" in Lagos, and drop it in `data/imports/`. Then run `import-csv`.
3. Ask Claude to do P2-5 (directory research) with the browser tools. Slower, data quality unknown.

**Next actions once leads exist (in order):**
1. `python -m scraper import-csv data/imports/<file>.csv --niche "real estate" --city Lagos --source apify`
2. `python -m scraper audit --limit 100` then `python -m scraper score` then `python -m scraper stats`
3. P4-4: eyeball 20 leads against their tiers and fix the rules in `scoring.py` where they disagree.
4. P3-3b (optional): free PageSpeed key.
5. Phase 5: message writer (WhatsApp first, then email; no pricing; ask for a meeting). Needs sender details in `.env` (`SENDER_*`) and optionally `ANTHROPIC_API_KEY`.

**Can be done with no leads and no money (good for an idle session):** P5-1 message spec and templates, P5-3 compliance helpers, P6-3 event logging commands, P2-5 directory research, P7-1 dashboard skeleton.

**Known caveats:** tier B "site did not load" must be re-checked on another day before any message mentions it (P4-3b). PageSpeed needs a key (keyless quota exhausted). Google's field-mask cost per request is unverified until P2-3b; start with `--max-requests 3`.

---

## Phase 0: Planning and setup
- [x] P0-1 Define business model, channels, niches (Nigeria first). See `architecture.md`.
- [x] P0-2 Create Google Cloud project `business-scraper` (ID `business-scraper-510800`).
- [x] P0-3 Enable Places API (New) on the project.
- [x] P0-4 Check OpenStreetMap coverage for Nigeria. Result: too thin to be the main source (24 estate agents, 6 with phone; ~2,400 schools, 32 with phone).
- [x] P0-5 Write `architecture.md`, `status.md`, `CLAUDE.md`.
- [!] P0-6 Link a billing account to the Cloud project. **Owner action:** $30 prepayment, dollar-enabled Visa/Mastercard.
- [ ] P0-7 Create API key restricted to Places API (New). Depends on P0-6.
- [ ] P0-8 Set daily quota cap and a budget alert in Google Cloud. Depends on P0-6.
- [x] P0-9 `git init` done; remote `origin` = `git@github.com:netojaycee/business-scraper.git`, branch `main`. Commit and push at the end of each work session so other sessions/agents see current state. `.env`, `data/`, `.venv/` are gitignored; never commit scraped contact data.

## Phase 1: Foundations
- [x] P1-1 `requirements.txt`, `.gitignore`, `.env.example`, venv setup.
- [x] P1-2 `scraper/config.py` (loads `.env`, `config/niches.json`).
- [x] P1-3 `scraper/db.py` with schema from `architecture.md` section 6, plus `init-db`.
- [x] P1-4 `scraper/cli.py` and `__main__.py` skeleton.
- [x] P1-5 `config/niches.json` with first niches and cities.
- [x] P1-6 Basic tests for db and dedupe.

## Phase 2: Lead sources
- [x] P2-1 `sources/base.py`: `Lead` dataclass, `Source` interface, phone normalisation (+234), dedupe rules.
- [x] P2-2 `sources/csv_import.py`: flexible column mapping (Apify/Outscraper/manual). Command `import-csv`.
- [x] P2-3 `sources/google_places.py`: text search, pagination, field mask, `api_usage` ledger, per-run and per-day caps, `collect --dry-run`. Unit-tested (caps, mapping, closed-place filter). Refuses to run without a key.
- [!] P2-3b First live Places call: verify the field mask, response mapping and real cost per request. Blocked on P0-6/P0-7. Start with `--max-requests 3`, then check the Cloud billing report before scaling.
- [ ] P2-4 `sources/osm.py`: Overpass with proper `User-Agent`; used only to cross-check website presence.
- [ ] P2-5 Nigerian directory research: find real URL structures for VConnect, BusinessList.ng, Finelib, Nigeria Yellow Pages; check robots.txt; decide which are scrapable. Write findings here.
- [ ] P2-6 Directory collector(s) for whichever sites pass P2-5.
- [ ] P2-7 Pilot data: 100 leads (real estate + private schools, Lagos/Abuja) from the cheapest working source.

## Phase 3: Website audit
- [x] P3-1 `audit/website.py`: reachability, HTTPS, load time, mobile viewport, title/meta, CTA detection, copyright year, builder fingerprint, social-only detection.
- [x] P3-2 `audit/contacts.py`: emails, WhatsApp links, Facebook/Instagram links from the HTML.
- [x] P3-3 `audit/pagespeed.py` written; returns None on any failure. **Keyless calls hit a shared daily quota (HTTP 429, tested 2026-10-06), so it needs a key.**
- [ ] P3-3b Create a PageSpeed Insights API key (free, no billing needed) in the Cloud project, put it in `.env` as `PAGESPEED_API_KEY`, and test `audit --pagespeed` on 3 real sites. Optional: load time and viewport checks already work without it.
- [x] P3-4 Command `audit` with concurrency limit, resume, error capture.

## Phase 4: Scoring and classification
- [x] P4-1 `scoring.py`: tiers A/B/C/D with human-readable reasons.
- [x] P4-2 Lead score: `rating × log(reviews)` × niche weight.
- [x] P4-3 Commands `score` and `export` (CSV by tier/niche/city).
- [ ] P4-3b Before any outreach claims a site is down (tier B, "did not load"), re-check it on a different day. One failed fetch is not proof. Add a `recheck` step.
- [ ] P4-4 Review on the pilot set: do tiers match a human eyeballing 20 leads?

## Phase 5: Message writer
- [ ] P5-1 Message spec: WhatsApp (about 60 words) and email (60–100 words), no pricing, meeting ask, truthful specifics per tier.
- [ ] P5-2 `outreach/writer.py` with Claude (needs `ANTHROPIC_API_KEY`) and a template fallback.
- [ ] P5-3 `outreach/compliance.py`: suppression check, opt-out line, sender address, daily caps.
- [ ] P5-4 Review queue: export drafts to CSV/markdown for the owner to approve or edit.
- [ ] P5-5 Preview/mockup offer for tier A: only if a real preview exists. Decide process and tooling.

## Phase 6: Sending and tracking
- [ ] P6-1 WhatsApp click-to-chat links (`wa.me`) prepared per approved message, so the owner sends manually.
- [ ] P6-2 Email sending path: dedicated domain, SPF/DKIM/DMARC, Gmail API or a sending tool. Owner decision needed.
- [ ] P6-3 `events` logging commands: sent, reply, meeting, won, lost, optout.
- [ ] P6-4 Follow-up scheduling (day 3 and day 7), stops on reply or opt-out.
- [ ] P6-5 Pipeline report: contacted, replies, meetings, wins by niche/city/channel.

## Phase 7: Review dashboard (optional)
- [ ] P7-1 Small local UI (Flask or Streamlit) for browsing leads, editing drafts, logging outcomes.

## Phase 8: Scale
- [ ] P8-1 More Nigerian cities (Abuja, Port Harcourt, Ibadan, Kano, Enugu).
- [ ] P8-2 Additional niches (clinics, hotels, venues, law/accounting, logistics, solar, car dealers).
- [ ] P8-3 Ghana, Kenya, South Africa. Review local data-protection and marketing rules first.
- [ ] P8-4 Instagram-based ecommerce seller discovery (separate source).
- [ ] P8-5 Switch bulk collection to Google Places once funded and capped.

---

## Open decisions (owner)
1. Pay the $30 Google prepayment now, or run on CSV/free sources first? (Pipeline is built to work either way.)
2. Which free route for Google-style data: Apify or Outscraper free tier (owner signs up and provides key), or directory research (P2-5)?
3. Email sending domain and tool (P6-2).
4. Sender identity and address for message footers (`SENDER_*` in `.env`).

## How to verify the current build
```
source .venv/bin/activate
python -W ignore -m unittest          # 29 tests should pass
python -W ignore -m scraper collect --niche "real estate" --city Lagos --dry-run   # shows plan, makes no calls
```
Smoke test used a fictional 5-row CSV (one duplicate, one no-site, one social-only, one unreachable `.invalid` domain, one live `example.com`) and produced tiers A, A, B, C with the duplicate merged. The test DB was deleted afterwards; `data/` holds no real data yet.

## Session log
- 2026-10-06 (session 1): Defined plan. Created Cloud project and enabled Places API. Confirmed no billing account exists (blocker). Tested OSM coverage for Nigeria (thin). First directory probe inconclusive (guessed URLs). Wrote the three docs.
- 2026-10-06 (session 1, later): Built Phases 1-4 (scaffold, db, CSV import, Google Places collector with caps, website audit, scorer, export, CLI) with 29 passing tests and an end-to-end smoke run. Found and fixed a bug in `host_of` for scheme-less URLs. PageSpeed keyless quota is exhausted (429), key needed. Unreachable-site reason text made neutral because one failed fetch is not proof of an outage. Added `PLACES_MAX_REQUESTS_PER_DAY` (default 150) as a second spend guard. Nothing run on real data; no real Google calls made.
