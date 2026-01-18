from __future__ import annotations

import html as py_html
import os
import sys
import datetime as dt
from typing import Tuple, Dict, List

import altair as alt
import pandas as pd
import streamlit as st
from dateutil import parser as dtparser
from dateutil import tz

from core.odds_api import fetch_nba_spreads_window
from core.schedule_espn import fetch_games_for_date
from core.standings import get_record, get_win_pct
from core.standings_espn import fetch_team_standings_maps
from core.team_meta import get_logo_url

import core.watchability as watch


def inject_base_css() -> None:
    st.markdown(
        """
<style>
/* Hide Streamlit multipage/sidebar nav (cleaner + more professional). */
section[data-testid="stSidebar"] {display: none;}
div[data-testid="stSidebarNav"] {display: none;}
div[data-testid="collapsedControl"] {display: none;}

.block-container {padding-top: 1rem; padding-bottom: 1rem;}
.menu-row {display:flex; align-items:center; gap:12px; padding:8px 4px; border-bottom: 1px solid rgba(49,51,63,0.12);}
.menu-awi {width:110px;}
.menu-awi .score {font-size: 24px; font-weight: 700; line-height: 1.05;}
.menu-awi .label {font-size: 14px; color: rgba(49,51,63,0.7); line-height: 1.2;}
.live-badge {color: #d62728; font-weight: 700; font-size: 13px; margin-top: 2px;}
.live-time {color: #d62728; font-size: 13px; line-height: 1.1; margin-top: 2px;}
.menu-teams {flex: 1; display:flex; align-items:center; gap:10px; min-width: 240px;}
.menu-teams .team {display:flex; align-items:center; gap:8px; min-width: 0;}
.menu-teams img {width: 28px; height: 28px;}
.menu-teams .name {font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.menu-teams .at {opacity: 0.6; padding: 0 2px;}
.menu-matchup {flex: 1; min-width: 0; display:flex; flex-direction: column; gap: 2px;}
.menu-matchup .teamline {display:flex; align-items:center; gap:8px; min-width: 0;}
.menu-matchup img {width: 28px; height: 28px;}
.menu-matchup .name {font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.menu-matchup .record {font-size: 12px; font-weight: 400; color: rgba(49,51,63,0.65); white-space: nowrap;}
.menu-meta {width: 240px; font-size: 13px; color: rgba(49,51,63,0.75); line-height: 1.3;}
.menu-meta div {margin: 1px 0;}
</style>
""",
        unsafe_allow_html=True,
    )


def inject_minimal_chrome_css() -> None:
    st.markdown(
        """
<style>
header, footer {visibility: hidden;}
div[data-testid="stToolbar"] {visibility: hidden; height: 0px;}
section[data-testid="stSidebar"] {display: none;}
.block-container {padding-top: 0.25rem; padding-bottom: 0.25rem;}
</style>
""",
        unsafe_allow_html=True,
    )


def inject_autorefresh(ms: int = 3_600_000) -> None:
    from streamlit.components.v1 import html

    html(
        f"""
        <script>
            setTimeout(function() {{
                window.location.reload();
            }}, {int(ms)});
        </script>
        """,
        height=0,
    )


@st.cache_data(ttl=60 * 10)  # 10 min
def load_games() -> list:
    return fetch_nba_spreads_window(days_ahead=2)


@st.cache_data(ttl=60 * 60)  # 1 hour
def load_standings():
    return fetch_team_standings_maps()


def _parse_score(x):
    try:
        if x is None:
            return None
        return int(float(x))
    except Exception:
        return None


