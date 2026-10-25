# FX Watch

**Exchange-rate monitoring and email alerts built on official sources.**
Track any of 150+ currencies, explore their history, and get an email when a rate
reaches your threshold. No account or password needed.

[![CI](https://github.com/Asimeng/webscraping/actions/workflows/ci.yml/badge.svg)](https://github.com/Asimeng/webscraping/actions/workflows/ci.yml)

---

## Why

This project started as an R script that scraped my bank's website and emailed me when
the rand–euro rate passed a fixed level, so I could stop checking it by hand whenever my
stipend arrived (the original lives in [`legacy/`](legacy/)). FX Watch turns that idea into
a service anyone can use: pick a pair, set a level, confirm your email, and forget about it.

## Features

- **Dashboard.** A bookmarkable watchlist (pairs live in the URL) with day change and
  30-day sparklines, plus a searchable board of every currency against any base.
- **Converter.** Any-to-any conversion, a side-by-side comparison of every source with
  deviation from the median, and a quick-reference table.
- **History & analysis.** Up to 10+ years of official history: moving averages,
  volatility, percentile of today's rate, distribution, threshold preview, CSV export.
- **Alerts.** Rises above, falls below, or crosses, sent once or every time. Recurring alerts
  use hysteresis and a cooldown so a rate hovering at your level doesn't flood your inbox.
  Alerts expire, with a one-click extension reminder.
- **No accounts.** Double opt-in by email; a signed, password-free management link to
  pause, edit, re-arm, extend or delete alerts; link rotation; one-click "delete my data".
- **Transparency.** Every rate shows its source, date and whether it's a cross rate. A
  status page shows source health, coverage and recent fetch runs.

## Data sources

| Source | Type | Coverage | Used for |
|---|---|---|---|
| [European Central Bank](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) | Official | ~30 currencies, since 1999 | Primary for majors |
| [Bank of Canada Valet API](https://www.bankofcanada.ca/valet/docs) | Official | ~25 currencies, since 2017 | Second official source, cross-checks |
| [ExchangeRate-API (open)](https://www.exchangerate-api.com/docs/free) | Aggregator | ~150 currencies, latest only | Currencies official sources don't cover (GHS, NGN, KES…) |
| [fawazahmed0/exchange-api](https://github.com/fawazahmed0/exchange-api) | Open data | ~150 currencies, since 2024-03 | History for those currencies |

**How rates are combined:**
1. Each pair is priced from **one** source's snapshot. Legs from different publishers are
   never mixed.
2. The most authoritative source with a fresh rate for both currencies wins.
3. Before an alert fires, its rate is cross-checked against the median of the other sources.
   Disagreements beyond 2% hold the alert instead of sending a wrong email.

All rates are mid-market reference rates for information only.

## Architecture

```
 GitHub Actions (cron)            PostgreSQL (Neon)             Streamlit Community Cloud
 python -m fxwatch run-once  ──▶  rates · alerts · outbox  ◀──  streamlit_app.py
   1 fetch sources (+ backfill)                                   dashboard, converter,
   2 store observations (idempotent)                              history, alerts UI
   3 evaluate alerts → outbox
   4 deliver emails (Gmail SMTP, retried)
   5 housekeeping
```

Streamlit only serves pages and can sleep; the scheduled worker does the monitoring. Every
worker pass is idempotent: emails are written to a transactional **outbox** in the same
transaction as the alert state change, each with a unique key, so a crash or overlapping
run can never lose or duplicate an alert. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
fxwatch/            core package (no Streamlit imports)
  domain/           pure logic: cross rates, alert rules
  sources/          one adapter per publisher
  services/         rates, alerts, evaluation, outbox, tokens, rate limiting, analytics
  notify/           mail backends + HTML/text templates
  db/               SQLAlchemy models + Alembic migrations
  worker/           fetch → evaluate → deliver jobs
  cli.py            python -m fxwatch …
app/                Streamlit UI (views + shared components)
streamlit_app.py    entry point
tests/              unit, integration (SQLite & Postgres) and page smoke tests
```

## Quick start (local)

Requires **Python 3.11+** (3.12 recommended, as in production). A setup script creates the
virtualenv, installs dependencies, writes a `.env` with a fresh `SECRET_KEY`, creates the
database and downloads the first rates and history (about a minute). It's safe to re-run.

### Linux / macOS

```bash
# Debian/Ubuntu only, if venv support is missing:
#   sudo apt install python3.12 python3.12-venv
bash scripts/setup-dev.sh            # --recreate to rebuild .venv, --python python3.13 to choose

source .venv/bin/activate
streamlit run streamlit_app.py       # http://localhost:8501
```

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1   # -Recreate to rebuild

.venv\Scripts\activate
streamlit run streamlit_app.py
```

If activation fails with *"running scripts is disabled on this system"*, allow local
scripts once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or skip activation
and call `.venv\Scripts\streamlit run streamlit_app.py` directly.

### Manual setup (any OS)

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                 # then set SECRET_KEY: python -m fxwatch generate-secret

python -m fxwatch run-once           # fetch rates (first run backfills history)
streamlit run streamlit_app.py       # http://localhost:8501
```

Locally everything defaults to SQLite (`data/fxwatch.db`) and the **console** mail backend,
which prints emails to the log. The New alert page also shows the confirmation link, so you
can test the whole flow without real email. Copy `.env.example` to `.env` to change settings.

Full stack with Postgres and a local inbox ([Mailpit](https://mailpit.axllent.org)):

```bash
docker compose up --build            # app :8501, mailbox :8025
```

## Deploying (free)

Streamlit Community Cloud (UI) + GitHub Actions (worker) + Neon (Postgres) + Gmail SMTP.
Step-by-step: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

## CLI

```
python -m fxwatch run-once                 one full worker pass (what cron runs)
python -m fxwatch serve                    run the worker forever (Docker/VPS)
python -m fxwatch fetch [--source ecb]     fetch latest rates
python -m fxwatch backfill --days 3650     load history
python -m fxwatch evaluate | deliver       run a single stage
python -m fxwatch send-test-email you@x    check SMTP settings
python -m fxwatch check-config             validate production settings
python -m fxwatch generate-secret          make a SECRET_KEY
```

## Development

```bash
pytest                    # SQLite; set TEST_DATABASE_URL to also test on Postgres
ruff check . && ruff format --check .
mypy
```

## Roadmap

- **Phase 2:** retail bank rates (FNB first) as a source, %-change rules, weekly digest
  emails, sparklines in emails.
- **Phase 3:** Telegram/webhook notifications, more banks, a public read-only API.

## License

MIT. Rates data remains subject to each publisher's terms; see the Data sources page.
Flag artwork is [Twemoji](https://github.com/jdecked/twemoji) (CC-BY 4.0), bundled as a
font from [country-flag-emoji-polyfill](https://github.com/talkjs/country-flag-emoji-polyfill)
(MIT) so flags also display on Windows.
