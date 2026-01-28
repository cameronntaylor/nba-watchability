from __future__ import annotations

import html as py_html
import os
import sys
import datetime as dt
from typing import Tuple, Dict, List

import altair as alt
import pandas as pd
import streamlit as st
import requests
from dateutil import parser as dtparser
from dateutil import tz

from core.odds_api import fetch_nba_spreads_window
from core.schedule_espn import fetch_games_for_date
from core.standings import _normalize_team_name, get_record, get_win_pct
from core.standings_espn import fetch_team_standings_detail_maps
from core.team_meta import get_logo_url, get_team_abbr
from core.health_espn import compute_team_player_impacts, injury_weight
from core.importance import compute_importance_detail_map
from core.watchability_v2_params import KEY_INJURY_IMPACT_SHARE_THRESHOLD, INJURY_OVERALL_IMPORTANCE_WEIGHT
from core.build_watchability_df import build_watchability_df

import core.watchability as watch


@st.cache_data(ttl=60 * 5)  # 5 min (odds + injuries)
def load_watchability_df(days_ahead: int = 2) -> pd.DataFrame:
    return build_watchability_df(days_ahead=days_ahead)


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
.menu-awi .score {font-size: 14px; font-weight: 650; line-height: 1.15; word-break: break-word;}
.menu-awi .subscores {margin-top: 2px; font-size: 12px; color: rgba(49,51,63,0.75); line-height: 1.15;}
.menu-awi .subscore {display:block;}
.menu-awi .label {font-size: 18px; font-weight: 800; color: rgba(0,0,0,0.90); line-height: 1.15;}
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
.menu-matchup .sep {font-size: 12px; font-weight: 400; color: rgba(49,51,63,0.35); white-space: nowrap;}
.menu-matchup .health {font-size: 12px; font-weight: 600; color: rgba(49,51,63,0.65); white-space: nowrap;}
.menu-matchup .health[data-tooltip] {cursor: pointer; text-decoration: underline dotted rgba(49,51,63,0.35); position: relative;}
.menu-matchup .health[data-tooltip]:hover::after {
  content: attr(data-tooltip);
  position: absolute;
  left: 0;
  top: 125%;
  z-index: 9999;
  max-width: 320px;
  white-space: normal;
  background: rgba(255,255,255,0.98);
  color: rgba(49,51,63,0.95);
  border: 1px solid rgba(49,51,63,0.20);
  box-shadow: 0 8px 24px rgba(0,0,0,0.10);
  padding: 8px 10px;
  border-radius: 8px;
  font-weight: 500;
  line-height: 1.25;
}
.menu-matchup .health[data-tooltip]:hover::before {
  content: "";
  position: absolute;
  left: 12px;
  top: 110%;
  border-width: 6px;
  border-style: solid;
  border-color: transparent transparent rgba(49,51,63,0.20) transparent;
}
.menu-meta {width: 240px; font-size: 13px; color: rgba(49,51,63,0.75); line-height: 1.3;}
.menu-meta div {margin: 1px 0;}

/* Small "info" hover icon next to the dashboard caption. */
.info-icon {display:inline-flex; align-items:center; justify-content:center; width: 22px; height: 22px; border-radius: 999px; border: 1px solid rgba(49,51,63,0.25); color: rgba(49,51,63,0.8); font-size: 13px; font-weight: 700;}
.info-icon[data-tooltip] {cursor: pointer; position: relative;}
.caption-row {display: inline-flex; align-items: center; gap: 10px;}
.caption-text {color: rgba(49,51,63,0.6); font-size: 0.9rem; line-height: 1.25;}
.caption-spacer {height: 14px;}
.info-icon[data-tooltip]:hover::after {
  content: attr(data-tooltip);
  position: absolute;
  left: 0;
  top: 130%;
  z-index: 9999;
  width: 340px;
  white-space: pre-line;
  background: rgba(255,255,255,0.98);
  color: rgba(49,51,63,0.95);
  border: 1px solid rgba(49,51,63,0.20);
  box-shadow: 0 8px 24px rgba(0,0,0,0.10);
  padding: 10px 12px;
  border-radius: 10px;
  font-weight: 500;
  line-height: 1.3;
}
.info-icon[data-tooltip]:hover::before {
  content: "";
  position: absolute;
  left: 10px;
  top: 115%;
  border-width: 6px;
  border-style: solid;
  border-color: transparent transparent rgba(49,51,63,0.20) transparent;
}

