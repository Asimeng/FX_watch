# Architecture

## Processes

| Process | Runs where | Does |
|---|---|---|
| **UI** (`streamlit_app.py`) | Streamlit Cloud / container | Reads rates; creates and manages alerts; sends confirmation and management-link emails immediately |
| **Worker** (`python -m fxwatch run-once`) | GitHub Actions cron / `serve` loop | Fetches sources, evaluates alerts, delivers queued email, housekeeping |

They share nothing but the database, so either can be scaled, restarted or moved
independently.

## A worker pass

1. **Migrate** the schema if needed (Alembic, idempotent).
2. **Fetch** each source in priority order. A source with no stored history is backfilled
   first: up to 10 years, or as far back as the source goes. Each source runs in its own
   transaction and its own `try`, so one failing publisher never blocks the others. Results
   go to `fetch_runs` and `source_status`.
3. **Store** observations with `INSERT … ON CONFLICT DO NOTHING` on
   `(source_id, rate_date, currency)`, so re-fetching is free.
4. **Evaluate** each active alert:
   - expire it, or queue an expiry reminder 7 days ahead;
   - price the pair from the best fresh source (or the user's chosen one);
   - **cross-check** against the median of the other sources and hold the alert if they
     disagree by more than `CROSS_CHECK_TOLERANCE_PCT`;
   - apply the rule (`fxwatch/domain/rules.py`), update its state, and queue an email in
     the **same transaction**.
5. **Deliver** pending outbox rows, committing after each send, retrying up to 5 attempts.
   Bodies are wiped after delivery so live links don't linger in the database.
6. **Housekeeping:** drop unconfirmed alerts after 7 days, subscribers without alerts,
   old rate-limit events, old outbox rows and old fetch runs.

## Data model

- `rate_observations`: one row per (source, date, currency); `value` is units of the
  currency per 1 unit of the source's base, stored as an exact decimal string.
- `subscribers`: email, `verified_at`, `token_version` (bumping it revokes all links).
- `alerts`: rule (`condition`, `threshold`, `mode`, `cooldown_hours`,
  `rearm_margin_pct`, `source_preference`), state (`armed`, `last_rate`,
  `last_triggered_at`, `trigger_count`, `hold_reason`) and lifecycle (`status`,
  `expires_at`).
- `notifications`: the outbox; `dedupe_key` is unique.
- `source_status`, `fetch_runs`: observability.
- `rate_limit_events`: keyed by an HMAC of email/IP, never the raw values.

## Identity without accounts

- **Confirmation link:** `itsdangerous` signature over the alert id, expires in 48 h.
- **Management link:** signature over `(subscriber_id, token_version)`, no expiry.
  "Replace my link" increments the version.
- Nothing secret is stored: links are verified with `SECRET_KEY`.
- "Email me my link" responds identically whether or not the address is known.

## Alert semantics

| Rule | Fires when | After firing |
|---|---|---|
| above / below | rate ≥ / ≤ threshold while armed | one-time: done. Recurring: disarmed until the rate retreats 0.5% past the threshold, then re-armed; a minimum cooldown applies between emails |
| crosses | rate moves from one side to the other between two evaluations | stays armed; cooldown applies |

## Precision & freshness

- Rates are `Decimal` end to end (sources are parsed with `parse_float=Decimal`).
- Bank of Canada series with fewer than 3 significant digits (IDR, VND) are discarded
  because inverting them adds ~1% error.
- Each source has a `max_age_days`. Older observations are not shown as current and never
  fire alerts.
