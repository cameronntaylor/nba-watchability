from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import streamlit as st
from dateutil import tz
from dateutil import parser as dtparser
import datetime as dt
from core.odds_api import fetch_nba_spreads_today
from core.standings import get_win_pct
from core.standings_espn import fetch_team_win_pct_map
from core.metric import MetricParams, compute_cis
from core.team_meta import get_logo_url

from streamlit.components.v1 import html

st.set_page_config(page_title="NBA Games-of-the-Day (CIS)", layout="wide")

# --- Auto-refresh the page every hour (3600000 ms) ---
html(
    """
    <script>
        setTimeout(function() {
            window.location.reload();
        }, 3600000);
    </script>
    """,
    height=0,
)

st.title("NBA Games-of-the-Day Dashboard")
st.caption("Ranks today’s NBA games by **Competitive Interest Score (CIS)** using spreads + team win%.")

# --- Controls ---
with st.sidebar:
    st.header("Metric controls")

    variant = st.selectbox(
        "Quality function f(w1, w2)",
        ["avg", "product", "max", "avg_minus_gap"],
        index=0,
        help=(
            "avg: average win%\n"
            "product: rewards two strong teams\n"
            "max: star/elite-team effect\n"
            "avg_minus_gap: parity bonus via penalty on win% gap"
        ),
    )

    a = st.slider("a (closeness weight)", min_value=0.0, max_value=5.0, value=2.0, step=0.1)
    b = st.slider("b (quality weight)", min_value=0.0, max_value=5.0, value=2.0, step=0.1)

    c = 0.0
    if variant == "avg_minus_gap":
        c = st.slider("c (penalty on |w1-w2|)", min_value=0.0, max_value=3.0, value=0.5, step=0.1)

    spread_cap = st.slider("Spread cap for normalization", min_value=8.0, max_value=25.0, value=15.0, step=1.0)

    st.divider()
    st.write("**Interpretation**")
    st.write("- Higher CIS = more watchable")
    st.write("- Closer spreads boost score")
    st.write("- Better teams (win%) boost score")

params = MetricParams(a=a, b=b, c=c, spread_cap=spread_cap)

@st.cache_data(ttl=60 * 60)  # 1 hour
def load_games():
    return fetch_nba_spreads_today()

@st.cache_data(ttl=60 * 60)  # 1 hour
def load_standings():
    return fetch_team_win_pct_map()

games = load_games()
winpct_map = load_standings()
if not winpct_map:
    st.warning(
        "Could not load standings from ESPN; win% will default to 0.5. "
        "Try refreshing, or check your network connectivity."
    )

local_tz = tz.gettz("America/Los_Angeles")

rows = []
for g in games:
    w_home = get_win_pct(g.home_team, winpct_map, default=0.5)
    w_away = get_win_pct(g.away_team, winpct_map, default=0.5)

    cis, spread_term, fval, abs_spread = compute_cis(
        home_spread=g.home_spread,
        w_home=w_home,
        w_away=w_away,
        params=params,
        variant=variant,  # type: ignore
    )

    # Commence time to local
    if g.commence_time_utc:
        dt_utc = dtparser.isoparse(g.commence_time_utc)
        dt_local = dt_utc.astimezone(local_tz)
        tip_local = dt_local.strftime("%a %I:%M %p")
    else:
        tip_local = "Unknown"

    rows.append({
        "Tip (PT)": tip_local,
        "Matchup": f"{g.away_team} @ {g.home_team}",
        "Home spread": g.home_spread,
        "|spread|": abs_spread,
        "Win% (away)": round(w_away, 3),
        "Win% (home)": round(w_home, 3),
        "Spread closeness term": round(spread_term, 3),
        "f(w1,w2)": round(fval, 3),
        "CIS": round(cis, 3),
        "Spread source": g.spread_source,
    })

df = pd.DataFrame(rows)
if df.empty:
    st.warning("No games returned from Odds API. (Off day? API issue? Check your key/limits.)")
    st.stop()

df = df.sort_values("CIS", ascending=False).reset_index(drop=True)

# --- Main table ---
st.subheader("Today’s games ranked by CIS")
for _, row in df.iterrows():
    away, home = row["Matchup"].split(" @ ")
    away_logo = get_logo_url(away)
    home_logo = get_logo_url(home)

    with st.expander(f"{away} @ {home} — CIS {row['CIS']}"):
        cols = st.columns([1, 4, 1, 4, 3])

        if away_logo:
            cols[0].image(away_logo, width=40)
        cols[1].markdown(f"**{away}**")

        if home_logo:
            cols[2].image(home_logo, width=40)
        cols[3].markdown(f"**{home}**")

        cols[4].write(
            f"""
            Tip: {row['Tip (PT)']}  
            Spread: {row['Home spread']}  
            Win%: {row['Win% (away)']} vs {row['Win% (home)']}  
            """
        )

# --- Top 3 cards ---
st.subheader("Top games (quick explainers)")
topn = df.head(3).to_dict(orient="records")
cols = st.columns(3)

for i, rec in enumerate(topn):
    with cols[i]:
        away, home = rec["Matchup"].split(" @ ")

        away_logo = get_logo_url(away)
        home_logo = get_logo_url(home)

        # Team row
        team_cols = st.columns([1, 3, 1, 3])
        if away_logo:
            team_cols[0].image(away_logo, width=50)
        team_cols[1].markdown(f"**{away}**")

        if home_logo:
            team_cols[2].image(home_logo, width=50)
        team_cols[3].markdown(f"**{home}**")

        st.metric("CIS", rec["CIS"])
        st.caption(f"Tip: {rec['Tip (PT)']}")
        st.write(f"Spread: {rec['Home spread']}")
        st.write(
            f"Win% — away {rec['Win% (away)']}, home {rec['Win% (home)']}"
        )

st.divider()
last_updated = dt.datetime.now(
    tz=tz.gettz("America/Los_Angeles")
).strftime("%Y-%m-%d %I:%M %p PT")
st.caption(f"Last updated: {last_updated}")