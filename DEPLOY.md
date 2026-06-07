# Deploying SedarWatchlist to Render (free tier, no credit card)

End result: a public URL like `https://sedarwatchlist-web.onrender.com` that runs the app in any browser, plus a scheduled job that polls SEDAR+ twice a day and emails you when new filings appear.

Total time: ~15 minutes. Everything below is free.

## Architecture (why it's split this way)

The filings pipeline runs in **GitHub Actions** twice a day, hitting two sources per company:

- **TMX Money** (free, no quota) — for any ticker on TSX / TSXV / NEO, we grab the press-release feed directly from `money.tmx.com`. No anti-bot, no auth.
- **SEDAR+ via ScraperAPI** (free tier — 1,000 credits/month) — SEDAR+ is behind Imperva, which hard-blocks cloud IPs even via Playwright. ScraperAPI proxies our requests through residential IPs and handles Imperva. We use this for SEDAR-only filings and for CSE (`.CN`) listings that TMX doesn't cover.

Render runs the UI, stores data, sends the email, and tells the scraper which companies to visit. The scraper POSTs filings back to `/api/filings/ingest`.

---

## Accounts you need

1. **GitHub** — you already have it
2. **Supabase** — database
3. **Render** — hosting
4. **Finnhub** — powers the company search bar
5. **Resend** *(optional)* — email notifications

All five are free, none require a credit card.

---

## Step 1 — Supabase: create the database

1. https://supabase.com → sign in with GitHub → **New project**
2. Wait for it to provision (~2 min)
3. **SQL Editor → New query** → paste the full contents of `supabase/schema.sql` → **Run**
   - Safe to re-run if you've already created the tables — the schema uses `if not exists` and `alter ... if not exists` throughout
4. **Project Settings → API Keys** → enable **Legacy API keys** if needed → copy:
   - **Project URL** (`https://<id>.supabase.co`)
   - **anon legacy JWT key** (starts with `eyJ…`)

> The newer `sb_publishable_…` keys are not yet supported by `supabase-py`. Use the legacy JWT one.

---

## Step 2 — Render: deploy with the Blueprint

1. https://render.com → **Get Started** → sign in with GitHub → grant access to `canadian-microcaps`
2. Dashboard → **New + → Blueprint** → pick `canadian-microcaps`
3. Render detects `render.yaml` and shows two services. You'll be prompted for env vars marked `sync: false`:

   For **sedarwatchlist-api**:
   - `SUPABASE_URL` → the Project URL from Step 1
   - `SUPABASE_KEY` → the legacy JWT anon key
   - `CORS_ORIGINS` → `*` for now (tighten in Step 5)
   - `REFRESH_SECRET` → **generate a long random string** (run `openssl rand -hex 32` in a terminal, or just bash any 40+ random characters). Save this — you'll paste it into GitHub in Step 4.
   - `RESEND_API_KEY` → leave blank for now (Step 6)
   - `NOTIFY_EMAIL` → your email address

   For **sedarwatchlist-web**:
   - `VITE_API_BASE_URL` → leave blank for now (Step 3)

4. Click **Apply**. The API build takes ~3 min; static site ~1 min.

---

## Step 3 — Wire the frontend to the backend

Once `sedarwatchlist-api` is **Live**:

1. Click into it, copy its URL (e.g. `https://sedarwatchlist-api.onrender.com`)
2. `sedarwatchlist-web` → **Environment** → set `VITE_API_BASE_URL` to that URL → **Save Changes**
3. **Manual Deploy → Deploy latest commit** so the frontend rebuilds with the URL baked in

Open the frontend URL — you should see the search bar.

---

## Step 4 — GitHub Actions: schedule the twice-daily scraper

The repo contains `.github/workflows/refresh-filings.yml`, which fires at 12:00 UTC and 19:00 UTC (= 09:00 and 16:00 in GMT-3).

1. GitHub → your `canadian-microcaps` repo → **Settings → Secrets and variables → Actions → New repository secret**
2. Add three secrets:
   - `REFRESH_API_URL` → your backend URL, e.g. `https://sedarwatchlist-api.onrender.com`
   - `REFRESH_SECRET` → the same long random string you set on Render
   - `SCRAPERAPI_KEY` → your ScraperAPI key (Step 5 below). Skip this for now if you only watch TSX/TSXV — TMX covers those.
3. **Actions tab → Scrape filings (TMX + SEDAR+) → Run workflow** (manual trigger) to test it. The job takes ~3–5 minutes (mostly Chromium download).
4. Look at the log for `Backend response: {'received': N, 'inserted': M, 'email_sent': true|false}`.
5. Every job uploads the rendered HTML of each fetched page as an artifact named `scrape-html`. If a company shows zero rows when you know it should have news, download the artifact and send me the relevant HTML file.

From now on it'll fire twice a day automatically.

## Step 5 — Install the self-hosted runner on your macOS laptop