/* Mobile layout: prevent overlap by stacking meta below matchup. */
@media (max-width: 640px) {
  .menu-row {flex-wrap: wrap; align-items: flex-start; gap: 8px 10px;}
  .menu-awi {width: 92px;}
  .menu-matchup {min-width: 0; flex: 1 1 calc(100% - 102px);}
  .menu-meta {width: 100%; padding-left: 92px; font-size: 14px; line-height: 1.35;}
  .menu-matchup .record {font-size: 11px;}
}
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
    try:
        return fetch_team_standings_detail_maps()
    except Exception:
        return {}, {}, {}


@st.cache_data(ttl=60 * 60 * 24)  # 24 hours (impact stats stable-ish)
def load_team_impacts(team_names: tuple[str, ...]) -> dict[str, dict]:
    """
    Returns per-team (normalized team name):
      { 'players': [{id,name,raw,share,rel}] }
    """
    out: dict[str, dict] = {}
    for name in team_names:
        key = _normalize_team_name(name)
        try:
            players = compute_team_player_impacts(name)
        except Exception:
            out[key] = {"players": []}
            continue

        out[key] = {
            "players": [
                {
                    "id": p.athlete_id,
                    "name": p.name,
                    "raw": float(p.raw_impact),
                    "share": float(p.impact_share),
                    "rel": float(p.relative_raw_impact),
                }
                for p in players
            ]
        }
    return out


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
      - game_id (str)
      - home_score (int|None)
      - away_score (int|None)
      - time_remaining (str|None) e.g. '5:32 Q3'
    """
    out: dict[tuple[str, str, str], dict] = {}
    if not local_dates_iso:
        return out

    targets = set(str(x) for x in local_dates_iso)
    local_tz = tz.gettz("America/Los_Angeles")

    # ESPN's scoreboard "dates=" is not always aligned with PT local dates for late games,
    # so fetch an extra day window and then map events back into PT dates.
    candidate_days = set()
    for iso in targets:
        try:
            y, m, d = (int(x) for x in iso.split("-"))
            day = dt.date(y, m, d)
            candidate_days.add(day)
            candidate_days.add(day + dt.timedelta(days=1))
        except Exception:
            continue

    for day in sorted(candidate_days):
        try:
            games = fetch_games_for_date(day)
        except Exception:
            continue
        for g in games:
            try:
                start = g.get("start_time_utc")
                if start:
                    dt_local = dtparser.isoparse(str(start)).astimezone(local_tz)
                    iso_local = dt_local.date().isoformat()
                else:
                    iso_local = None
            except Exception:
                iso_local = None
            if not iso_local or iso_local not in targets:
                continue

            home = _normalize_team_name(str(g.get("home_team", "")))
            away = _normalize_team_name(str(g.get("away_team", "")))
            state = str(g.get("state", ""))
            home_score = _parse_score(g.get("home_score"))
            away_score = _parse_score(g.get("away_score"))
            time_remaining = g.get("time_remaining")
            if home and away and state:
                out[(iso_local, home, away)] = {
                    "state": state,
                    "game_id": str(g.get("game_id") or ""),
                    "home_score": home_score,
                    "away_score": away_score,
                    "time_remaining": time_remaining,
                }
    return out


def _normalize_status_for_display(status: str | None) -> str:
    s = (status or "").strip()
    if not s:
        return "Available"
    if s.upper() == "GTD":
        return "GTD"
    return s


@st.cache_data(ttl=60 * 10)  # 10 min
def load_espn_game_injury_report_map(game_ids: tuple[str, ...]) -> dict[str, dict[str, dict[str, str]]]:
    """
    Returns: game_id -> team_key -> athlete_id -> status
    (team_key is normalized team displayName from ESPN summary)
    """
    out: dict[str, dict[str, dict[str, str]]] = {}
    for gid in game_ids:
        gid_s = str(gid).strip()
        if not gid_s:
            continue
        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
            r = requests.get(url, params={"event": gid_s}, timeout=12)
            r.raise_for_status()
            data = r.json()
        except Exception:
            continue

        injuries = data.get("injuries") if isinstance(data, dict) else None
        if not isinstance(injuries, list):
            continue

        by_team: dict[str, dict[str, str]] = {}
        for block in injuries:
            if not isinstance(block, dict):
                continue
            team = block.get("team")
            if not isinstance(team, dict):
                continue
            team_name = team.get("displayName") or team.get("name")
            if not team_name:
                continue
            team_key = _normalize_team_name(str(team_name))
            team_inj = block.get("injuries")
            if not isinstance(team_inj, list):
                continue

            m: dict[str, str] = {}
            for inj in team_inj:
                if not isinstance(inj, dict):
                    continue
                athlete = inj.get("athlete")
                athlete_id = None
                if isinstance(athlete, dict) and athlete.get("id"):
                    athlete_id = str(athlete.get("id"))
                if not athlete_id:
                    continue
                status = inj.get("status")
                details = inj.get("details")
                fs = None
                if isinstance(details, dict):
                    fantasy = details.get("fantasyStatus")
                    if isinstance(fantasy, dict):
                        fs = fantasy.get("displayDescription") or fantasy.get("description") or fantasy.get("abbreviation")

                chosen = _normalize_status_for_display(str(fs) if fs else (str(status) if status else ""))
                m[athlete_id] = chosen
            by_team[team_key] = m

        out[gid_s] = by_team

    return out


def _fmt_m_d(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def build_dashboard_frames() -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict[str, str]]:
    df = load_watchability_df(days_ahead=2)
    if df.empty:
        st.warning("No games returned from Odds API. (Off day? API issue? Check your key/limits.)")
        st.stop()

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
    if "Away Key Injuries" in df_plot.columns:
        df_plot["Away Key Injuries"] = df_plot["Away Key Injuries"].fillna("")
    if "Home Key Injuries" in df_plot.columns:
        df_plot["Home Key Injuries"] = df_plot["Home Key Injuries"].fillna("")
    if "Away Star Factor" in df_plot.columns:
        df_plot["Away Star Factor"] = df_plot["Away Star Factor"].fillna("")
    if "Home Star Factor" in df_plot.columns:
        df_plot["Home Star Factor"] = df_plot["Home Star Factor"].fillna("")
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

    region_order = ["Must Watch", "Strong Watch", "Watchable", "Skippable", "Hard Skip"]
    region_colors = {
        "Must Watch": "#1f77b4",
        "Strong Watch": "#2ca02c",
        "Watchable": "#ff7f0e",
        "Skippable": "#9467bd",
        "Hard Skip": "#7f7f7f",
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
        .transform_filter(alt.datum.Region != "Hard Skip")
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
        .transform_filter(alt.datum.Region == "Hard Skip")
        .mark_rect(opacity=0.15, color=region_colors["Hard Skip"])
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
            {"label": "Must Watch", "x": 0.93, "y": 0.93},
            {"label": "Strong Watch", "x": 0.80, "y": 0.82},
            {"label": "Watchable", "x": 0.60, "y": 0.60},
            {"label": "Skippable", "x": 0.40, "y": 0.40},
            {"label": "Hard Skip", "x": 0.20, "y": 0.20},
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
        alt.Tooltip("aWI:Q", title="Watchability", format=".1f"),
        alt.Tooltip("Region:N"),
        alt.Tooltip("Tip (PT):N"),
        alt.Tooltip("Home spread:Q"),
        alt.Tooltip("Health (away):Q", title="Away health", format=".2f"),
        alt.Tooltip("Health (home):Q", title="Home health", format=".2f"),
        alt.Tooltip("Away Star Factor:N"),
        alt.Tooltip("Home Star Factor:N"),
        alt.Tooltip("Away Key Injuries:N"),
        alt.Tooltip("Home Key Injuries:N"),
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
    tooltip_cols = [
        "Matchup",
        "Tip short",
        "Tip (PT)",
        "Home spread",
        "Record (away)",
        "Record (home)",
        "aWI",
        "Region",
        "Team quality",
        "Closeness",
        "Importance",
        "Health (away)",
        "Health (home)",
        "Away Star Factor",
        "Home Star Factor",
        "Away Key Injuries",
        "Home Key Injuries",
        "Importance (away)",
        "Importance (home)",
        "Seed radius (away)",
        "Seed radius (home)",
        "Playoff radius (away)",
        "Playoff radius (home)",
        "_x",
        "_logo",
    ]
    tooltip_cols = list(dict.fromkeys([c for c in tooltip_cols if c in df_plot.columns] + ["_x", "_logo"]))

    images_df = pd.concat(
        [
            away_points[tooltip_cols].assign(_side="away"),
            home_points[tooltip_cols].assign(_side="home"),
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

    chart_legend_df = pd.DataFrame(
        [
            {"text": "↗ Better games (high quality + close)", "x": QUALITY_FLOOR + 0.01, "y": CLOSENESS_FLOOR + 0.08},
            {"text": "↙ Less watchable", "x": QUALITY_FLOOR + 0.01, "y": CLOSENESS_FLOOR + 0.03},
        ]
    )
    chart_legend = alt.Chart(chart_legend_df).mark_text(
        align="left",
        baseline="top",
        fontSize=12,
        fontWeight=600,
        color="rgba(49,51,63,0.70)",
        opacity=0.95,
    ).encode(
        x=alt.X("x:Q", scale=alt.Scale(domain=[QUALITY_FLOOR, 1.0]), axis=None),
        y=alt.Y("y:Q", scale=alt.Scale(domain=[CLOSENESS_FLOOR, 1.0]), axis=None),
        text=alt.Text("text:N"),
        tooltip=[],
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
        + chart_legend
    ).resolve_scale(x="shared", y="shared").properties(height=560)
    st.altair_chart(chart, use_container_width=True)


def _render_menu_row(r) -> str:
    awi_score = int(round(float(r["aWI"])))
    label = py_html.escape(str(r["Region"]))

    q = r.get("Team quality")
    c = r.get("Closeness")
    q_score = None if q is None else 100.0 * float(q)
    c_score = None if c is None else 100.0 * float(c)
    q_str = "—" if q_score is None else str(int(round(q_score)))
    c_str = "—" if c_score is None else str(int(round(c_score)))

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
    dt_pt = r.get("Tip dt (PT)")
    dt_et = r.get("Tip dt (ET)")
    if dt_pt is not None and dt_et is not None:
        dow = dt_pt.strftime("%a")
        pt_time = dt_pt.strftime("%I:%M%p").replace(" 0", " ").replace("AM", "am").replace("PM", "pm").lstrip("0")
        et_time = dt_et.strftime("%I:%M%p").replace("AM", "am").replace("PM", "pm").lstrip("0")
        tip_line = f"Tip {dow} {pt_time} PT / {et_time} ET"
    else:
        tip_pt = str(r.get("Tip (PT)", "Unknown"))
        tip_et = str(r.get("Tip (ET)", "Unknown"))
        tip_line = f"Tip {tip_pt} PT / {tip_et} ET"
    tip_line = py_html.escape(tip_line)
    spread = r["Home spread"]
    home_abbr = get_team_abbr(str(r.get("Home team", ""))) or str(r.get("Home team", ""))[:3].upper()
    spread_str = "?" if spread is None else f"{home_abbr} {float(spread):+g}"
    record_away = py_html.escape(str(r.get("Record (away)", "—")))
    record_home = py_html.escape(str(r.get("Record (home)", "—")))
    health_away = r.get("Health (away)")
    health_home = r.get("Health (home)")
    health_away_str = "—" if health_away is None else f"{float(health_away):.2f}"
    health_home_str = "—" if health_home is None else f"{float(health_home):.2f}"

    away_inj = str(r.get("Away Key Injuries", "") or "").strip()
    home_inj = str(r.get("Home Key Injuries", "") or "").strip()

    away_tip = py_html.escape(away_inj) if away_inj else ""
    home_tip = py_html.escape(home_inj) if home_inj else ""

    away_star_html = ""
    home_star_html = ""
    if bool(r.get("_away_top_star", False)):
        tip = py_html.escape(str(r.get("Away Star Player") or ""))
        away_star_html = f"<div class='sep'>|</div><div class='health' data-tooltip=\"{tip}\">⭐ Top Star</div>"
    if bool(r.get("_home_top_star", False)):
        tip = py_html.escape(str(r.get("Home Star Player") or ""))
        home_star_html = f"<div class='sep'>|</div><div class='health' data-tooltip=\"{tip}\">⭐ Top Star</div>"

    away_key_html = (
        f"<div class='sep'>|</div><div class='health' data-tooltip=\"{away_tip}\">❗ Key Injuries</div>"
        if away_inj
        else ""
    )
    home_key_html = (
        f"<div class='sep'>|</div><div class='health' data-tooltip=\"{home_tip}\">❗ Key Injuries</div>"
        if home_inj
        else ""
    )
    away_logo = py_html.escape(str(r["Away logo"]))
    home_logo = py_html.escape(str(r["Home logo"]))
    away_img = f"<img src='{away_logo}'/>" if away_logo else ""
    home_img = f"<img src='{home_logo}'/>" if home_logo else ""

    # Avoid leading indentation/newlines: Streamlit Markdown can render it as a code block.
    return f"""<div class="menu-row">
