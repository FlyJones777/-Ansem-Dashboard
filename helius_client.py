"""
helius_client.py

Low-level Helius API calls shared by fetch_data.py (one-off manual pull)
and snapshot.py (the daily scheduled job that builds retention history).
"""

import os
import time
import datetime as dt

import requests

HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY")
BASE_URL = "https://api.helius.xyz/v0"


def _rpc_url():
    if not HELIUS_API_KEY:
        raise RuntimeError(
            "HELIUS_API_KEY is not set. Get a free key at https://helius.dev "
            "and set it as an environment variable / secret."
        )
    return f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"


def get_current_token_accounts(mint: str) -> list[dict]:
    """
    Returns [{wallet, balance}, ...] for every current holder of the mint,
    using Helius's getTokenAccounts RPC method with pagination.
    """
    accounts = []
    cursor = None

    while True:
        body = {
            "jsonrpc": "2.0",
            "id": "ansem-dashboard",
            "method": "getTokenAccounts",
            "params": {"mint": mint, "limit": 1000},
        }
        if cursor:
            body["params"]["cursor"] = cursor

        resp = requests.post(_rpc_url(), json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("result", {})
        page = data.get("token_accounts", [])
        if not page:
            break

        accounts.extend(page)
        cursor = data.get("cursor")
        if not cursor:
            break
        time.sleep(0.2)

    rows, seen = [], set()
    for acc in accounts:
        wallet = acc.get("owner")
        if not wallet or wallet in seen:
            continue
        seen.add(wallet)
        rows.append({"wallet": wallet, "balance": float(acc.get("amount", 0))})
    return rows


def get_wallet_signature_count(wallet: str) -> int:
    """Proxy for prior Solana activity — signature count, capped at 1000."""
    body = {
        "jsonrpc": "2.0",
        "id": "sig-count",
        "method": "getSignaturesForAddress",
        "params": [wallet, {"limit": 1000}],
    }
    resp = requests.post(_rpc_url(), json=body, timeout=30)
    resp.raise_for_status()
    return len(resp.json().get("result", []))


def get_mint_transfer_history(mint: str, days: int = 30) -> dict:
    """Returns {wallet: first_seen_date_iso} for wallets seen receiving the mint in the lookback window."""
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

    return first_seen
