# Deploying FX Watch for free

| Piece | Service | Free tier notes |
|---|---|---|
| Database | [Neon](https://neon.tech) Postgres | 0.5 GB is ~10× what FX Watch needs |
| Web app | [Streamlit Community Cloud](https://streamlit.io/cloud) | Sleeps when idle; that's fine |
| Worker | GitHub Actions (scheduled) | Unlimited minutes on public repos; ~2,000 min/month private |
| Email | Gmail SMTP | ~500 recipients/day |

Allow about 20 minutes.

## 1. Database (Neon)

1. Create a Neon project and database (e.g. `fxwatch`).
2. Copy the connection string, e.g.
   `postgresql://user:pass@ep-xxx.eu-central-1.aws.neon.tech/fxwatch?sslmode=require`.
   (`postgres://` and `postgresql://` URLs are both accepted.)

The schema is created automatically by the first worker run or app start.

## 2. Gmail app password

1. Turn on [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification)
   for the Gmail account that will send alerts (a dedicated account is recommended).
2. Create an [app password](https://myaccount.google.com/apppasswords). You'll get 16 characters.
3. Optional check from your machine:
   ```bash
   MAIL_BACKEND=smtp SMTP_USERNAME=you@gmail.com SMTP_PASSWORD=xxxx \
     python -m fxwatch send-test-email you@gmail.com
   ```

## 3. Shared secret

```bash
python -m fxwatch generate-secret
```

Use the **same** value for the app and the worker. It signs the confirmation and
management links; changing it later invalidates every link already emailed.

## 4. Streamlit Community Cloud

1. Push this repo to GitHub.
2. *Create app* → pick the repo, branch `main`, main file `streamlit_app.py`.
3. *Advanced settings* → Python **3.12**.
4. *Secrets* → paste `.streamlit/secrets.toml.example` with your values. Set `APP_BASE_URL`
   to the app's final URL (e.g. `https://fxwatch.streamlit.app`, no trailing slash).
5. Deploy. Until the worker has run once, the dashboard asks you to wait for data.

## 5. GitHub Actions worker

1. Repo → *Settings → Secrets and variables → Actions* → add:
   `DATABASE_URL`, `SECRET_KEY`, `APP_BASE_URL`, `SMTP_USERNAME`, `SMTP_PASSWORD`
   (and optionally `MAIL_FROM`).
2. *Actions → Worker → Run workflow* to trigger the first run by hand. The first run
   backfills history (~1 minute); later runs take ~15 seconds.
3. From then on it runs hourly on weekdays, every 6 hours at weekends, and right after the
   ECB publishes.

**About the schedule:** GitHub may start scheduled runs 5-30+ minutes late when its
runners are busy. Official rates change once a day, so this doesn't matter for these
alerts. GitHub also pauses schedules in repos with no activity for 60 days; the workflow's
keep-alive step re-enables itself each run. If a schedule is ever disabled anyway, re-enable
it from the Actions tab.

## 6. Verify

- Create an alert on the app with your email, confirm it, then *Run workflow* again.
  Set a threshold just below the current rate to see it fire.
- *Data sources & status* shows each source's latest rates and recent fetch runs.
- A failed worker run shows as a red ❌ in the Actions tab, and GitHub emails the repo owner.

## Alternative: a single VPS

`docker compose up -d --build` runs Postgres, the app and a long-running worker
(`python -m fxwatch serve`). Replace the Mailpit settings in `docker-compose.yml` with your
SMTP settings and put a reverse proxy with TLS (Caddy, nginx) in front of port 8501.