SEDAR+ is fronted by Imperva, which blocks every cloud datacenter IP (GitHub's cloud runners, Render, etc.) but lets through real consumer ISPs. So the scrape job runs from your home Mac.

1. GitHub → your repo → **Settings → Actions → Runners → New self-hosted runner**
2. Pick **macOS** + your Mac's architecture (ARM64 for Apple Silicon, x64 for Intel)
3. Open Terminal and copy/paste the commands GitHub shows you. They look like:
   ```bash
   mkdir actions-runner && cd actions-runner
   curl -o actions-runner-osx-arm64.tar.gz -L https://github.com/actions/runner/releases/download/...
   tar xzf actions-runner-osx-arm64.tar.gz
   ./config.sh --url https://github.com/<you>/canadian-microcaps --token <token>
   ```
   - Accept all the defaults during `./config.sh` (runner name, labels, work folder).
4. Install as a background service so it auto-starts on login:
   ```bash
   ./svc.sh install
   ./svc.sh start
   ```
5. Verify in GitHub: **Settings → Actions → Runners** should now list your Mac as **Idle** with a green dot.

**Caveat:** the runner only picks up jobs while your Mac is awake and connected to the internet. If the cron fires at 9 AM and your Mac is asleep, the job queues. When you next open your laptop, the runner reconnects and the queued job runs immediately — you'd get the email a few minutes later.

### Test it

GitHub → **Actions → Scrape filings (TMX + SEDAR+) → Run workflow**.

First run will be ~3-5 min (downloads Chromium into your Mac's Library). Subsequent runs are ~30 sec to 2 min depending on watchlist size. The job log lives on GitHub as always.

---

## Step 5b — (Optional) Tighten CORS

1. Copy the frontend URL (e.g. `https://sedarwatchlist-web.onrender.com`)
2. `sedarwatchlist-api` → **Environment** → set `CORS_ORIGINS` to that URL (no trailing slash) → **Save Changes**

---

## Step 6 — Finnhub API key (for the search bar)

The add-company search uses Finnhub. Yahoo Finance rate-limits Render's IP, so we use Finnhub instead — 60 calls/minute on the free tier, plenty for typeahead.

1. https://finnhub.io → **Get free API key** → sign up with email
2. Copy the API key from your dashboard (looks like `cugxyz1abc234defg5h6i`)
3. Render → `sedarwatchlist-api` → **Environment** → set `FINNHUB_API_KEY` to that value → **Save Changes**
4. The service auto-restarts in ~30 sec

Until this is set, the search bar will return an empty list for every query.

## Step 7 — (Optional) Email notifications via Resend

Skip this if you only want the in-app filings feed.

1. https://resend.com → sign up (GitHub login works)
2. **API Keys → Create API key** → copy the value (starts with `re_…`)
3. Render → `sedarwatchlist-api` → **Environment** → set `RESEND_API_KEY` to that value → **Save Changes**
4. (Optional) verify a custom sending domain in Resend and update `RESEND_FROM` to use it. Until you do, emails come from `onboarding@resend.dev` (Resend's shared test address — works out of the box, may end up in spam).

The next time the refresh job runs and finds new filings, you'll get an email at `NOTIFY_EMAIL`.

---

## Sanity checks

| What | URL | Expected |
|---|---|---|
| Backend alive | `https://sedarwatchlist-api.onrender.com/health` | `{"status":"ok"}` |
| Watchlist works | `https://sedarwatchlist-api.onrender.com/api/watchlist` | `[]` or your rows |
| Filings feed works | `https://sedarwatchlist-api.onrender.com/api/filings` | `[]` until first scrape lands |
| Scraper job (manual) | GitHub → Actions → Scrape SEDAR+ filings → Run workflow | Job completes with `Backend response: {...}` |
| Frontend | `https://sedarwatchlist-web.onrender.com` | UI loads, add-company form visible |

## Adding a company

Type the company name (or ticker) in the search bar. Matches come from Yahoo Finance, filtered to Canadian listings (TSX / TSXV / CSE / NEO). Click one → it's on your watchlist.

The first scraper run after adding will:

1. Search SEDAR+ for the company name (via Playwright + real Chromium),
2. Pick the best match, cache its profile URL on your watchlist row,
3. Open that page and ingest any filings it finds.

Until the first run completes the card shows "SEDAR+ lookup pending"; afterward it shows a direct link to the SEDAR+ profile.

---

## Free-tier gotchas

- **Cold starts:** Render's free web service spins down after 15 min idle. First request after that takes ~30 s.
- **Cron + cold start:** the GitHub Actions step uses `--max-time 180` to ride out the cold start.
- **Supabase:** 500 MB DB + 50K MAUs free. Fine for this.
- **Resend:** 100 emails/day, 3,000/month free.

---

## If something breaks

| Symptom | Likely cause |
|---|---|
| Scraper run says "Got 0 scrape target(s)" | None of your watchlist entries have a SEDAR+ profile URL. Add one via the form. |
| Scraper run says "parsed 0 filings" for a company you know has filings | Imperva served us a challenge page or the DOM differs from what the parser expects. Download the `sedar-html` artifact from the Actions run and send it to me — the parser in `scripts/scrape_sedar.py` is a one-file fix. |
| Email never arrives | Check spam; verify `RESEND_API_KEY` and `NOTIFY_EMAIL` in Render env; Resend dashboard shows delivery logs. |
| `/api/filings/ingest` returns 401 | `REFRESH_SECRET` value on Render doesn't match GitHub secret. |
| Generic 500 on any endpoint | Render logs always have the stack trace. |

Paste any error message back to me and I'll debug it.
