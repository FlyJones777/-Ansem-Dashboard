"""
snapshot.py — run this once per day (via GitHub Actions or cron).

Each run:
  1. Pulls current holder balances from Helius.
  2. Updates holders_meta.csv — adds any brand-new wallets with today's date
     as their first_seen_date, and computes their prior-activity proxy ONCE
     (so we're not re-querying signature counts for old wallets every day).
  3. Writes a dated snapshot to snapshots/YYYY-MM-DD.csv with every wallet's
     balance as of today.
  4. Rebuilds daily.csv (new holders per day + cumulative) and retention.csv
     (% of each day's cohort still holding 1/7/30 days later, computed from
     the accumulated snapshots) so app.py can read them directly.

Retention curves only become meaningful once you have >30 days of snapshots.
Before that, the dashboard will show partial/shorter-horizon retention.
"""

import os
import glob
import datetime as dt

import pandas as pd

import helius_client

MINT = "9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump"
NEW_TO_CRYPTO_TX_THRESHOLD = 5
SNAPSHOT_DIR = "snapshots"
HOLDERS_META_PATH = "holders_meta.csv"

RETENTION_OFFSETS = (1, 7, 30)


def load_holders_meta() -> pd.DataFrame:
    if os.path.exists(HOLDERS_META_PATH):
        return pd.read_csv(HOLDERS_META_PATH)
    return pd.DataFrame(
        columns=["wallet", "first_seen_date", "prior_tx_count", "new_to_crypto_proxy"]
    )


def update_holders_meta(current_wallets: set, meta_df: pd.DataFrame, today: str) -> pd.DataFrame:
    known_wallets = set(meta_df["wallet"]) if len(meta_df) else set()
    new_wallets = current_wallets - known_wallets

    new_rows = []
    for wallet in new_wallets:
        try:
            prior_tx = helius_client.get_wallet_signature_count(wallet)
        except Exception:
            prior_tx = None
        new_rows.append(
            {
                "wallet": wallet,
                "first_seen_date": today,
                "prior_tx_count": prior_tx,
                "new_to_crypto_proxy": (prior_tx is not None) and (prior_tx < NEW_TO_CRYPTO_TX_THRESHOLD),
            }
        )

    if new_rows:
        meta_df = pd.concat([meta_df, pd.DataFrame(new_rows)], ignore_index=True)

    return meta_df


def build_daily_table(meta_df: pd.DataFrame) -> pd.DataFrame:
    daily = (
        meta_df.groupby("first_seen_date")
        .size()
        .reset_index(name="new_holders")
        .rename(columns={"first_seen_date": "date"})
        .sort_values("date")
    )
    daily["cumulative_holders"] = daily["new_holders"].cumsum()
    return daily


def build_retention_table(meta_df: pd.DataFrame) -> pd.DataFrame:
    snapshot_files = sorted(glob.glob(f"{SNAPSHOT_DIR}/*.csv"))
    if not snapshot_files:
        return pd.DataFrame(columns=["cohort_date", "day_offset", "pct_retained", "cohort_size"])

    snapshots = {}
    for f in snapshot_files:
        date_str = os.path.basename(f).replace(".csv", "")
        snapshots[date_str] = pd.read_csv(f).set_index("wallet")["balance"]

    rows = []
    for cohort_date, group in meta_df.groupby("first_seen_date"):
        cohort_wallets = set(group["wallet"])
        cohort_size = len(cohort_wallets)
        cohort_dt = dt.date.fromisoformat(cohort_date)

        for offset in RETENTION_OFFSETS:
            target_date = (cohort_dt + dt.timedelta(days=offset)).isoformat()
            if target_date not in snapshots:
                continue  # not enough history yet for this offset
            balances = snapshots[target_date]
            still_holding = sum(
                1 for w in cohort_wallets if w in balances.index and balances[w] > 0
            )
            rows.append(
                {
                    "cohort_date": cohort_date,
                    "day_offset": offset,
                    "pct_retained": round(still_holding / cohort_size * 100, 1) if cohort_size else 0,
                    "cohort_size": cohort_size,
                }
            )

    return pd.DataFrame(rows)


def main():
    today = dt.date.today().isoformat()
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    print(f"[{today}] Fetching current holders from Helius...")
    holders = helius_client.get_current_token_accounts(MINT)
    holders_df = pd.DataFrame(holders)
    print(f"[{today}] {len(holders_df)} current holders.")

    holders_df.to_csv(f"{SNAPSHOT_DIR}/{today}.csv", index=False)
    print(f"[{today}] Snapshot saved to {SNAPSHOT_DIR}/{today}.csv")

    meta_df = load_holders_meta()
    meta_df = update_holders_meta(set(holders_df["wallet"]), meta_df, today)
    meta_df.to_csv(HOLDERS_META_PATH, index=False)
    print(f"[{today}] holders_meta.csv now has {len(meta_df)} tracked wallets.")

    daily_df = build_daily_table(meta_df)
    daily_df.to_csv("daily.csv", index=False)
    print(f"[{today}] daily.csv rebuilt ({len(daily_df)} rows).")

    retention_df = build_retention_table(meta_df)
    retention_df.to_csv("retention.csv", index=False)
    print(f"[{today}] retention.csv rebuilt ({len(retention_df)} rows).")


if __name__ == "__main__":
    main()
