"""
mock_data.py

Generates realistic-looking sample data so the dashboard is fully demoable
before you've wired up a live Helius key. Shapes match what fetch_data.py
produces, so swapping real data in later is a drop-in replacement.
"""

import datetime as dt
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)


def generate_daily(days: int = 45, start_holders: int = 200) -> pd.DataFrame:
    dates = [
        (dt.date.today() - dt.timedelta(days=days - i)).isoformat()
        for i in range(days)
    ]
    # simulate a growth curve with some viral spikes
    base = RNG.integers(20, 80, size=days).astype(float)
    spike_days = RNG.choice(days, size=4, replace=False)
    base[spike_days] *= RNG.uniform(3, 6, size=4)
    new_holders = base.astype(int)

    cumulative = start_holders + np.cumsum(new_holders)

    return pd.DataFrame(
        {"date": dates, "new_holders": new_holders, "cumulative_holders": cumulative}
    )


def generate_holders(daily_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    wallet_id = 0
    for _, row in daily_df.iterrows():
        for _ in range(int(row["new_holders"])):
            wallet_id += 1
            prior_tx = int(RNG.exponential(scale=15))
            rows.append(
                {
                    "wallet": f"Wallet{wallet_id:06d}...",
                    "first_seen_date": row["date"],
                    "balance": max(0, RNG.normal(5000, 4000)),
                    "prior_tx_count": prior_tx,
                    "new_to_crypto_proxy": prior_tx < 5,
                }
            )
    return pd.DataFrame(rows)


def generate_retention(holders_df: pd.DataFrame, offsets=(1, 7, 30)) -> pd.DataFrame:
    rows = []
    for cohort_date, group in holders_df.groupby("first_seen_date"):
        n = len(group)
        for offset in offsets:
            # retention decays with offset, plus noise; floors around 35-55%
            decay = np.clip(
                1 - (offset / 45) - RNG.uniform(-0.05, 0.05), 0.35, 0.98
            )
            rows.append(
                {
                    "cohort_date": cohort_date,
                    "day_offset": offset,
                    "pct_retained": round(decay * 100, 1),
                    "cohort_size": n,
                }
            )
    return pd.DataFrame(rows)


def generate_funnel(holders_df: pd.DataFrame) -> dict:
    total_wallets = len(holders_df)
    holders = int(total_wallets * RNG.uniform(0.75, 0.85))
    repeat_traders = int(holders * RNG.uniform(0.25, 0.4))
    return {
        "First-time buyers": total_wallets,
        "Still holding": holders,
        "Repeat traders": repeat_traders,
    }


def load_all():
    daily_df = generate_daily()
    holders_df = generate_holders(daily_df)
    retention_df = generate_retention(holders_df)
    funnel = generate_funnel(holders_df)
    return daily_df, holders_df, retention_df, funnel
