from __future__ import annotations

import html as py_html
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import streamlit as st
import altair as alt
from dateutil import tz
from dateutil import parser as dtparser
import datetime as dt
from core.odds_api import fetch_nba_spreads_window
from core.schedule_espn import fetch_games_for_date
from core.standings import get_win_pct
from core.standings_espn import fetch_team_win_pct_map
from core.team_meta import get_logo_url
import core.watchability as watch

from streamlit.components.v1 import html

st.set_page_config(
    page_title="NBA Watchability (aWI)",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
.block-container {padding-top: 1rem; padding-bottom: 1rem;}
.menu-row {display:flex; align-items:center; gap:12px; padding:8px 4px; border-bottom: 1px solid rgba(49,51,63,0.12);}
.menu-awi {width:110px;}
.menu-awi .score {font-size: 24px; font-weight: 700; line-height: 1.05;}
.menu-awi .label {font-size: 12px; color: rgba(49,51,63,0.7); line-height: 1.2;}
.live-badge {color: #d62728; font-weight: 700; margin-left: 6px;}
.menu-teams {flex: 1; display:flex; align-items:center; gap:10px; min-width: 280px;}
.menu-teams .team {display:flex; align-items:center; gap:8px; min-width: 0;}
.menu-teams img {width: 28px; height: 28px;}
.menu-teams .name {font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.menu-teams .at {opacity: 0.6; padding: 0 2px;}
.menu-meta {width: 240px; font-size: 12px; color: rgba(49,51,63,0.75); line-height: 1.25;}
.menu-meta div {margin: 1px 0;}
</style>
""",
    unsafe_allow_html=True,
)

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

st.title(
    "What to watch? NBA Watchability Today"
)

@st.cache_data(ttl=60 * 10)  # 10 min
def load_games():
    return fetch_nba_spreads_window(days_ahead=2)

@st.cache_data(ttl=60 * 60)  # 1 hour
def load_standings():
    return fetch_team_win_pct_map()

def _parse_score(x):
    try:
        if x is None:
            return None
        return int(float(x))
    except Exception:
        return None


@st.cache_data(ttl=60)  # 1 min (live scores)
def load_espn_game_map(local_dates_iso: tuple[str, ...]) -> dict[tuple[str, str, str], dict]:
    """
    Map (date_iso, home_team_lower, away_team_lower) -> dict with:
      - state ('pre'/'in'/'post')
      - home_score (int|None)
      - away_score (int|None)
    """
    out: dict[tuple[str, str, str], dict] = {}
    for iso in local_dates_iso:
        try:
            y, m, d = (int(x) for x in iso.split("-"))
            day = dt.date(y, m, d)
            games = fetch_games_for_date(day)
        except Exception:
            continue
        for g in games:
            home = str(g.get("home_team", "")).lower().strip()
            away = str(g.get("away_team", "")).lower().strip()
            state = str(g.get("state", ""))
            home_score = _parse_score(g.get("home_score"))
            away_score = _parse_score(g.get("away_score"))
            if home and away and state:
                out[(iso, home, away)] = {
                    "state": state,
                    "home_score": home_score,
                    "away_score": away_score,
                }
    return out

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

    abs_spread = None if g.home_spread is None else abs(float(g.home_spread))
    w = watch.compute_watchability(w_home, w_away, abs_spread)

    # Commence time to local
    if g.commence_time_utc:
        dt_utc = dtparser.isoparse(g.commence_time_utc)
        dt_local = dt_utc.astimezone(local_tz)
        local_date = dt_local.date()
        day_name = dt_local.strftime("%A")
        tip_local = dt_local.strftime("%a %I:%M %p")
        tip_short = dt_local.strftime("%a %I%p").replace(" 0", " ")
    else:
        local_date = None
        day_name = "Unknown"
        tip_local = "Unknown"
        tip_short = "?"

    rows.append({
        "Tip (PT)": tip_local,
        "Tip short": tip_short,
        "Local date": local_date,
        "Day": day_name,
        "Matchup": f"{g.away_team} @ {g.home_team}",
        "Away team": g.away_team,
        "Home team": g.home_team,
        "Away logo": get_logo_url(g.away_team) or "",
        "Home logo": get_logo_url(g.home_team) or "",
        "Home spread": g.home_spread,
        "|spread|": abs_spread,
        "Win% (away)": round(w_away, 3),
        "Win% (home)": round(w_home, 3),
        "Team quality": w.team_quality,
        "Closeness": w.closeness,
        "Uavg": w.uavg,
        "aWI": w.awi,
        "Region": w.label,
        "Spread source": g.spread_source,
    })

df = pd.DataFrame(rows)
if df.empty:
    st.warning("No games returned from Odds API. (Off day? API issue? Check your key/limits.)")
    st.stop()

df = df.sort_values("aWI", ascending=False).reset_index(drop=True)

df_dates = (
    df.dropna(subset=["Local date"])
    .sort_values("Local date")
    .loc[:, ["Local date", "Day"]]
    .drop_duplicates()
)
date_options = [d.isoformat() for d in df_dates["Local date"].tolist()]
def _fmt_m_d(d: dt.date) -> str:
    return f"{d.month}/{d.day}"

date_to_label = {
    d.isoformat(): f"{day} {_fmt_m_d(d)}"
    for d, day in df_dates.itertuples(index=False, name=None)
}

game_map = load_espn_game_map(tuple(date_options))
# Annotate live games (ESPN 'in' state).
if date_options:
    def _lookup_game(r, key: str):
        rec = game_map.get(
            (str(r["Local date"]), str(r["Home team"]).lower().strip(), str(r["Away team"]).lower().strip())
        )
        if not rec:
            return None
        return rec.get(key)

    df["Status"] = df.apply(lambda r: _lookup_game(r, "state") or "pre", axis=1)
    df["Away score"] = df.apply(lambda r: _lookup_game(r, "away_score"), axis=1)
    df["Home score"] = df.apply(lambda r: _lookup_game(r, "home_score"), axis=1)
else:
    df["Status"] = "pre"
    df["Away score"] = None
    df["Home score"] = None
df["Is live"] = df["Status"] == "in"
def _tip_display(r) -> str:
    if not bool(r["Is live"]):
        return str(r["Tip short"])
    away = r.get("Away score")
    home = r.get("Home score")
    if away is None or home is None:
        return "🚨 LIVE"
    return f"🚨 {int(away)}-{int(home)}"

df["Tip display"] = df.apply(_tip_display, axis=1)

left, right = st.columns([1.05, 1.0], gap="large")

with left:
    st.write("")

    QUALITY_FLOOR = getattr(watch, "QUALITY_FLOOR", 0.1)
    CLOSENESS_FLOOR = getattr(watch, "CLOSENESS_FLOOR", 0.1)

    if date_options:
        selected_date = st.segmented_control(
            "Day",
            options=date_options,
            format_func=lambda x: date_to_label.get(x, x),
            default=date_options[0],
        )
        df_plot = df[df["Local date"].astype(str) == selected_date].copy()
    else:
        df_plot = df.copy()

    region_order = ["Amazing game", "Great game", "Good game", "Ok game", "Crap game"]
    region_colors = {
        "Amazing game": "#1f77b4",
        "Great game": "#2ca02c",
        "Good game": "#ff7f0e",
        "Ok game": "#9467bd",
        "Crap game": "#7f7f7f",
    }

    # Background regions (by aWI buckets) on a quality/closeness grid.
    step = 0.02
    q_vals = [QUALITY_FLOOR + i * step for i in range(int((1.0 - QUALITY_FLOOR) / step) + 1)]
    c_vals = [CLOSENESS_FLOOR + i * step for i in range(int((1.0 - CLOSENESS_FLOOR) / step) + 1)]
    cells = []
    for q in q_vals[:-1]:
        for c in c_vals[:-1]:
            q_mid = q + step / 2
            c_mid = c + step / 2
            a = watch.awi(q_mid, c_mid)
            cells.append(
                {
                    "q": q,
                    "q2": min(1.0, q + step),
                    "c": c,
                    "c2": min(1.0, c + step),
                    "Region": watch.awi_label(a),
                }
            )
    regions_df = pd.DataFrame(cells)

    regions = alt.Chart(regions_df).mark_rect(opacity=0.10).encode(
        x=alt.X("q:Q", scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]), axis=None),
        x2="q2:Q",
        y=alt.Y("c:Q", scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]), axis=None),
        y2="c2:Q",
        color=alt.Color(
            "Region:N",
            sort=region_order,
            scale=alt.Scale(domain=region_order, range=[region_colors[r] for r in region_order]),
            legend=None,
        ),
    )

    x_axis = alt.X(
        "Team quality:Q",
        scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]),
        axis=alt.Axis(title="Team Quality", format=".2f"),
    )
    y_axis = alt.Y(
        "Closeness:Q",
        scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]),
        axis=alt.Axis(title="Closeness", format=".2f"),
    )

    circles = alt.Chart(df_plot).mark_circle(size=800, opacity=0.10).encode(
        x=x_axis,
        y=y_axis,
        color=alt.Color(
            "Region:N",
            sort=region_order,
            scale=alt.Scale(domain=region_order, range=[region_colors[r] for r in region_order]),
            legend=alt.Legend(title=None),
        ),
        tooltip=[
            alt.Tooltip("Matchup:N"),
            alt.Tooltip("aWI:Q", format=".1f"),
            alt.Tooltip("Region:N"),
            alt.Tooltip("Tip (PT):N"),
            alt.Tooltip("Home spread:Q"),
            alt.Tooltip("Win% (away):Q"),
            alt.Tooltip("Win% (home):Q"),
        ],
    )

    dx = 0.03
    away_points = df_plot.assign(_x=(df_plot["Team quality"] - dx).clip(0, 1), _logo=df_plot["Away logo"])
    home_points = df_plot.assign(_x=(df_plot["Team quality"] + dx).clip(0, 1), _logo=df_plot["Home logo"])
    images_df = pd.concat(
        [
            away_points[["Matchup", "Tip short", "Tip (PT)", "Home spread", "Win% (away)", "Win% (home)", "aWI", "Region", "Closeness", "Team quality", "_x", "_logo"]].assign(_side="away"),
            home_points[["Matchup", "Tip short", "Tip (PT)", "Home spread", "Win% (away)", "Win% (home)", "aWI", "Region", "Closeness", "Team quality", "_x", "_logo"]].assign(_side="home"),
        ],
        ignore_index=True,
    )
    images_df = images_df[images_df["_logo"].astype(bool)]

    images = alt.Chart(images_df).mark_image(width=40, height=40).encode(
        x=alt.X("_x:Q", axis=None),
        y=alt.Y("Closeness:Q", axis=None),
        url=alt.Url("_logo:N"),
        tooltip=[
            alt.Tooltip("Matchup:N"),
            alt.Tooltip("aWI:Q", format=".1f"),
            alt.Tooltip("Region:N"),
            alt.Tooltip("Tip (PT):N"),
        ],
    )

    tips = alt.Chart(df_plot).mark_text(dy=32, fontSize=11, color="rgba(49,51,63,0.75)").encode(
        x=alt.X("Team quality:Q", axis=None),
        y=alt.Y("Closeness:Q", axis=None),
        text=alt.Text("Tip display:N"),
    )

    chart = (regions + circles + images + tips).resolve_scale(x="shared", y="shared").properties(height=560)
    st.altair_chart(chart, use_container_width=True)

with right:
    st.write("")

    def _render_menu_row(r) -> str:
        awi_score = int(round(float(r["aWI"])))
        label = py_html.escape(str(r["Region"]))
        live_badge = ""
        if bool(r.get("Is live", False)):
            away_s = r.get("Away score")
            home_s = r.get("Home score")
            if away_s is not None and home_s is not None:
                live_badge = f"<div class='live-badge'>🚨 LIVE {int(away_s)} - {int(home_s)}</div>"
            else:
                live_badge = "<div class='live-badge'>🚨 LIVE</div>"
        away = py_html.escape(str(r["Away team"]))
        home = py_html.escape(str(r["Home team"]))
        tip = py_html.escape(str(r["Tip (PT)"]))
        spread = r["Home spread"]
        spread_str = "?" if spread is None else f"{float(spread):g}"
        win_away = float(r["Win% (away)"])
        win_home = float(r["Win% (home)"])
        away_logo = py_html.escape(str(r["Away logo"]))
        home_logo = py_html.escape(str(r["Home logo"]))
        away_img = f"<img src='{away_logo}'/>" if away_logo else ""
        home_img = f"<img src='{home_logo}'/>" if home_logo else ""

        return f"""
<div class="menu-row">
  <div class="menu-awi">
    <div class="score">{awi_score} aWI</div>
    <div class="label">{label}</div>
    {live_badge}
  </div>
  <div class="menu-teams">
    <div class="team">
      {away_img}
      <div class="name">{away}</div>
    </div>
    <div class="at">@</div>
    <div class="team">
      {home_img}
      <div class="name">{home}</div>
    </div>
  </div>
  <div class="menu-meta">
    <div>Tip: {tip}</div>
    <div>Spread: {spread_str}</div>
    <div>Win%: {win_away:.3f} vs {win_home:.3f}</div>
  </div>
</div>
"""

    if date_options:
        for local_date, day_name in df_dates.itertuples(index=False, name=None):
            st.markdown(f"**{py_html.escape(str(day_name))}**")
            st.divider()
            day_df = df[df["Local date"] == local_date].sort_values("aWI", ascending=False)
            for _, row in day_df.iterrows():
                st.markdown(_render_menu_row(row), unsafe_allow_html=True)
            st.divider()
    else:
        for _, row in df.iterrows():
            st.markdown(_render_menu_row(row), unsafe_allow_html=True)

st.divider()
last_updated = dt.datetime.now(
    tz=tz.gettz("America/Los_Angeles")
).strftime("%Y-%m-%d %I:%M %p PT")
st.caption(f"Last updated: {last_updated}")
