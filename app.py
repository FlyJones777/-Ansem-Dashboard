"""
app.py — $ANSEM Onboarding Dashboard

Run locally:
    pip install -r requirements.txt
    streamlit run app.py

Deploy free:
    Push this folder to a GitHub repo, then connect it at
    https://share.streamlit.io (Streamlit Community Cloud).
    Add HELIUS_API_KEY as a secret if you want live data (see README.md).
"""

import os
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

import mock_data
import helius_client

MINT = "9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump"
GOAL_HOLDERS = 1_000_000
HAS_KEY = bool(os.environ.get("HELIUS_API_KEY"))

st.set_page_config(
    page_title="$ANSEM Onboarding Dashboard",
    page_icon="🚀",
    layout="wide",
)


# ---------- Data loading ----------

@st.cache_data(ttl=60 * 30)
def load_data():
    """
    Uses the snapshot pipeline's CSVs (daily.csv, holders_meta.csv,
    retention.csv — built by snapshot.py, refreshed daily via GitHub Actions)
    if present, otherwise falls back to generated mock data.
    """
    if all(os.path.exists(f) for f in ("daily.csv", "holders_meta.csv", "retention.csv")):
        daily_df = pd.read_csv("daily.csv")
        meta_df = pd.read_csv("holders_meta.csv")
        retention_df = pd.read_csv("retention.csv")
        funnel = {
            "First-time buyers": len(meta_df),
            "Still holding": int(daily_df["cumulative_holders"].iloc[-1]) if len(daily_df) else 0,
            "Repeat traders": int((meta_df.get("prior_tx_count", 0) > 1).sum()),
        }
        using_live = True
    else:
        daily_df, meta_df, retention_df, funnel = mock_data.load_all()
        using_live = False

    return daily_df, meta_df, retention_df, funnel, using_live


@st.cache_data(ttl=60 * 5)
def get_live_holder_count():
    """
    A truly real-time number (independent of the once-daily snapshot job) —
    queries Helius directly, cached for 5 minutes so page loads stay fast
    and you don't burn through API rate limits.
    """
    if not HAS_KEY:
        return None
    try:
        holders = helius_client.get_current_token_accounts(MINT)
        return len(holders)
    except Exception as e:
        return None


daily_df, holders_df, retention_df, funnel, using_live = load_data()
live_count = get_live_holder_count()


# ---------- Sidebar filters ----------

st.sidebar.title("Filters")
if not using_live:
    st.sidebar.info("Showing **mock data**. Set up `snapshot.py` (see README) for real history.")
elif live_count is None:
    st.sidebar.warning("Showing snapshot history, but no live key found for real-time counts right now.")
else:
    st.sidebar.success("Live holder count + snapshot history connected.")

date_min = pd.to_datetime(daily_df["date"]).min()
date_max = pd.to_datetime(daily_df["date"]).max()

date_range = st.sidebar.date_input(
    "Date range",
    value=(date_min.date(), date_max.date()),
    min_value=date_min.date(),
    max_value=date_max.date(),
)

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = date_min.date(), date_max.date()

mask = (pd.to_datetime(daily_df["date"]).dt.date >= start_date) & (
    pd.to_datetime(daily_df["date"]).dt.date <= end_date
)
filtered_daily = daily_df[mask]

st.sidebar.markdown("---")
st.sidebar.caption(f"Mint: `{MINT[:6]}...{MINT[-4:]}`")
st.sidebar.caption("Data refreshes every 30 min (cached).")


# ---------- Header ----------

st.title("🚀 $ANSEM Onboarding Dashboard")
st.caption("Tracking how new people join, stick around, and become active holders.")


# ---------- KPI cards ----------

