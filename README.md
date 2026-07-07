# $ANSEM Onboarding Dashboard

A mobile-friendly Streamlit dashboard tracking new holder growth, retention,
and onboarding funnel for the $ANSEM Solana token
(`9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump`) — with live holder counts
and real, growing retention curves built from daily snapshots.

## How the "live" part actually works

Two different things are live, on two different clocks:

1. **Total holder count** — fetched fresh from Helius on every page load
   (cached 5 min so it stays fast). This is a real number the moment someone
   opens the dashboard.
2. **Retention curves (1/7/30 day)** — these need to know who was still
   holding *N days after* they first showed up, which only exists if you've
   been recording daily snapshots. A GitHub Action runs `snapshot.py` once a
   day, forever, and commits the growing history back to the repo. The
   longer it runs, the more real retention data you have — a 30-day
   retention number literally can't exist until 30 days after launch.

## First-time setup (do this once)

### 1. Get a Helius API key
Free at [helius.dev](https://helius.dev). No card required for the free tier.

### 2. Push this folder to a new GitHub repo
```bash
cd ansem_dashboard
git init
git add .
git commit -m "Initial ANSEM dashboard"
git remote add origin https://github.com/YOUR_USERNAME/ansem-dashboard.git
git push -u origin main
```

### 3. Add your Helius key as a GitHub secret (for the daily snapshot job)
In your GitHub repo: **Settings → Secrets and variables → Actions → New
repository secret**
- Name: `HELIUS_API_KEY`
- Value: your key

The workflow in `.github/workflows/daily_snapshot.yml` is already set up to
use it — it runs `snapshot.py` every day at 09:00 UTC and commits the
updated CSVs back to the repo automatically. You can also trigger it
manually anytime from the **Actions** tab (useful to kick off the first
snapshot right now instead of waiting for tomorrow).

### 4. Deploy the dashboard on Streamlit Community Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub.
2. "New app" → pick your repo → main file path `app.py`.
3. Under **Advanced settings → Secrets**, add:
   ```
   HELIUS_API_KEY = "your-key-here"
   ```
4. Deploy. You'll get a public URL like `https://your-app.streamlit.app` —
   that's what you send to Ansem.

Streamlit Cloud auto-redeploys whenever you push to the repo, and since the
GitHub Action commits new snapshot data daily, the deployed app's data
updates right along with it.

## Day-to-day after setup

You don't have to do anything — the GitHub Action runs on its own schedule
and commits fresh data daily. The retention curve fills in more history
(and becomes more meaningful) the longer it runs. If you want a snapshot
right now rather than waiting for the next scheduled run, go to your repo's
**Actions** tab → "Daily ANSEM Snapshot" → **Run workflow**.

## What's in each file

- `app.py` — the dashboard (live holder count, growth chart, retention
  curve, funnel, plain-language explainer, CSV export).
- `helius_client.py` — shared low-level Helius API calls.
- `snapshot.py` — the daily job: pulls current holders, records a dated
  snapshot, updates `holders_meta.csv` (first-seen dates + new-to-crypto
  proxy), and rebuilds `daily.csv` / `retention.csv` from accumulated history.
- `.github/workflows/daily_snapshot.yml` — schedules `snapshot.py` to run
  daily and commits the results.
- `fetch_data.py` — a standalone manual one-off pull (handy for testing
  locally without waiting on the scheduled job).
- `mock_data.py` — generated sample data so the dashboard renders even with
  no key / before any snapshots exist.
- `requirements.txt` — dependencies.

## Things worth knowing

- **Retention takes time to become real.** Day 1, you'll only have "day 1"
  retention for cohorts from day 0. The 30-day column fills in after a month
  of the Action running. That's inherent to what retention means, not a bug.
- **Rate limits:** the free Helius tier is generous but not infinite — the
  live holder count is cached 5 minutes, and the daily job only computes the
  expensive "prior activity" signature-count check once per wallet, ever
  (not on every snapshot).
- **If the Action fails** (e.g. rate limit, API hiccup), check the Actions
  tab logs — nothing else breaks; the dashboard just keeps showing the last
  successful snapshot until the next run succeeds.
