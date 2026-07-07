"""
fetch_data.py

Pulls holder + transaction data for the $ANSEM token from Helius and turns it
into the tables the dashboard needs:

    holders.csv   -> wallet, first_seen_date, balance, prior_activity_proxy
    daily.csv     -> date, new_holders, cumulative_holders
    retention.csv -> cohort_date, day_offset, pct_retained

Run:
    export HELIUS_API_KEY="your-key-here"
    python fetch_data.py

If HELIUS_API_KEY is not set, this script will refuse to run against the live
API and tell you to use mock_data.py instead (used by the dashboard for demos).
"""

import os
import sys
import time
import datetime as dt
from collections import defaultdict

import requests
import pandas as pd

MINT = "9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump"
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY")
BASE_URL = "https://api.helius.xyz/v0"
RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# How many prior transactions counts as "new to crypto" for the proxy metric
NEW_TO_CRYPTO_TX_THRESHOLD = 5
# How far back to look at transaction history
LOOKBACK_DAYS = 30


def _require_key():
    if not HELIUS_API_KEY:
        sys.exit(
            "HELIUS_API_KEY is not set.\n"
            "Get a free key at https://helius.dev, then:\n"
            "    export HELIUS_API_KEY=your-key-here\n"
            "Or, to just try the dashboard without live data, run app.py directly —\n"
            "it will fall back to generated mock data automatically."
        )


def get_current_token_accounts(mint: str) -> pd.DataFrame:
    """
    Uses Helius's getTokenAccounts RPC method to pull every current holder
    of the mint, with pagination.
    """
    _require_key()
    accounts = []
    cursor = None

    while True:
        body = {
            "jsonrpc": "2.0",
            "id": "ansem-dashboard",
            "method": "getTokenAccounts",
            "params": {
                "mint": mint,
                "limit": 1000,
            },
        }
        if cursor:
            body["params"]["cursor"] = cursor

        resp = requests.post(RPC_URL, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("result", {})
        page = data.get("token_accounts", [])
        if not page:
            break

        accounts.extend(page)
        cursor = data.get("cursor")
        if not cursor:
            break
        time.sleep(0.2)  # be polite to the rate limit

    rows = []
    for acc in accounts:
        rows.append(
            {
                "wallet": acc.get("owner"),
                "balance": float(acc.get("amount", 0)),
            }
        )
    return pd.DataFrame(rows).drop_duplicates(subset="wallet")


def get_wallet_signature_count(wallet: str) -> int:
    """
    Rough proxy for 'prior Solana activity' — counts signatures for the
    wallet. Helius/RPC caps a single getSignaturesForAddress call at 1000;
    for a proxy metric that's plenty (we just need a low vs. high signal).
    """
    body = {
        "jsonrpc": "2.0",
        "id": "sig-count",
        "method": "getSignaturesForAddress",
        "params": [wallet, {"limit": 1000}],
    }
    resp = requests.post(RPC_URL, json=body, timeout=30)
    resp.raise_for_status()
    result = resp.json().get("result", [])
    return len(result)


def get_mint_transfer_history(mint: str, days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """
    Pulls recent enhanced transaction history for the mint via Helius's
    /addresses/{address}/transactions endpoint, and extracts the first time
    each wallet shows up interacting with the mint (their first_seen_date).
    """
    _require_key()
    url = f"{BASE_URL}/addresses/{mint}/transactions"
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)

    first_seen = {}
    before = None

    while True:
        params = {"api-key": HELIUS_API_KEY, "limit": 100}
        if before:
            params["before"] = before

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        stop = False
        for txn in batch:
            ts = dt.datetime.utcfromtimestamp(txn.get("timestamp", 0))
            if ts < cutoff:
                stop = True
                continue

            for transfer in txn.get("tokenTransfers", []):
                if transfer.get("mint") != mint:
                    continue
                wallet = transfer.get("toUserAccount")
                if not wallet:
                    continue
                date_str = ts.date().isoformat()
                if wallet not in first_seen or date_str < first_seen[wallet]:
                    first_seen[wallet] = date_str

        before = batch[-1].get("signature")
        if stop or len(batch) < 100:
            break
        time.sleep(0.2)

    return pd.DataFrame(
        [{"wallet": w, "first_seen_date": d} for w, d in first_seen.items()]
    )


def build_holders_table() -> pd.DataFrame:
    holders = get_current_token_accounts(MINT)
    history = get_mint_transfer_history(MINT)

    df = holders.merge(history, on="wallet", how="left")
    # Wallets with no transfer-in event in the lookback window are assumed
    # to have joined earlier than our window — mark unknown.
    df["first_seen_date"] = df["first_seen_date"].fillna("pre-window")

    # Prior-activity proxy — only computed for wallets we can date within
    # the lookback window (querying every wallet is expensive/rate-limited).
    proxies = []
    for wallet in df["wallet"]:
        try:
            sig_count = get_wallet_signature_count(wallet)
        except requests.RequestException:
            sig_count = None
        proxies.append(sig_count)
        time.sleep(0.05)

    df["prior_tx_count"] = proxies
    df["new_to_crypto_proxy"] = df["prior_tx_count"].apply(
        lambda c: (c is not None) and (c < NEW_TO_CRYPTO_TX_THRESHOLD)
    )

    return df


def build_daily_table(holders_df: pd.DataFrame) -> pd.DataFrame:
    dated = holders_df[holders_df["first_seen_date"] != "pre-window"].copy()
    daily = (
        dated.groupby("first_seen_date")
        .size()
        .reset_index(name="new_holders")
        .rename(columns={"first_seen_date": "date"})
        .sort_values("date")
    )
    daily["cumulative_holders"] = daily["new_holders"].cumsum()
    return daily


def build_retention_table(holders_df: pd.DataFrame, offsets=(1, 7, 30)) -> pd.DataFrame:
    """
    NOTE: true retention requires balance snapshots over time, which this
    single-pull script doesn't have. This produces a placeholder structure —
    for real cohort retention, snapshot build_holders_table() daily and diff
    balances across snapshots (see README).
    """
    rows = []
    for cohort_date, group in holders_df[
        holders_df["first_seen_date"] != "pre-window"
    ].groupby("first_seen_date"):
        still_holding = (group["balance"] > 0).mean() * 100
        for offset in offsets:
            rows.append(
                {
                    "cohort_date": cohort_date,
                    "day_offset": offset,
                    "pct_retained": still_holding,  # placeholder until snapshots exist
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print("Fetching current holders + transfer history from Helius...")
    holders_df = build_holders_table()
    holders_df.to_csv("holders.csv", index=False)
    print(f"Saved {len(holders_df)} holders to holders.csv")

    daily_df = build_daily_table(holders_df)
    daily_df.to_csv("daily.csv", index=False)
    print(f"Saved {len(daily_df)} daily rows to daily.csv")

    retention_df = build_retention_table(holders_df)
    retention_df.to_csv("retention.csv", index=False)
    print(f"Saved {len(retention_df)} retention rows to retention.csv")
