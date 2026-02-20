from __future__ import annotations

import html as py_html
import json
import os
import sys
import datetime as dt
import textwrap
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
from core.team_meta import get_logo_url, get_team_abbr, get_team_mascot
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
.menu-row {display:flex; align-items:center; gap:12px;}
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
.menu-matchup img {width: 34px; height: 34px;}
.menu-matchup .name {font-size: 16px; font-weight: 800; color: rgba(0,0,0,0.90); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.menu-matchup .name-full {display: inline;}
.menu-matchup .name-short {display: none;}
.menu-matchup .record {font-size: 11px; font-weight: 400; color: rgba(49,51,63,0.65); white-space: nowrap;}
.menu-matchup .sep {font-size: 11px; font-weight: 400; color: rgba(49,51,63,0.35); white-space: nowrap;}
.menu-matchup .health {font-size: 11px; font-weight: 600; color: rgba(49,51,63,0.65); white-space: nowrap;}
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

/* Recommendations module */
.rec-wrap {margin-bottom: 10px;}
.rec-head {font-size: 22px; font-weight: 950; color: rgba(49,51,63,0.90); letter-spacing: 0.2px; margin-bottom: 8px;}
.rec-card {border: 1px solid rgba(49,51,63,0.15); border-radius: 14px; padding: 12px 12px; background: rgba(255,255,255,0.92); box-shadow: 0 8px 22px rgba(0,0,0,0.06); margin-bottom: 10px;}
.rec-title {font-size: 20px; font-weight: 900; color: rgba(49,51,63,0.90); line-height: 1.1;}
.rec-title.now {color: rgba(214, 39, 40, 0.90);}   /* red tint */
.rec-title.upcoming {color: rgba(31, 119, 180, 0.90);} /* blue tint */
.rec-title.doubleheader {color: rgba(44, 160, 44, 0.90);} /* green tint */
.rec-sub {margin-top: 2px; font-size: 18px; font-weight: 900; color: rgba(0,0,0,0.92); line-height: 1.1;}
.rec-row {margin-top: 8px; display:flex; align-items:center; gap:10px;}
.rec-teams {flex:1; display:flex; flex-direction: column; gap:6px; min-width: 0;}
.rec-teamline {display:flex; align-items:center; gap:8px; min-width: 0;}
.rec-teamline img {width: 34px; height: 34px;}
.rec-teamline .name {font-size: 16px; font-weight: 800; color: rgba(0,0,0,0.90); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.rec-teamline .name-full {display: inline;}
.rec-teamline .name-short {display: none;}
.rec-teamline .record {font-size: 11px; font-weight: 400; color: rgba(49,51,63,0.65); white-space: nowrap;}
.rec-teamline .sep {font-size: 11px; font-weight: 400; color: rgba(49,51,63,0.35); white-space: nowrap;}
.rec-teamline .health {font-size: 11px; font-weight: 600; color: rgba(49,51,63,0.65); white-space: nowrap;}
.rec-teamline .health[data-tooltip] {cursor: pointer; text-decoration: underline dotted rgba(49,51,63,0.35); position: relative;}
.rec-teamline .health[data-tooltip]:hover::after {
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
.rec-teamline .health[data-tooltip]:hover::before {
  content: "";
  position: absolute;
  left: 12px;
  top: 110%;
  border-width: 6px;
  border-style: solid;
  border-color: transparent transparent rgba(49,51,63,0.20) transparent;
}
.rec-meta {display:flex; flex-direction: column; align-items: flex-end; gap:6px;}
.chip {display:inline-flex; align-items:center; justify-content:center; border: 1px solid rgba(49,51,63,0.20); border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 700; color: rgba(49,51,63,0.80); background: rgba(255,255,255,0.95);}
.chip a {color: rgba(49,51,63,0.85); text-decoration: none;}
.rec-live {font-size: 12px; font-weight: 900; color: #d62728;}
.rec-score {font-size: 12px; font-weight: 900; color: #d62728; margin-top: -2px;}
.rec-wi {font-size: 12px; font-weight: 800; color: rgba(49,51,63,0.78);}
.rec-tip {font-weight: 850; color: rgba(49,51,63,0.82);}
.rec-menu-row {padding-top: 10px; padding-bottom: 10px;}
.rec-menu-row + .rec-menu-row {border-top: 1px solid rgba(49,51,63,0.12);}
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
  .menu-matchup .name-full {display: none;}
  .menu-matchup .name-short {display: inline;}
  .rec-teamline .name-full {display: none;}
  .rec-teamline .name-short {display: inline;}
}

/* On mobile, show Recommendations above the All Games menu. */
.recs-mobile {display: none;}
.recs-desktop {display: block;}
@media (max-width: 640px) {
  .recs-mobile {display: block;}
  .recs-desktop {display: none;}
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


def _parse_time_remaining(tr: str | None) -> tuple[int | None, int | None]:
    """
    Returns (quarter, seconds_remaining_in_quarter) if parsable.
    Expected formats include: '5:32 Q3', '12:00 Q4', '0.0 Q2'.
    """
    if tr is None:
        return None, None
    s = str(tr).strip().upper()
    if not s:
        return None, None
    try:
        import re

        m = re.search(r"(\\d{1,2})[:.](\\d{1,2})\\s*Q(\\d)", s)
    except Exception:
        m = None
    if not m:
        return None, None
    mm = int(m.group(1))
    ss = int(m.group(2))
    q = int(m.group(3))
    return q, mm * 60 + ss


def _w2wn_live_boost(time_remaining: str | None, away_score: int | None, home_score: int | None) -> float:
    """
    W2WN live boost:
      - +3 in Q3 if score diff < 10
      - +5 in Q4 if score diff < 10
    """
    q, _sec = _parse_time_remaining(time_remaining)
    if q is None:
        return 0.0
    if away_score is None or home_score is None:
        return 0.0
    try:
        diff = abs(int(away_score) - int(home_score))
    except Exception:
        return 0.0
    if diff >= 10:
        return 0.0
    if q == 3:
        return 3.0
    if q >= 4:
        return 5.0
    return 0.0


def _fmt_wait_time(minutes: float) -> str:
    m = max(0.0, float(minutes))
    if m > 60:
        hrs = m / 60.0
        if hrs >= 2.0:
            return f"{int(round(hrs))} hours"
        return f"{hrs:.1f} hours"
    return f"{int(round(m))} mins"


def _pick_slate_df(df: pd.DataFrame, slate_day: str | None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if slate_day and "Local date" in df.columns:
        out = df[df["Local date"].astype(str) == str(slate_day)].copy()
        if not out.empty:
            return out
    # Fallback: earliest PT date in the window.
    if "Local date" in df.columns:
        dates = sorted({str(x) for x in df["Local date"].dropna().tolist() if str(x).strip()})
        if dates:
            return df[df["Local date"].astype(str) == dates[0]].copy()
    return df.copy()


def render_recommendations_module(df: pd.DataFrame, *, slate_day: str | None, wrapper_class: str = "") -> None:
    """
    Recommendations:
      - What to watch now (W2WN)
      - Best upcoming game tonight
      - Best doubleheader tonight
      - Best games to switch between
    """
    if df is None or df.empty:
        return

    now_pt = dt.datetime.now(tz=tz.gettz("America/Los_Angeles"))
    d = _pick_slate_df(df, slate_day)
    if d is None or d.empty:
        return

    # Recommendation feature flags (keep infra, but allow disabling specific cards).
    ENABLE_DOUBLEHEADER_REC = False
    ENABLE_SWITCH_BETWEEN_REC = False

    d["_is_live"] = d.get("Is live", False)
    d["_status"] = d.get("Status", "pre").astype(str) if "Status" in d.columns else "pre"

    def _minutes_to_tip_row(r) -> float | None:
        dt_pt = r.get("Tip dt (PT)")
        if isinstance(dt_pt, dt.datetime):
            return (dt_pt - now_pt).total_seconds() / 60.0
        return None

    d["_minutes_to_tip"] = d.apply(_minutes_to_tip_row, axis=1)

    today_pt = now_pt.date()

    def _is_today_pt_tip(x) -> bool:
        if isinstance(x, dt.datetime):
            return x.date() == today_pt
        return False

    def _top_star_set(day_df: pd.DataFrame) -> set[str]:
        entries: list[tuple[float, str]] = []
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
            if af > 0 and away_key:
                entries.append((af, away_key))
            if hf > 0 and home_key:
                entries.append((hf, home_key))

        entries.sort(key=lambda x: x[0], reverse=True)
        top_keys: list[str] = []
        for _v, k in entries:
            if k and k not in top_keys:
                top_keys.append(k)
            if len(top_keys) >= 5:
                break
        return set(top_keys)

    # Populate top-star flags on this slate (used by recommendation row rendering).
    if "Tip dt (PT)" in d.columns:
        d["_is_today_pt"] = d["Tip dt (PT)"].apply(_is_today_pt_tip)
        eligible = d[d["_is_today_pt"]].copy()
    else:
        d["_is_today_pt"] = False
        eligible = d.iloc[0:0].copy()
    top_star_set = _top_star_set(eligible)
    d["_away_top_star"] = d.apply(
        lambda r: bool(r.get("_is_today_pt", False))
        and _normalize_team_name(str(r.get("Away team", ""))) in top_star_set,
        axis=1,
    )
    d["_home_top_star"] = d.apply(
        lambda r: bool(r.get("_is_today_pt", False))
        and _normalize_team_name(str(r.get("Home team", ""))) in top_star_set,
        axis=1,
    )

    def _w2wn_score_row(r) -> float:
        wi = float(r.get("aWI") or 0.0)
        # Treat ESPN 'in' as live even if boolean flag is missing.
        if bool(r.get("_is_live", False)) or str(r.get("_status") or "").lower() == "in":
            away_s = _parse_score(r.get("Away score"))
            home_s = _parse_score(r.get("Home score"))
            return wi + float(_w2wn_live_boost(r.get("Time remaining"), away_s, home_s))
        if str(r.get("_status") or "").lower() == "pre":
            m = r.get("_minutes_to_tip")
            if m is None:
                # Unknown tip time: strongly de-prioritize.
                return wi - 1_000_000.0
            m = max(0.0, float(m))
            return wi - (m / 2.0)
        return wi

    d["_w2wn_score"] = d.apply(_w2wn_score_row, axis=1)

    def _chip(where_url: str, provider: str) -> str:
        url = (where_url or "").strip()
        if not url:
            return ""
        return (
            f"<span class='chip'><a href='{py_html.escape(url)}' target='_blank' rel='noopener noreferrer'>"
            f"Where to watch: {py_html.escape(provider or 'League Pass')}</a></span>"
        )

    def _subscores_row(r) -> tuple[str, str]:
        q = r.get("Team quality")
        c = r.get("Closeness")
        q_score = None if q is None else 100.0 * float(q)
        c_score = None if c is None else 100.0 * float(c)
        q_str = "—" if q_score is None else str(int(round(q_score)))
        c_str = "—" if c_score is None else str(int(round(c_score)))
        return c_str, q_str

    def _spread_str(r) -> str:
        spread = r.get("Home spread")
        home = str(r.get("Home team", "") or "")
        home_abbr = get_team_abbr(home) or home[:3].upper()
        return "?" if spread is None else f"{home_abbr} {float(spread):+g}"

    def _menu_like_row(row) -> str:
        awi_score = int(round(float(row.get("aWI") or 0.0)))
        label = py_html.escape(str(row.get("Region") or ""))

        c_str, q_str = _subscores_row(row)

        live_badge = ""
        is_live = bool(row.get("_is_live", False)) or str(row.get("_status") or "").lower() == "in"
        if is_live:
            away_s = _parse_score(row.get("Away score"))
            home_s = _parse_score(row.get("Home score"))
            tr = str(row.get("Time remaining") or "").strip()
            tr_line = f"<div class='live-time'>🚨 LIVE {py_html.escape(tr)}</div>" if tr else "<div class='live-time'>🚨 LIVE</div>"
            if away_s is not None and home_s is not None:
                live_badge = f"{tr_line}<div class='live-badge'>{int(away_s)} - {int(home_s)}</div>"
            else:
                live_badge = tr_line

        away_full = str(row.get("Away team") or "")
        home_full = str(row.get("Home team") or "")
        away_mascot = get_team_mascot(away_full) or away_full
        home_mascot = get_team_mascot(home_full) or home_full
        away = py_html.escape(away_full)
        home = py_html.escape(home_full)
        away_short = py_html.escape(str(away_mascot))
        home_short = py_html.escape(str(home_mascot))

        dt_pt = row.get("Tip dt (PT)")
        dt_et = row.get("Tip dt (ET)")
        if isinstance(dt_pt, dt.datetime) and isinstance(dt_et, dt.datetime):
            dow = dt_pt.strftime("%a")
            pt_time = (
                dt_pt.strftime("%I:%M%p")
                .replace(" 0", " ")
                .replace("AM", "am")
                .replace("PM", "pm")
                .lstrip("0")
            )
            et_time = (
                dt_et.strftime("%I:%M%p")
                .replace("AM", "am")
                .replace("PM", "pm")
                .lstrip("0")
            )
            tip_line = f"Tip {dow} {pt_time} PT / {et_time} ET"
        else:
            tip_line = str(row.get("Tip (PT)", "Unknown"))
            tip_line = f"Tip {tip_line}"
        tip_line = py_html.escape(tip_line)

        spread_str = py_html.escape(_spread_str(row))

        where_url = str(row.get("Where to watch URL", "") or "").strip()
        where_html = ""
        if where_url:
            provider = str(row.get("Where to watch provider", "") or "").strip() or "League Pass"
            where_html = (
                f"<div><span class='chip'><a href='{py_html.escape(where_url)}' target='_blank' rel='noopener noreferrer'>"
                f"Where to watch: {py_html.escape(provider)}</a></span></div>"
            )

        record_away = py_html.escape(str(row.get("Record (away)", "—")))
        record_home = py_html.escape(str(row.get("Record (home)", "—")))

        away_inj = str(row.get("Away Key Injuries", "") or "").strip()
        home_inj = str(row.get("Home Key Injuries", "") or "").strip()
        away_tip = py_html.escape(away_inj) if away_inj else ""
        home_tip = py_html.escape(home_inj) if home_inj else ""

        away_star_html = ""
        home_star_html = ""
        if bool(row.get("_away_top_star", False)):
            tip = py_html.escape(str(row.get("Away Star Player") or ""))
            away_star_html = f"<div class='sep'>|</div><div class='health' data-tooltip=\"{tip}\">⭐ Top Star</div>"
        if bool(row.get("_home_top_star", False)):
            tip = py_html.escape(str(row.get("Home Star Player") or ""))
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

        away_logo = py_html.escape(str(row.get("Away logo") or ""))
        home_logo = py_html.escape(str(row.get("Home logo") or ""))
        away_img = f"<img src='{away_logo}'/>" if away_logo else ""
        home_img = f"<img src='{home_logo}'/>" if home_logo else ""

        return (
            f"<div class='menu-row rec-menu-row'>"
            f"<div class='menu-awi'>"
            f"<div class='label'>{label}</div>"
            f"<div class='score'>Watchability {awi_score}</div>"
            f"<div class='subscores'>"
            f"<span class='subscore'>Competitiveness {py_html.escape(c_str)}</span>"
            f"<span class='subscore'>Team Quality {py_html.escape(q_str)}</span>"
            f"</div>"
            f"{live_badge}"
            f"</div>"
            f"<div class='menu-matchup'>"
            f"<div class='teamline'>"
            f"{away_img}"
            f"<div class='name'><span class='name-full'>{away}</span><span class='name-short'>{away_short}</span></div>"
            f"<div class='record'>{record_away}</div>"
            f"{away_star_html}{away_key_html}"
            f"</div>"
            f"<div class='teamline'>"
            f"{home_img}"
            f"<div class='name'><span class='name-full'>{home}</span><span class='name-short'>{home_short}</span></div>"
            f"<div class='record'>{record_home}</div>"
            f"{home_star_html}{home_key_html}"
            f"</div>"
            f"</div>"
            f"<div class='menu-meta'>"
            f"<div class='rec-tip'>{tip_line}</div>"
            f"<div>Spread: {spread_str}</div>"
            f"{where_html}"
            f"</div>"
            f"</div>"
        )

    def _matchup_block(r) -> str:
        away_full = str(r.get("Away team") or "")
        home_full = str(r.get("Home team") or "")
        away_mascot = get_team_mascot(away_full) or away_full
        home_mascot = get_team_mascot(home_full) or home_full
        away = py_html.escape(away_full)
        home = py_html.escape(home_full)
        away_short = py_html.escape(str(away_mascot))
        home_short = py_html.escape(str(home_mascot))
        away_logo = py_html.escape(str(r.get("Away logo") or ""))
        home_logo = py_html.escape(str(r.get("Home logo") or ""))
        away_img = f"<img src='{away_logo}'/>" if away_logo else ""
        home_img = f"<img src='{home_logo}'/>" if home_logo else ""
        record_away = py_html.escape(str(r.get("Record (away)", "—")))
        record_home = py_html.escape(str(r.get("Record (home)", "—")))

        away_inj = str(r.get("Away Key Injuries", "") or "").strip()
        home_inj = str(r.get("Home Key Injuries", "") or "").strip()
        away_inj_tip = py_html.escape(away_inj) if away_inj else ""
        home_inj_tip = py_html.escape(home_inj) if home_inj else ""

        away_star_html = ""
        home_star_html = ""
        if bool(r.get("_away_top_star", False)):
            tip = py_html.escape(str(r.get("Away Star Player") or ""))
            away_star_html = f"<div class='sep'>|</div><div class='health' data-tooltip=\"{tip}\">⭐ Top Star</div>"
        if bool(r.get("_home_top_star", False)):
            tip = py_html.escape(str(r.get("Home Star Player") or ""))
            home_star_html = f"<div class='sep'>|</div><div class='health' data-tooltip=\"{tip}\">⭐ Top Star</div>"

        away_key_html = (
            f"<div class='sep'>|</div><div class='health' data-tooltip=\"{away_inj_tip}\">❗ Key Injuries</div>"
            if away_inj
            else ""
        )
        home_key_html = (
            f"<div class='sep'>|</div><div class='health' data-tooltip=\"{home_inj_tip}\">❗ Key Injuries</div>"
            if home_inj
            else ""
        )

        return (
            f"<div class='rec-teams'>"
            f"<div class='rec-teamline'>{away_img}<div class='name'><span class='name-full'>{away}</span><span class='name-short'>{away_short}</span></div><div class='record'>{record_away}</div>{away_star_html}{away_key_html}</div>"
            f"<div class='rec-teamline'>{home_img}<div class='name'><span class='name-full'>{home}</span><span class='name-short'>{home_short}</span></div><div class='record'>{record_home}</div>{home_star_html}{home_key_html}</div>"
            f"</div>"
        )

    def _tip_pt_et(row) -> str:
        dt_pt = row.get("Tip dt (PT)")
        dt_et = row.get("Tip dt (ET)")
        if isinstance(dt_pt, dt.datetime) and isinstance(dt_et, dt.datetime):
            dow = dt_pt.strftime("%a")
            pt_time = (
                dt_pt.strftime("%I:%M%p")
                .replace(" 0", " ")
                .replace("AM", "am")
                .replace("PM", "pm")
                .lstrip("0")
            )
            et_time = (
                dt_et.strftime("%I:%M%p")
                .replace("AM", "am")
                .replace("PM", "pm")
                .lstrip("0")
            )
            return f"{dow} {pt_time} PT / {et_time} ET"
        tip_pt = str(row.get("Tip (PT)") or row.get("Tip short") or row.get("Tip display") or "").strip()
        tip_et = str(row.get("Tip (ET)") or "").strip()
        if tip_pt and tip_et:
            # tip_pt already has day/time; avoid repeating 'PT' if present.
            pt = tip_pt if "PT" in tip_pt else f"{tip_pt} PT"
            et = tip_et if "ET" in tip_et else f"{tip_et} ET"
            return f"{pt} / {et}"
        return tip_pt

    def _rec_card(*, title: str, title_class: str, subtitle: str, row, extra_meta: str = "") -> str:
        tip_display = py_html.escape(_tip_pt_et(row) or str(row.get("Tip display") or row.get("Tip short") or ""))
        wi_score = int(round(float(row.get("aWI") or 0.0)))
        chip = _chip(
            str(row.get("Where to watch URL") or ""),
            str(row.get("Where to watch provider") or "") or "League Pass",
        )
        c_str, q_str = _subscores_row(row)
        spread_line = py_html.escape(_spread_str(row))

        live_html = _live_score_html(row)
        return textwrap.dedent(
            f"""
            <div class="rec-card">
            <div class="rec-title {py_html.escape(title_class)}">{py_html.escape(title)}</div>
            <div class="rec-sub">{py_html.escape(subtitle)}</div>
            <div class="rec-row">
            {_matchup_block(row)}
            <div class="rec-meta">
            <div class="rec-wi">Watchability {wi_score}</div>
            <div class="rec-wi">Competitiveness {py_html.escape(c_str)} · Team Quality {py_html.escape(q_str)}</div>
            <div class="rec-wi">{tip_display}</div>
            <div class="rec-wi">Spread: {spread_line}</div>
            {live_html}
            {chip}
            {extra_meta}
            </div>
            </div>
            </div>
            """
        ).strip()

    def _live_score_html(row) -> str:
        is_live = bool(row.get("_is_live", False)) or str(row.get("_status") or "").lower() == "in"
        if not is_live:
            return ""
        live_line = ""
        score_line = ""
        tr = str(row.get("Time remaining") or "").strip()
        live_line = f"🚨 LIVE {py_html.escape(tr)}" if tr else "🚨 LIVE"
        away_s = _parse_score(row.get("Away score"))
        home_s = _parse_score(row.get("Home score"))
        if away_s is not None and home_s is not None:
            score_line = f"{int(away_s)} - {int(home_s)}"

        html = f"<div class='rec-live'>{live_line}</div>"
        if score_line:
            html += f"<div class='rec-score'>{py_html.escape(score_line)}</div>"
        return html

    def _rec_meta_block(row) -> str:
        tip_display = py_html.escape(_tip_pt_et(row) or str(row.get("Tip display") or row.get("Tip short") or ""))
        wi_score = int(round(float(row.get("aWI") or 0.0)))
        c_str, q_str = _subscores_row(row)
        spread_line = py_html.escape(_spread_str(row))
        chip = _chip(
            str(row.get("Where to watch URL") or ""),
            str(row.get("Where to watch provider") or "") or "League Pass",
        )
        live_html = _live_score_html(row)
        return textwrap.dedent(
            f"""
            <div class="rec-meta">
              <div class="rec-wi">Watchability {wi_score}</div>
              <div class="rec-wi">Competitiveness {py_html.escape(c_str)} · Team Quality {py_html.escape(q_str)}</div>
              <div class="rec-wi">{tip_display}</div>
              <div class="rec-wi">Spread: {spread_line}</div>
              {live_html}
              {chip}
            </div>
            """
        ).strip()

    def _rec_card_multi(*, title: str, title_class: str, subtitle: str, rows: list) -> str:
        # rows: list of dataframe rows (Series-like)
        inner_rows = "\n".join([_menu_like_row(r) for r in rows])
        return textwrap.dedent(
            f"""
            <div class="rec-card">
              <div class="rec-title {py_html.escape(title_class)}">{py_html.escape(title)}</div>
              <div class="rec-sub">{py_html.escape(subtitle)}</div>
              {inner_rows}
            </div>
            """
        ).strip()

    cards: list[str] = []

    # 1) What to watch now
    show_w2wn = False
    try:
        slate_date: dt.date | None = None
        if slate_day and len(str(slate_day)) == 10:
            y, m, dd = (int(x) for x in str(slate_day).split("-"))
            slate_date = dt.date(y, m, dd)
        elif "Local date" in d.columns and not d["Local date"].dropna().empty:
            v = d["Local date"].dropna().iloc[0]
            if isinstance(v, dt.date):
                slate_date = v

        is_same_day = bool(slate_date) and slate_date == now_pt.date()
        if is_same_day:
            # Only show when there is a live game.
            any_live = bool(
                (d.get("_is_live", False) == True).any()  # noqa: E712
                or (d.get("_status", "").astype(str).str.lower() == "in").any()
            )
            show_w2wn = any_live
    except Exception:
        show_w2wn = False

    if show_w2wn:
        live_df = d[
            (d.get("_is_live", False) == True)  # noqa: E712
            | (d.get("_status", "").astype(str).str.lower() == "in")
        ].copy()
        if not live_df.empty:
            live_sorted = live_df.sort_values(["_w2wn_score", "aWI"], ascending=False).reset_index(drop=True)
            rows = [live_sorted.iloc[0]]
            if len(live_sorted) > 1:
                r2 = live_sorted.iloc[1]
                if float(r2.get("aWI") or 0.0) > 50.0:
                    rows.append(r2)
            cards.append(_rec_card_multi(title="What to watch now", title_class="now", subtitle="Watch LIVE:", rows=rows))

    # 2) Best upcoming game tonight
    upcoming = d[
        (d["_status"].astype(str).str.lower() == "pre")
        & (d.get("_is_live", False) == False)  # noqa: E712
        & (d["_minutes_to_tip"].notna())
        & (d["_minutes_to_tip"].astype(float) > 0)
    ].copy()
    if not upcoming.empty:
        upcoming_sorted = upcoming.sort_values(["aWI", "_minutes_to_tip"], ascending=[False, True]).reset_index(drop=True)
        rows = [upcoming_sorted.iloc[0]]
        if len(upcoming_sorted) > 1:
            r2 = upcoming_sorted.iloc[1]
            if float(r2.get("aWI") or 0.0) > 50.0:
                rows.append(r2)
        if len(upcoming_sorted) > 2:
            r3 = upcoming_sorted.iloc[2]
            if float(r3.get("aWI") or 0.0) > 50.0:
                rows.append(r3)
        cards.append(_rec_card_multi(title="Best upcoming tonight", title_class="upcoming", subtitle="", rows=rows))

    # 3) Best doubleheader tonight (disabled for now; keep infra).
    if ENABLE_DOUBLEHEADER_REC:
        best_pair = None
        if not upcoming.empty and "Tip dt (PT)" in upcoming.columns:
            upcoming2 = upcoming.dropna(subset=["Tip dt (PT)"]).sort_values("Tip dt (PT)").copy()
            best_sum = None
            for i in range(len(upcoming2)):
                ti = upcoming2.iloc[i]["Tip dt (PT)"]
                for j in range(i + 1, len(upcoming2)):
                    tj = upcoming2.iloc[j]["Tip dt (PT)"]
                    if isinstance(ti, dt.datetime) and isinstance(tj, dt.datetime):
                        if (tj - ti).total_seconds() < 2 * 3600:
                            continue
                    s = float(upcoming2.iloc[i].get("aWI") or 0.0) + float(upcoming2.iloc[j].get("aWI") or 0.0)
                    if best_sum is None or s > best_sum:
                        best_sum = s
                        best_pair = (upcoming2.iloc[i], upcoming2.iloc[j])
        if best_pair is not None:
            g1, g2 = best_pair
            wi_avg = int(round(0.5 * (float(g1.get("aWI") or 0.0) + float(g2.get("aWI") or 0.0))))
            tip1 = py_html.escape(str(g1.get("Tip display") or g1.get("Tip short") or ""))
            tip2 = py_html.escape(str(g2.get("Tip display") or g2.get("Tip short") or ""))
            wi1 = int(round(float(g1.get("aWI") or 0.0)))
            wi2 = int(round(float(g2.get("aWI") or 0.0)))
            c1, q1 = _subscores_row(g1)
            c2, q2 = _subscores_row(g2)
            spread1 = py_html.escape(_spread_str(g1))
            spread2 = py_html.escape(_spread_str(g2))
            chip1 = _chip(str(g1.get("Where to watch URL") or ""), str(g1.get("Where to watch provider") or "") or "League Pass")
            chip2 = _chip(str(g2.get("Where to watch URL") or ""), str(g2.get("Where to watch provider") or "") or "League Pass")
            html = textwrap.dedent(
                f"""
                <div class="rec-card">
                <div class="rec-title doubleheader">Best doubleheader tonight</div>
                <div class="rec-sub">Two games (≥2h apart)</div>
                <div class="rec-wi">Average Watchability {wi_avg}</div>
                <div class="rec-row">
                  {_matchup_block(g1)}
                  <div class="rec-meta">
                    <div class="rec-wi">Watchability {wi1}</div>
                    <div class="rec-wi">Competitiveness {py_html.escape(c1)} · Team Quality {py_html.escape(q1)}</div>
                    <div class="rec-wi">{py_html.escape(_tip_pt_et(g1) or '') or tip1}</div>
                    <div class="rec-wi">Spread: {spread1}</div>
                    {chip1}
                  </div>
                </div>
                <div class="rec-row">
                  {_matchup_block(g2)}
                  <div class="rec-meta">
                    <div class="rec-wi">Watchability {wi2}</div>
                    <div class="rec-wi">Competitiveness {py_html.escape(c2)} · Team Quality {py_html.escape(q2)}</div>
                    <div class="rec-wi">{py_html.escape(_tip_pt_et(g2) or '') or tip2}</div>
                    <div class="rec-wi">Spread: {spread2}</div>
                    {chip2}
                  </div>
                </div>
                </div>
                """
            ).strip()
            cards.append(html)

    # 4) Best games to switch between (disabled for now; keep infra).
    if ENABLE_SWITCH_BETWEEN_REC:
        best_pair_close = None
        if not upcoming.empty and "Tip dt (PT)" in upcoming.columns:
            upcoming2 = upcoming.dropna(subset=["Tip dt (PT)"]).sort_values("Tip dt (PT)").copy()
            best_avg = None
            for i in range(len(upcoming2)):
                ti = upcoming2.iloc[i]["Tip dt (PT)"]
                for j in range(i + 1, len(upcoming2)):
                    tj = upcoming2.iloc[j]["Tip dt (PT)"]
                    if isinstance(ti, dt.datetime) and isinstance(tj, dt.datetime):
                        if (tj - ti).total_seconds() > 45 * 60:
                            break
                    avg = 0.5 * (
                        float(upcoming2.iloc[i].get("aWI") or 0.0)
                        + float(upcoming2.iloc[j].get("aWI") or 0.0)
                    )
                    if best_avg is None or avg > best_avg:
                        best_avg = avg
                        best_pair_close = (upcoming2.iloc[i], upcoming2.iloc[j])

        if best_pair_close is not None:
            g1, g2 = best_pair_close
            wi_avg = int(round(0.5 * (float(g1.get("aWI") or 0.0) + float(g2.get("aWI") or 0.0))))
            tip1 = py_html.escape(str(g1.get("Tip display") or g1.get("Tip short") or ""))
            tip2 = py_html.escape(str(g2.get("Tip display") or g2.get("Tip short") or ""))
            wi1 = int(round(float(g1.get("aWI") or 0.0)))
            wi2 = int(round(float(g2.get("aWI") or 0.0)))
            c1, q1 = _subscores_row(g1)
            c2, q2 = _subscores_row(g2)
            spread1 = py_html.escape(_spread_str(g1))
            spread2 = py_html.escape(_spread_str(g2))
            chip1 = _chip(
                str(g1.get("Where to watch URL") or ""),
                str(g1.get("Where to watch provider") or "") or "League Pass",
            )
            chip2 = _chip(
                str(g2.get("Where to watch URL") or ""),
                str(g2.get("Where to watch provider") or "") or "League Pass",
            )
            html = textwrap.dedent(
                f"""
                <div class="rec-card">
                <div class="rec-title">Best games to switch between</div>
                <div class="rec-sub">Two games (≤45m apart)</div>
                <div class="rec-wi">Average Watchability {wi_avg}</div>
                <div class="rec-row">
                  {_matchup_block(g1)}
                  <div class="rec-meta">
                    <div class="rec-wi">Watchability {wi1}</div>
                    <div class="rec-wi">Competitiveness {py_html.escape(c1)} · Team Quality {py_html.escape(q1)}</div>
                    <div class="rec-wi">{py_html.escape(_tip_pt_et(g1) or '') or tip1}</div>
                    <div class="rec-wi">Spread: {spread1}</div>
                    {chip1}
                  </div>
                </div>
                <div class="rec-row">
                  {_matchup_block(g2)}
                  <div class="rec-meta">
                    <div class="rec-wi">Watchability {wi2}</div>
                    <div class="rec-wi">Competitiveness {py_html.escape(c2)} · Team Quality {py_html.escape(q2)}</div>
                    <div class="rec-wi">{py_html.escape(_tip_pt_et(g2) or '') or tip2}</div>
                    <div class="rec-wi">Spread: {spread2}</div>
                    {chip2}
                  </div>
                </div>
                </div>
                """
            ).strip()
            cards.append(html)

    header_html = "<div class='rec-wrap'><div class='rec-head'>Recommendations</div></div>"
    inner = "\n".join([header_html] + cards)
    if wrapper_class:
        inner = f"<div class='{py_html.escape(wrapper_class)}'>{inner}</div>"
    st.markdown(inner, unsafe_allow_html=True)


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
    if s.upper() == "OUT":
        return "Out"
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
        return df, pd.DataFrame(columns=["Local date", "Day"]), [], {}

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
    default_day: str | None = None,
) -> str | None:
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
    selected: str | None = None
    if date_options:
        if show_day_selector:
            default_value = default_day if (default_day in date_options) else date_options[0]
            selected = st.segmented_control(
                "Day",
                options=date_options,
                format_func=lambda x: date_to_label.get(x, x),
                default=default_value,
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
    return selected


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

    away_full = str(r["Away team"])
    home_full = str(r["Home team"])
    away_mascot = get_team_mascot(away_full) or away_full
    home_mascot = get_team_mascot(home_full) or home_full
    away = py_html.escape(away_full)
    home = py_html.escape(home_full)
    away_short = py_html.escape(str(away_mascot))
    home_short = py_html.escape(str(home_mascot))
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
    where_url = str(r.get("Where to watch URL", "") or "").strip()
    where_html = ""
    if where_url:
        provider = str(r.get("Where to watch provider", "") or "").strip() or "League Pass"
        where_html = (
            f"<div><span class='chip'><a href='{py_html.escape(where_url)}' target='_blank' rel='noopener noreferrer'>Where to watch: {py_html.escape(provider)}</a></span></div>"
        )
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
    return f"""<div class="rec-card menu-row">
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
<div class="name"><span class="name-full">{away}</span><span class="name-short">{away_short}</span></div>
<div class="record">{record_away}</div>
{away_star_html}
{away_key_html}
</div>
<div class="teamline">
{home_img}
<div class="name"><span class="name-full">{home}</span><span class="name-short">{home_short}</span></div>
<div class="record">{record_home}</div>
{home_star_html}
{home_key_html}
</div>
</div>
<div class="menu-meta">
<div>{tip_line}</div>
<div>Spread: {spread_str}</div>
{where_html}
</div>
</div>"""


def render_table(
    df: pd.DataFrame,
    df_dates: pd.DataFrame,
    date_options: list[str],
    *,
    selected_day: str | None = None,
) -> None:
    sort_mode = st.segmented_control("Sort", options=["Watchability", "Tip time"], default="Watchability")
    sort_mode = sort_mode or "Watchability"
    today_pt = dt.datetime.now(tz=tz.gettz("America/Los_Angeles")).date()

    def _is_today_pt_tip(x) -> bool:
        if isinstance(x, dt.datetime):
            return x.date() == today_pt
        return False

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

    if selected_day and selected_day in (date_options or []) and "Local date" in df.columns:
        day_df = df[df["Local date"].astype(str) == str(selected_day)].copy()
        if day_df.empty:
            return
        if "Tip dt (PT)" in day_df.columns:
            day_df["_is_today_pt"] = day_df["Tip dt (PT)"].apply(_is_today_pt_tip)
            eligible = day_df[day_df["_is_today_pt"]].copy()
        else:
            day_df["_is_today_pt"] = False
            eligible = day_df.iloc[0:0].copy()

        top_star_set, _ = _top_star_sets(eligible)
        day_df["_away_top_star"] = day_df.apply(
            lambda r: bool(r.get("_is_today_pt", False))
            and _normalize_team_name(str(r.get("Away team", ""))) in top_star_set,
            axis=1,
        )
        day_df["_home_top_star"] = day_df.apply(
            lambda r: bool(r.get("_is_today_pt", False))
            and _normalize_team_name(str(r.get("Home team", ""))) in top_star_set,
            axis=1,
        )
        if sort_mode == "Tip time" and "Tip dt (PT)" in day_df.columns:
            day_df = day_df.sort_values("Tip dt (PT)", ascending=True, na_position="last")
        else:
            day_df = day_df.sort_values("aWI", ascending=False)
        for _, row in day_df.iterrows():
            st.markdown(_render_menu_row(row), unsafe_allow_html=True)
        return

    if date_options:
        for local_date, day_name in df_dates.itertuples(index=False, name=None):
            st.markdown(f"**{py_html.escape(str(day_name))}**")
            st.divider()
            day_df = df[df["Local date"] == local_date].copy()
            if "Tip dt (PT)" in day_df.columns:
                day_df["_is_today_pt"] = day_df["Tip dt (PT)"].apply(_is_today_pt_tip)
                eligible = day_df[day_df["_is_today_pt"]].copy()
            else:
                day_df["_is_today_pt"] = False
                eligible = day_df.iloc[0:0].copy()

            top_star_set, _ = _top_star_sets(eligible)
            day_df["_away_top_star"] = day_df.apply(
                lambda r: bool(r.get("_is_today_pt", False))
                and _normalize_team_name(str(r.get("Away team", ""))) in top_star_set,
                axis=1,
            )
            day_df["_home_top_star"] = day_df.apply(
                lambda r: bool(r.get("_is_today_pt", False))
                and _normalize_team_name(str(r.get("Home team", ""))) in top_star_set,
                axis=1,
            )
            if sort_mode == "Tip time" and "Tip dt (PT)" in day_df.columns:
                day_df = day_df.sort_values("Tip dt (PT)", ascending=True, na_position="last")
            else:
                day_df = day_df.sort_values("aWI", ascending=False)
            for _, row in day_df.iterrows():
                st.markdown(_render_menu_row(row), unsafe_allow_html=True)
            st.markdown("<div style='height: 100px;'></div>", unsafe_allow_html=True)
    else:
        flat = df.copy()
        if "Tip dt (PT)" in flat.columns:
            flat["_is_today_pt"] = flat["Tip dt (PT)"].apply(_is_today_pt_tip)
            eligible = flat[flat["_is_today_pt"]].copy()
        else:
            flat["_is_today_pt"] = False
            eligible = flat.iloc[0:0].copy()

        top_star_set, _ = _top_star_sets(eligible)
        flat["_away_top_star"] = flat.apply(
            lambda r: bool(r.get("_is_today_pt", False)) and _normalize_team_name(str(r.get("Away team", ""))) in top_star_set,
            axis=1,
        )
        flat["_home_top_star"] = flat.apply(
            lambda r: bool(r.get("_is_today_pt", False)) and _normalize_team_name(str(r.get("Home team", ""))) in top_star_set,
            axis=1,
        )
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
    if df.empty:
        st.warning("No NBA regular season or playoff games found. Enjoy the break!")
        try:
            meta = {
                "slate_day": None,
                "tweet_date": dt.date.today().strftime("%b %d").replace(" 0", " "),
                "n_games": 0,
                "counts": {},
                "matchups": {},
            }
            meta_attr = py_html.escape(json.dumps(meta, ensure_ascii=False))
            st.markdown(
                f"<div id='tweet-meta' data-meta='{meta_attr}' style='display:none;'></div>",
                unsafe_allow_html=True,
            )
        except Exception:
            pass
        return

    default_day = None
    try:
        default_day = st.query_params.get("day")
    except Exception:
        default_day = None

    left, right = st.columns([1.05, 1.0], gap="large")
    with left:
        selected = render_chart(
            df=df,
            date_options=date_options,
            date_to_label=date_to_label,
            show_day_selector=True,
            selected_date=None,
            default_day=default_day,
        )
        render_recommendations_module(df, slate_day=selected, wrapper_class="recs-mobile")
    with right:
        render_recommendations_module(df, slate_day=selected, wrapper_class="recs-desktop")
        st.markdown("<div style='font-size:22px; font-weight:950; margin-top:10px;'>All Games</div>", unsafe_allow_html=True)
        st.divider()
        render_table(df=df, df_dates=df_dates, date_options=date_options, selected_day=selected)

    # Hidden machine-readable metadata so the bot can align tweet text
    # with the exact slate rendered on the deployed dashboard.
    try:
        slate = selected if (selected in (date_options or [])) else (date_options[0] if date_options else None)
        if slate:
            df_slate = df[df["Local date"].astype(str) == slate].copy()
        else:
            df_slate = df.copy()

        counts: dict[str, int] = {}
        if not df_slate.empty and "Region" in df_slate.columns:
            vc = df_slate["Region"].astype(str).value_counts()
            counts = {str(k): int(v) for k, v in vc.items()}

        slate_date = None
        if not df_slate.empty and "Local date" in df_slate.columns:
            try:
                slate_date = df_slate["Local date"].dropna().iloc[0]
            except Exception:
                slate_date = None

        tweet_date = None
        if isinstance(slate_date, dt.date):
            tweet_date = slate_date.strftime("%b %d").replace(" 0", " ")
        elif isinstance(slate, str) and len(slate) == 10:
            try:
                y, m, d = (int(x) for x in slate.split("-"))
                tweet_date = dt.date(y, m, d).strftime("%b %d").replace(" 0", " ")
            except Exception:
                tweet_date = None

        matchups: dict[str, list[str]] = {}
        if not df_slate.empty and {"Region", "Matchup"}.issubset(df_slate.columns):
            for region, grp in df_slate.groupby(df_slate["Region"].astype(str)):
                matchups[str(region)] = [str(x) for x in grp["Matchup"].astype(str).tolist()]

        meta = {
            "slate_day": slate,
            "tweet_date": tweet_date,
            "n_games": int(len(df_slate)) if df_slate is not None else 0,
            "counts": counts,
            "matchups": matchups,
        }
        meta_attr = py_html.escape(json.dumps(meta, ensure_ascii=False))
        st.markdown(f"<div id='tweet-meta' data-meta='{meta_attr}' style='display:none;'></div>", unsafe_allow_html=True)
    except Exception:
        pass


def render_chart_page() -> None:
    inject_base_css()
    df, _, date_options, date_to_label = build_dashboard_frames()
    if df.empty:
        st.warning("No NBA regular season or playoff games found. Enjoy the break!")
        return
    selected = st.query_params.get("day")
    render_chart(
        df=df,
        date_options=date_options,
        date_to_label=date_to_label,
        show_day_selector=False,
        selected_date=selected,
        default_day=None,
    )


def render_table_page() -> None:
    inject_base_css()
    df, df_dates, date_options, _ = build_dashboard_frames()
    if df.empty:
        st.warning("No NBA regular season or playoff games found. Enjoy the break!")
        return
    render_table(df=df, df_dates=df_dates, date_options=date_options, selected_day=None)
