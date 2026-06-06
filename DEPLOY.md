# Deploying SedarWatchlist to Render (free tier, no credit card)

End result: a public URL like `https://sedarwatchlist-web.onrender.com` that runs the app in any browser, plus a scheduled job that polls SEDAR+ twice a day and emails you when new filings appear.

Total time: ~15 minutes. Everything below is free.

---

## Accounts you need

1. **GitHub** — you already have it
2. **Supabase** — database
3. **Render** — hosting
4. **Resend** *(optional)* — email notifications

All four are free, none require a credit card.

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

## Step 4 — GitHub Actions: schedule the twice-daily refresh

The repo already contains `.github/workflows/refresh-filings.yml`, which fires at 12:00 UTC and 19:00 UTC (= 09:00 and 16:00 in GMT-3).

1. GitHub → your `canadian-microcaps` repo → **Settings → Secrets and variables → Actions → New repository secret**
2. Add two secrets:
   - `REFRESH_API_URL` → your backend URL, e.g. `https://sedarwatchlist-api.onrender.com`
   - `REFRESH_SECRET` → the same long random string you set on Render
3. **Actions tab → Refresh SEDAR+ filings → Run workflow** (manual trigger) to test it. Watch the job log — should end with a JSON response like `{"companies_checked":N,"new_filings":M,"email_sent":true|false}`.

From now on it'll fire twice a day automatically.

---

## Step 5 — (Optional) Tighten CORS

1. Copy the frontend URL (e.g. `https://sedarwatchlist-web.onrender.com`)
2. `sedarwatchlist-api` → **Environment** → set `CORS_ORIGINS` to that URL (no trailing slash) → **Save Changes**

---

## Step 6 — (Optional) Email notifications via Resend

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
| SEDAR search works | `https://sedarwatchlist-api.onrender.com/api/sedar/search?q=shopify` | array of matches |
| Filings feed works | `https://sedarwatchlist-api.onrender.com/api/filings` | `[]` until refresh runs |
| Refresh job (manual) | GitHub → Actions → Run workflow | Job completes with summary JSON |
| Frontend | `https://sedarwatchlist-web.onrender.com` | UI loads, search returns SEDAR+ hits |

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
| `/api/sedar/search` returns `[]` for known names | SEDAR+ may have changed their internal endpoints — paste the Render logs and I'll patch `backend/app/services/sedar_plus.py` |
| Refresh job returns `new_filings: 0` forever | Same as above — the filings endpoint in `sedar_plus.py` may need adjustment |
| `companies_checked: 0` | None of your watchlist entries have a `sedar_profile_id` (you added them via the manual fallback). Re-add via SEDAR+ search to enable polling. |
| Email never arrives | Check spam; verify `RESEND_API_KEY` and `NOTIFY_EMAIL` in Render env; check Resend's dashboard for delivery logs |
| Generic 500 on any endpoint | Render logs always have the stack trace |

Paste any error message back to me and I'll debug it.