@st.cache_data(ttl=60 * 10)  # 10 min (live scores)
def load_espn_game_map(local_dates_iso: tuple[str, ...]) -> dict[tuple[str, str, str], dict]:
    """
    Map (date_iso, home_team_lower, away_team_lower) -> dict with:
      - state ('pre'/'in'/'post')
      - home_score (int|None)
      - away_score (int|None)
      - time_remaining (str|None) e.g. '5:32 Q3'
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
            time_remaining = g.get("time_remaining")
            if home and away and state:
                out[(iso, home, away)] = {
                    "state": state,
                    "home_score": home_score,
                    "away_score": away_score,
                    "time_remaining": time_remaining,
                }
    return out


def _fmt_m_d(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def build_dashboard_frames() -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict[str, str]]:
    games = load_games()
    winpct_map, record_map = load_standings()
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
        w_home_rec, l_home_rec = get_record(g.home_team, record_map)
        w_away_rec, l_away_rec = get_record(g.away_team, record_map)
        home_record = "—" if (w_home_rec is None or l_home_rec is None) else f"{w_home_rec}-{l_home_rec}"
        away_record = "—" if (w_away_rec is None or l_away_rec is None) else f"{w_away_rec}-{l_away_rec}"

        abs_spread = None if g.home_spread is None else abs(float(g.home_spread))
        w = watch.compute_watchability(w_home, w_away, abs_spread)

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

        rows.append(
            {
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
                "Record (away)": away_record,
                "Record (home)": home_record,
                "Team quality": w.team_quality,
                "Closeness": w.closeness,
                "Uavg": w.uavg,
                "aWI": w.awi,
                "Region": w.label,
                "Spread source": g.spread_source,
            }
        )

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
    date_to_label = {
        d.isoformat(): f"{day} {_fmt_m_d(d)}"
        for d, day in df_dates.itertuples(index=False, name=None)
    }

    game_map = load_espn_game_map(tuple(date_options))

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
        df["Time remaining"] = df.apply(lambda r: _lookup_game(r, "time_remaining"), axis=1)
    else:
        df["Status"] = "pre"
        df["Away score"] = None
        df["Home score"] = None
        df["Time remaining"] = None

    df["Is live"] = df["Status"] == "in"

    def _tip_display(r) -> str:
        if not bool(r["Is live"]):
            return str(r["Tip short"])
        away = r.get("Away score")
        home = r.get("Home score")
        tr = r.get("Time remaining")
        if away is None or home is None:
            return f"🚨 LIVE{(' ' + str(tr)) if tr else ''}"
        return f"🚨 {int(away)}-{int(home)}{(' ' + str(tr)) if tr else ''}"

    df["Tip display"] = df.apply(_tip_display, axis=1)

    # Remove finished games from both views.
    df = df[df["Status"] != "post"].copy()

    return df, df_dates, date_options, date_to_label


def render_chart(
    df: pd.DataFrame,
    date_options: list[str],
    date_to_label: dict[str, str],
    show_day_selector: bool,
    selected_date: str | None,
) -> None:
    QUALITY_FLOOR = getattr(watch, "QUALITY_FLOOR", 0.1)
    CLOSENESS_FLOOR = getattr(watch, "CLOSENESS_FLOOR", 0.1)

    df_plot = df.copy()
    if date_options:
        if show_day_selector:
            selected = st.segmented_control(
                "Day",
                options=date_options,
                format_func=lambda x: date_to_label.get(x, x),
                default=date_options[0],
            )
        else:
            selected = selected_date if selected_date in date_options else date_options[0]
        df_plot = df[df["Local date"].astype(str) == selected].copy()

    region_order = ["Amazing game", "Great game", "Good game", "Ok game", "Bad game"]
    region_colors = {
        "Amazing game": "#1f77b4",
        "Great game": "#2ca02c",
        "Good game": "#ff7f0e",
        "Ok game": "#9467bd",
        "Bad game": "#7f7f7f",
    }

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

    regions_other = (
        alt.Chart(regions_df)
        .transform_filter(alt.datum.Region != "Bad game")
        .mark_rect(opacity=0.10)
        .encode(
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
            tooltip=[],
        )
    )

    regions_bad = (
        alt.Chart(regions_df)
        .transform_filter(alt.datum.Region == "Bad game")
        .mark_rect(opacity=0.15, color=region_colors["Bad game"])
        .encode(
            x=alt.X("q:Q", scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]), axis=None),
            x2="q2:Q",
            y=alt.Y("c:Q", scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]), axis=None),
            y2="c2:Q",
            tooltip=[],
        )
    )

    regions = regions_other + regions_bad

    axes = alt.Chart(df_plot).mark_point(opacity=0).encode(
        x=alt.X(
            "Team quality:Q",
            scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]),
            axis=alt.Axis(
                title="Team Quality",
                format=".2f",
                titleColor="rgba(0,0,0,0.9)",
                titleFontSize=18,
                titleFontWeight="bold",
                titlePadding=28,
                labelColor="rgba(0,0,0,0.65)",
                labelFontSize=12,
            ),
        ),
        y=alt.Y(
            "Closeness:Q",
            scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]),
            axis=alt.Axis(
                title="Competitiveness",
                format=".2f",
                titleColor="rgba(0,0,0,0.9)",
                titleFontSize=18,
                titleFontWeight="bold",
                titlePadding=34,
                labelColor="rgba(0,0,0,0.65)",
                labelFontSize=12,
            ),
        ),
        tooltip=[],
    )

    region_labels_df = pd.DataFrame(
        [
            {"label": "Amazing", "x": 0.93, "y": 0.93},
            {"label": "Great game", "x": 0.82, "y": 0.82},
            {"label": "Good game", "x": 0.60, "y": 0.60},
            {"label": "Ok game", "x": 0.4, "y": 0.4},
            {"label": "Bad game", "x": 0.2, "y": 0.2},
        ]
    )
    region_text = alt.Chart(region_labels_df).mark_text(
        fontSize=28,
        fontWeight=700,
        opacity=0.15,
        color="rgba(49,51,63,0.75)",
    ).encode(
        x=alt.X("x:Q", scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]), axis=None),
        y=alt.Y("y:Q", scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]), axis=None),
        text=alt.Text("label:N"),
        tooltip=[],
    )

    x_axis_label_df = pd.DataFrame(
        [{"text": "Team Quality", "x": 0.55, "y": CLOSENESS_FLOOR + 0.05}]
    )
    x_axis_label_text = alt.Chart(x_axis_label_df).mark_text(
        dy=78,
        fontSize=22,
        fontWeight=800,
        opacity=0.95,
        color="rgba(0,0,0,0.9)",
    ).encode(
        x=alt.X("x:Q", scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]), axis=None),
        y=alt.Y("y:Q", scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]), axis=None),
        text=alt.Text("text:N"),
        tooltip=[],
    )

    y_axis_label_df = pd.DataFrame(
        [{"text": "Competitiveness", "x": QUALITY_FLOOR - 0.07, "y": 0.65}]
    )
    y_axis_label_text = alt.Chart(y_axis_label_df).mark_text(
        dx=-74,
        fontSize=22,
        fontWeight=800,
        opacity=0.95,
        color="rgba(0,0,0,0.9)",
        angle=270,
    ).encode(
        x=alt.X("x:Q", scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]), axis=None),
        y=alt.Y("y:Q", scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]), axis=None),
        text=alt.Text("text:N"),
        tooltip=[],
    )

    game_tooltip = [
        alt.Tooltip("Matchup:N"),
        alt.Tooltip("aWI:Q", title="WI", format=".1f"),
        alt.Tooltip("Region:N"),
        alt.Tooltip("Tip (PT):N"),
        alt.Tooltip("Home spread:Q"),
        alt.Tooltip("Record (away):N"),
        alt.Tooltip("Record (home):N"),
    ]

    circles = alt.Chart(df_plot).mark_circle(size=800, opacity=0.10).encode(
        x=alt.X("Team quality:Q", scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]), axis=None),
        y=alt.Y("Closeness:Q", scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]), axis=None),
        color=alt.Color(
            "Region:N",
            sort=region_order,
            scale=alt.Scale(domain=region_order, range=[region_colors[r] for r in region_order]),
            legend=alt.Legend(title=None),
        ),
        tooltip=game_tooltip,
    )

    hit_targets = alt.Chart(df_plot).mark_circle(size=4200, opacity=0.001).encode(
        x=alt.X("Team quality:Q", scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]), axis=None),
        y=alt.Y("Closeness:Q", scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]), axis=None),
        tooltip=game_tooltip,
    )

    dx = 0.03
    away_points = df_plot.assign(_x=(df_plot["Team quality"] - dx).clip(0, 1), _logo=df_plot["Away logo"])
    home_points = df_plot.assign(_x=(df_plot["Team quality"] + dx).clip(0, 1), _logo=df_plot["Home logo"])
    images_df = pd.concat(
        [
            away_points[
                [
                    "Matchup",
                    "Tip short",
                    "Tip (PT)",
                    "Home spread",
                    "Record (away)",
                    "Record (home)",
                    "aWI",
                    "Region",
                    "Closeness",
                    "Team quality",
                    "_x",
                    "_logo",
                ]
            ].assign(_side="away"),
            home_points[
                [
                    "Matchup",
                    "Tip short",
                    "Tip (PT)",
                    "Home spread",
                    "Record (away)",
                    "Record (home)",
                    "aWI",
                    "Region",
                    "Closeness",
                    "Team quality",
                    "_x",
                    "_logo",
                ]
            ].assign(_side="home"),
        ],
        ignore_index=True,
    )
    images_df = images_df[images_df["_logo"].astype(bool)]

    images = alt.Chart(images_df).mark_image(width=40, height=40).encode(
        x=alt.X("_x:Q", axis=None),
        y=alt.Y("Closeness:Q", axis=None),
        url=alt.Url("_logo:N"),
        tooltip=game_tooltip,
    )

    tips = alt.Chart(df_plot).mark_text(dy=32, fontSize=11, color="rgba(49,51,63,0.75)").encode(
        x=alt.X("Team quality:Q", axis=None),
        y=alt.Y("Closeness:Q", axis=None),
        text=alt.Text("Tip display:N"),
        tooltip=game_tooltip,
    )

    chart = (
        axes
        + regions
        + region_text
        + x_axis_label_text
        + y_axis_label_text
        + circles
        + hit_targets
        + images
        + tips
    ).resolve_scale(x="shared", y="shared").properties(height=560)
    st.altair_chart(chart, use_container_width=True)


def _render_menu_row(r) -> str:
    awi_score = int(round(float(r["aWI"])))
    label = py_html.escape(str(r["Region"]))

    live_badge = ""
    if bool(r.get("Is live", False)):
        away_s = r.get("Away score")
        home_s = r.get("Home score")
        tr = r.get("Time remaining")
        tr_line = (
            f"<div class='live-time'>🚨 LIVE {py_html.escape(str(tr))}</div>"
            if tr
            else "<div class='live-time'>🚨 LIVE</div>"
        )
        if away_s is not None and home_s is not None:
            live_badge = f"{tr_line}<div class='live-badge'>{int(away_s)} - {int(home_s)}</div>"
        else:
            live_badge = f"{tr_line}"

    away = py_html.escape(str(r["Away team"]))
    home = py_html.escape(str(r["Home team"]))
    tip = py_html.escape(str(r["Tip (PT)"]))
    spread = r["Home spread"]
    spread_str = "?" if spread is None else f"{float(spread):g}"
    record_away = py_html.escape(str(r.get("Record (away)", "—")))
    record_home = py_html.escape(str(r.get("Record (home)", "—")))
    away_logo = py_html.escape(str(r["Away logo"]))
    home_logo = py_html.escape(str(r["Home logo"]))
    away_img = f"<img src='{away_logo}'/>" if away_logo else ""
    home_img = f"<img src='{home_logo}'/>" if home_logo else ""

    return f"""
