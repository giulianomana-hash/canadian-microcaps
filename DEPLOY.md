# Deploying SedarWatchlist to Render (free tier, no credit card)

End result: a public URL like `https://sedarwatchlist-web.onrender.com` that runs the app in any browser. Everything below is free.

You will need ~10 minutes and four accounts (all free, no credit card):

1. GitHub (you already have this)
2. Supabase (database)
3. Render (hosting)

---

## Step 1 — Supabase: create the database (5 min)

1. Go to https://supabase.com and sign in with GitHub.
2. Click **New project**. Pick any name and region. Generate a strong DB password (you don't need to remember it for this project).
3. Wait ~2 minutes for the project to provision.
4. In the left sidebar click **SQL Editor → New query**.
5. Open `supabase/schema.sql` from this repo, copy everything, paste it into the editor, click **Run**. You should see "Success. No rows returned."
6. Now go to **Project Settings (gear icon) → Data API**. Copy two values into a scratchpad:
   - **Project URL** — looks like `https://abcdwxyz.supabase.co`
   - **Project API Keys → publishable / anon key** — long string

Keep those two values handy. You'll paste them into Render in Step 3.

---

## Step 2 — Render: connect your GitHub (2 min)

1. Go to https://render.com and click **Get Started** → sign in with GitHub.
2. When prompted, **install Render on the `canadian-microcaps` repository** (you can grant access to just this one repo, not all of them).
3. You should land on your Render dashboard.

---

## Step 3 — Render: deploy with the Blueprint (3 min)

The repo already contains `render.yaml`, which tells Render to spin up **both** services at once.

1. In the Render dashboard, click **New + → Blueprint**.
2. Select the `canadian-microcaps` repository.
3. Render will detect `render.yaml` and show two services: `sedarwatchlist-api` and `sedarwatchlist-web`.
4. It will prompt you for the env vars marked `sync: false`. Fill them in:

   For **sedarwatchlist-api**:
   - `SUPABASE_URL` → the Project URL you copied
   - `SUPABASE_KEY` → the publishable/anon key you copied
   - `CORS_ORIGINS` → leave as `*` for now (we'll tighten it in Step 5)

   For **sedarwatchlist-web**:
   - `VITE_API_BASE_URL` → leave blank for now (we'll fill it in Step 4)

5. Click **Apply**. Render starts building both services. The API build takes ~3 min; the static site takes ~1 min.

---

## Step 4 — Wire the frontend to the backend (1 min)

Once the API service shows status "Live":

1. Click into the `sedarwatchlist-api` service and copy its URL from the top of the page (e.g. `https://sedarwatchlist-api.onrender.com`).
2. Go to `sedarwatchlist-web` → **Environment** → set `VITE_API_BASE_URL` to that URL → **Save Changes**.
3. Click **Manual Deploy → Deploy latest commit** so the frontend rebuilds with the new URL baked in.

---

## Step 5 — (Optional) tighten CORS

Once the frontend is live:

1. Copy the frontend URL (e.g. `https://sedarwatchlist-web.onrender.com`).
2. In `sedarwatchlist-api` → **Environment** → change `CORS_ORIGINS` from `*` to that URL → **Save Changes**.

The API will restart automatically.

---

## You're done

Open the frontend URL in your browser. The page loads, you can add a company in the search bar, and refreshing keeps it on the list (because it's stored in Supabase).

**Verify it's actually saving:** in Supabase → **Table Editor → watchlist**, you'll see the rows you added.

---

## Things to know about the free tier

- **Backend cold starts:** Render's free web service spins down after 15 minutes of no traffic. The first request after that takes ~30 seconds to wake up — the page will show "Loading watchlist…" while it boots. Subsequent requests are instant.
- **Static frontend:** always on, no cold starts.
- **Supabase:** 500MB database + 50K monthly active users on the free tier. Plenty for this.
- **Custom domain:** Render supports custom domains on the free tier if you want `watchlist.yourdomain.com` later.

---

## If something goes wrong

- **Build fails on the API** → check the build logs in Render. Most common cause is a typo in `requirements.txt` (shouldn't happen — it's pinned).
- **Frontend loads but shows "Failed to fetch"** → `VITE_API_BASE_URL` is wrong or wasn't rebuilt after change. Re-do Step 4.
- **API returns 500 on `/api/watchlist`** → `SUPABASE_URL` or `SUPABASE_KEY` is wrong, or the SQL schema wasn't run. Check Render's logs for the exact error.
- **CORS error in browser console** → `CORS_ORIGINS` on the API doesn't match the frontend URL. Set it to `*` to test, then narrow it down.

Paste any error message back to me and I'll debug it.
