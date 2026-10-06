# CLAUDE.md

Project: lead-generation pipeline for a web-design business (Nigeria first, then Africa). Find businesses, audit their web presence, score them, draft meeting-booking outreach.

## Start every session like this
0. Run `git pull`, then read the "Where we stopped" section at the top of `status.md`. End your session by updating it, committing and pushing (remote: `origin`, branch `main`).
1. Read `status.md` (what is done, what is next, blockers, session log).
2. Read `architecture.md` if you need the why or the design.
3. Pick the first unblocked `[ ]` task, or one the owner names. Mark it `[~]` with your session/agent tag and date **before** starting.
4. When finished, mark it `[x]`, note anything the next person needs, and append a line to the session log in `status.md`.

## Rules
- **No pricing in outreach.** Messages sell the meeting only.
- **Truthful personalisation only.** Use real observed facts. Never fabricate familiarity, claim a site was built when it wasn't, or hide that it is outreach.
- **Never enter card or payment details.** The owner does all billing steps. Never request or print API keys.
- **Secrets live in `.env` only.** Never commit `.env` or `data/`. Never write key values into docs, logs or code.
- **Spend guard:** every Google Places run must respect `PLACES_MAX_REQUESTS_PER_RUN` and write to `api_usage`. Do not make bulk Places calls until billing, quota cap and budget alert are confirmed in `status.md`.
- **Human sends.** Messages are drafts until the owner approves. Do not send anything on the owner's behalf without explicit instruction.
- **Respect suppression.** Anything in the `suppression` table is never contacted.
- **Python 3.9 compatible.** Add `from __future__ import annotations`; no `match`, no runtime `X | Y` unions.
- **Be polite when fetching.** Real `User-Agent`, timeouts, small delays, honour robots.txt on directories. Overpass needs a descriptive `User-Agent` or it returns 406.

## Multi-agent coordination
- `status.md` is the single source of truth. Claim a task by changing `[ ]` to `[~] (tag, date)`. If a `[~]` is more than a day old with no log entry, ask the owner before taking it over.
- Stay inside the files your task names. If you must touch shared files (`db.py`, `cli.py`, `config/niches.json`), keep the change small and mention it in the session log.
- Schema changes: edit `scraper/db.py` and `architecture.md` section 6 together, and add a migration note to the session log.
- Do not mark a task `[x]` until it has been run and verified. Say how you verified it.

## Commands
```
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python -m scraper init-db
python -m scraper import-csv <file.csv> --niche "real estate" --city Lagos
python -m scraper collect --niche "real estate" --city Lagos     # Google Places; needs key + billing
python -m scraper audit --limit 50
python -m scraper score
python -m scraper export --tier A --out data/exports/tierA.csv
```
(Commands appear as their phases are built; `status.md` says which exist.)

## Owner context
- Based in Nigeria; pilot geography Lagos/Abuja, then other Nigerian cities, then Africa.
- Cash is tight. Google Places needs a **$30 prepayment** (not yet paid). Keep every source pluggable so work continues without it.
- Primary channel is WhatsApp; email is secondary.
- Owner prefers quick progress and concise reports. Surface decisions that are genuinely theirs; otherwise pick a sensible default and say so.