<div class="menu-row">
  <div class="menu-awi">
    <div class="score">{awi_score} WI</div>
    <div class="label">{label}</div>
    {live_badge}
  </div>
  <div class="menu-matchup">
    <div class="teamline">
      {away_img}
      <div class="name">{away}</div>
      <div class="record">{record_away}</div>
    </div>
    <div class="teamline">
      {home_img}
      <div class="name">{home}</div>
      <div class="record">{record_home}</div>
    </div>
  </div>
  <div class="menu-meta">
    <div>Tip: {tip}</div>
    <div>Spread: {spread_str}</div>
  </div>
</div>
"""


def render_table(df: pd.DataFrame, df_dates: pd.DataFrame, date_options: list[str]) -> None:
    if date_options:
        for local_date, day_name in df_dates.itertuples(index=False, name=None):
            st.markdown(f"**{py_html.escape(str(day_name))}**")
            st.divider()
            day_df = df[df["Local date"] == local_date].sort_values("aWI", ascending=False)
            for _, row in day_df.iterrows():
                st.markdown(_render_menu_row(row), unsafe_allow_html=True)
            st.markdown("<div style='height: 100px;'></div>", unsafe_allow_html=True)
    else:
        for _, row in df.iterrows():
            st.markdown(_render_menu_row(row), unsafe_allow_html=True)


def render_full_dashboard(title: str, caption: str) -> None:
    inject_base_css()
    inject_autorefresh()

    st.title(title)
    st.caption(caption)

    df, df_dates, date_options, date_to_label = build_dashboard_frames()

    left, right = st.columns([1.05, 1.0], gap="large")
    with left:
        render_chart(
            df=df,
            date_options=date_options,
            date_to_label=date_to_label,
            show_day_selector=True,
            selected_date=None,
        )
    with right:
        render_table(df=df, df_dates=df_dates, date_options=date_options)


def render_chart_page() -> None:
    inject_base_css()
    df, _, date_options, date_to_label = build_dashboard_frames()
    selected = st.query_params.get("day")
    render_chart(
        df=df,
        date_options=date_options,
        date_to_label=date_to_label,
        show_day_selector=False,
        selected_date=selected,
    )


def render_table_page() -> None:
    inject_base_css()
    df, df_dates, date_options, _ = build_dashboard_frames()
    render_table(df=df, df_dates=df_dates, date_options=date_options)