total_holders = live_count if live_count is not None else (
    int(daily_df["cumulative_holders"].iloc[-1]) if len(daily_df) else 0
)
new_today = int(daily_df["new_holders"].iloc[-1]) if len(daily_df) else 0
pct_new_to_crypto = (
    round(holders_df["new_to_crypto_proxy"].mean() * 100, 1)
    if "new_to_crypto_proxy" in holders_df.columns and len(holders_df)
    else 0
)
pct_to_goal = round(total_holders / GOAL_HOLDERS * 100, 3)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total holders" + (" (live)" if live_count is not None else ""), f"{total_holders:,}")
k2.metric("New today", f"+{new_today:,}")
k3.metric("New-to-crypto (proxy)", f"{pct_new_to_crypto}%")
k4.metric("Progress to 1M goal", f"{pct_to_goal}%")


# ---------- Growth chart ----------

st.subheader("Holder growth")
st.caption("Daily new holders (bars) and cumulative total (line), with a 1,000,000 holder goal line.")

fig_growth = go.Figure()
fig_growth.add_bar(
    x=filtered_daily["date"], y=filtered_daily["new_holders"], name="New holders/day"
)
fig_growth.add_trace(
    go.Scatter(
        x=filtered_daily["date"],
        y=filtered_daily["cumulative_holders"],
        name="Cumulative holders",
        yaxis="y2",
        mode="lines+markers",
    )
)
fig_growth.update_layout(
    yaxis=dict(title="New holders/day"),
    yaxis2=dict(title="Cumulative holders", overlaying="y", side="right"),
    legend=dict(orientation="h", y=1.1),
    margin=dict(l=10, r=10, t=30, b=10),
    height=380,
)
st.plotly_chart(fig_growth, use_container_width=True)


# ---------- Two-column: retention + funnel ----------

col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Retention curve")
    st.caption("% of each daily cohort still holding after 1 / 7 / 30 days.")
    if len(retention_df):
        ret_summary = (
            retention_df.groupby("day_offset")["pct_retained"].mean().reset_index()
        )
        fig_ret = px.line(
            ret_summary,
            x="day_offset",
            y="pct_retained",
            markers=True,
            labels={"day_offset": "Days after first buy", "pct_retained": "% still holding"},
        )
        fig_ret.update_yaxes(range=[0, 100])
        fig_ret.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=340)
        st.plotly_chart(fig_ret, use_container_width=True)
    else:
        st.info("No retention data yet.")

with col_b:
    st.subheader("Onboarding funnel")
    st.caption("First-time buyers → still holding → repeat traders.")
    funnel_df = pd.DataFrame(
        {"stage": list(funnel.keys()), "count": list(funnel.values())}
    )
    fig_funnel = go.Figure(
        go.Funnel(y=funnel_df["stage"], x=funnel_df["count"], textinfo="value+percent initial")
    )
    fig_funnel.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=340)
    st.plotly_chart(fig_funnel, use_container_width=True)


# ---------- Plain-language explainer ----------

with st.expander("What am I looking at? (plain-language explainer)"):
    st.markdown(
        f"""
- **Total holders**: everyone currently holding any amount of $ANSEM.
- **New today**: how many brand-new wallets showed up in the last day.
- **New-to-crypto (proxy)**: wallets with very little prior Solana activity before
  buying $ANSEM — a rough signal of people who are new to crypto, not just new to this token.
- **Retention curve**: of the people who bought on a given day, what % are still
  holding 1, 7, and 30 days later. A flatter, higher curve means people are sticking around.
- **Onboarding funnel**: shows the drop-off from "bought once" to "still holding"
  to "actively trading again" — this shows how easy it is for new people to join
  $ANSEM and keep going.
        """
    )

st.markdown("---")
st.caption(
    f"Data as of {dt.datetime.now().strftime('%Y-%m-%d %H:%M UTC')}. "
    + ("Live Helius data." if using_live else "Mock/demo data — connect Helius for live numbers.")
)


# ---------- Export ----------

st.sidebar.markdown("---")
st.sidebar.download_button(
    "Download daily data (CSV)",
    data=filtered_daily.to_csv(index=False),
    file_name="ansem_daily_holders.csv",
    mime="text/csv",
)