<div class="menu-awi">
<div class="label">{label}</div>
<div class="score">Watchability {awi_score}</div>
<div class="subscores">
<span class="subscore">Competitiveness {c_str}</span>
<span class="subscore">Team Quality {q_str}</span>
</div>
{live_badge}
</div>
<div class="menu-matchup">
<div class="teamline">
{away_img}
<div class="name">{away}</div>
<div class="record">{record_away}</div>
{away_star_html}
{away_key_html}
</div>
<div class="teamline">
{home_img}
<div class="name">{home}</div>
<div class="record">{record_home}</div>
{home_star_html}
{home_key_html}
</div>
</div>
<div class="menu-meta">
<div>{tip_line}</div>
<div>Spread: {spread_str}</div>
</div>
</div>"""


def render_table(df: pd.DataFrame, df_dates: pd.DataFrame, date_options: list[str]) -> None:
    sort_mode = st.segmented_control("Sort", options=["Watchability", "Tip time"], default="Watchability")
    sort_mode = sort_mode or "Watchability"

    def _top_star_sets(day_df: pd.DataFrame) -> tuple[set[str], set[str]]:
        # Top 5 star factors across teams playing that day (inclusive of availability scaling).
        entries: list[tuple[float, str, str]] = []
        for _, r in day_df.iterrows():
            away_key = _normalize_team_name(str(r.get("Away team", "")))
            home_key = _normalize_team_name(str(r.get("Home team", "")))
            try:
                af = float(r.get("Star factor (away)") or 0.0)
            except Exception:
                af = 0.0
            try:
                hf = float(r.get("Star factor (home)") or 0.0)
            except Exception:
                hf = 0.0
            if af > 0:
                entries.append((af, away_key, "away"))
            if hf > 0:
                entries.append((hf, home_key, "home"))

        entries.sort(key=lambda x: x[0], reverse=True)
        top_keys: list[str] = []
        for _, k, _side in entries:
            if k and k not in top_keys:
                top_keys.append(k)
            if len(top_keys) >= 5:
                break
        top_set = set(top_keys)
        return top_set, top_set

    if date_options:
        for local_date, day_name in df_dates.itertuples(index=False, name=None):
            st.markdown(f"**{py_html.escape(str(day_name))}**")
            st.divider()
            day_df = df[df["Local date"] == local_date].copy()
            top_star_set, _ = _top_star_sets(day_df)
            day_df["_away_top_star"] = day_df["Away team"].apply(lambda t: _normalize_team_name(str(t)) in top_star_set)
            day_df["_home_top_star"] = day_df["Home team"].apply(lambda t: _normalize_team_name(str(t)) in top_star_set)
            if sort_mode == "Tip time" and "Tip dt (PT)" in day_df.columns:
                day_df = day_df.sort_values("Tip dt (PT)", ascending=True, na_position="last")
            else:
                day_df = day_df.sort_values("aWI", ascending=False)
            for _, row in day_df.iterrows():
                st.markdown(_render_menu_row(row), unsafe_allow_html=True)
            st.markdown("<div style='height: 100px;'></div>", unsafe_allow_html=True)
    else:
        flat = df.copy()
        top_star_set, _ = _top_star_sets(flat)
        flat["_away_top_star"] = flat["Away team"].apply(lambda t: _normalize_team_name(str(t)) in top_star_set)
        flat["_home_top_star"] = flat["Home team"].apply(lambda t: _normalize_team_name(str(t)) in top_star_set)
        if sort_mode == "Tip time" and "Tip dt (PT)" in flat.columns:
            flat = flat.sort_values("Tip dt (PT)", ascending=True, na_position="last")
        else:
            flat = flat.sort_values("aWI", ascending=False)
        for _, row in flat.iterrows():
            st.markdown(_render_menu_row(row), unsafe_allow_html=True)


def render_full_dashboard(title: str, caption: str) -> None:
    inject_base_css()
    inject_autorefresh()

    st.title(title)
    info_text = (
        "How it works\n"
        "• Competitiveness: based on the betting spread (smaller spread = closer game).\n"
        "• Team quality: based on team strength, adjusted for key injuries.\n"
        "• Output: a single Watchability score + simple labels (Must Watch → Hard Skip).\n"
        "• Updates live: watchability can change as the score stays close (or blows out)."
    )
    info_attr = py_html.escape(info_text).replace("\n", "&#10;")
    cap_text = py_html.escape(caption)
    st.markdown(
        f"<div class='caption-row'><span class='caption-text'>{cap_text}</span>"
        f"<span class='info-icon' data-tooltip=\"{info_attr}\">i</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='caption-spacer'></div>", unsafe_allow_html=True)

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
