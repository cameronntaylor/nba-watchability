from __future__ import annotations

import datetime as dt
import os
from typing import Any

import pandas as pd
from dateutil import parser as dtparser
from dateutil import tz

from core.forecast_config import load_forecast_config
from core.forecast_features import build_team_recent_feature_map
from core.forecast_spread import predict_home_spread
from core.http_cache import get_json_cached
from core.odds_api import fetch_nba_spreads_window
from core.schedule_espn import fetch_games_for_date
from core.standings import _normalize_team_name, get_record, get_win_pct
from core.standings_espn import fetch_team_standings_detail_maps
from core.team_meta import get_logo_url, get_team_abbr
from core.build_watchability_df import (
    _map_watch_provider_label,
    _load_espn_game_summary_maps,
    _load_nba_schedule_game_id_map_by_pt_date,
)
import core.watchability as watch


def _fmt_tip_short(dt_local: dt.datetime | None) -> str:
    if not dt_local:
        return "?"
    return dt_local.strftime("%a %I%p").replace(" 0", " ")


def _build_odds_map(days_ahead: int, local_tz) -> dict[tuple[str, str, str], Any]:
    out: dict[tuple[str, str, str], Any] = {}
    try:
        odds = fetch_nba_spreads_window(days_ahead=days_ahead)
    except Exception:
        return out

    for g in odds:
        try:
            t_utc = dtparser.isoparse(str(g.commence_time_utc))
            t_local = t_utc.astimezone(local_tz)
            d = t_local.date().isoformat()
        except Exception:
            continue
        k = (d, _normalize_team_name(g.home_team), _normalize_team_name(g.away_team))
        out[k] = g
    return out


def _team_feature(team_features: dict[str, dict], team_key: str, default_health: float, default_star: float) -> dict:
    base = team_features.get(team_key) or {}
    return {
        "avg_health_7d": float(base.get("avg_health_7d", default_health)),
        "avg_star_factor_7d": float(base.get("avg_star_factor_7d", default_star)),
        "avg_team_spread_7d": float(base.get("avg_team_spread_7d", 0.0)),
        "n_games": int(base.get("n_games", 0) or 0),
    }


def _load_nba_provider_map_by_game_id() -> dict[str, str]:
    """
    Map nba_game_id -> simplified provider label from nba.com schedule broadcasters.
    """
    out: dict[str, str] = {}
    url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
    try:
        resp = get_json_cached(
            url,
            namespace="nba",
            cache_key="nba_scheduleLeagueV2",
            ttl_seconds=24 * 60 * 60,
            timeout_seconds=15,
        )
        data = resp.data
    except Exception:
        return out

    game_dates = None
    if isinstance(data, dict):
        league = data.get("leagueSchedule")
        if isinstance(league, dict):
            game_dates = league.get("gameDates")
    if not isinstance(game_dates, list):
        return out

    for gd in game_dates:
        if not isinstance(gd, dict):
            continue
        games = gd.get("games")
        if not isinstance(games, list):
            continue
        for g in games:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("gameId") or "").strip()
            if not gid:
                continue
            broadcasters = g.get("broadcasters")
            names: list[str] = []
            if isinstance(broadcasters, dict):
                for k in (
                    "nationalBroadcasters",
                    "nationalOttBroadcasters",
                    "homeTvBroadcasters",
                    "homeOttBroadcasters",
                    "awayTvBroadcasters",
                    "awayOttBroadcasters",
                ):
                    arr = broadcasters.get(k)
                    if not isinstance(arr, list):
                        continue
                    for b in arr:
                        if not isinstance(b, dict):
                            continue
                        for f in ("broadcasterDisplay", "broadcasterAbbreviation"):
                            v = b.get(f)
                            if isinstance(v, str) and v.strip():
                                names.append(v.strip())
            provider = _map_watch_provider_label(names)
            out[gid] = provider
    return out


def build_watchability_forecast_df(
    *,
    days_ahead: int | None = None,
    tz_name: str = "America/Los_Angeles",
    include_post: bool = False,
    cfg_path: str | None = None,
) -> pd.DataFrame:
    cfg = load_forecast_config(cfg_path)
    days = int(days_ahead if days_ahead is not None else cfg.days_ahead)
    days = max(1, days)

    local_tz = tz.gettz(tz_name)
    et_tz = tz.gettz("America/New_York")
    now_pt = dt.datetime.now(tz=local_tz)

    winpct_map, record_map, _detail = fetch_team_standings_detail_maps()

    # default star in win% units from TQ points.
    default_star_factor = float(cfg.default_star_tq_points) / 100.0
    team_features = build_team_recent_feature_map(
        lookback_days=int(cfg.lookback_days),
        default_health=float(cfg.default_health),
        default_star_factor=float(default_star_factor),
        min_games_for_team_spread_avg=int(cfg.min_games_for_team_spread_avg),
        logs_dir=os.path.join("output", "logs"),
        now_pt=now_pt,
    )

    odds_map = _build_odds_map(days_ahead=days, local_tz=local_tz)

    rows: list[dict[str, Any]] = []
    start_date = now_pt.date()
    for i in range(days):
        d = start_date + dt.timedelta(days=i)
        try:
            games = fetch_games_for_date(d)
        except Exception:
            continue

        for g in games:
            state = str(g.get("state") or "pre")
            if not include_post and state == "post":
                continue

            home = str(g.get("home_team") or "").strip()
            away = str(g.get("away_team") or "").strip()
            if not home or not away:
                continue

            home_key = _normalize_team_name(home)
            away_key = _normalize_team_name(away)

            # Time handling.
            dt_utc = None
            dt_local = None
            dt_et = None
            try:
                dt_utc = dtparser.isoparse(str(g.get("start_time_utc")))
                dt_local = dt_utc.astimezone(local_tz)
                dt_et = dt_utc.astimezone(et_tz)
            except Exception:
                pass

            local_date = dt_local.date() if isinstance(dt_local, dt.datetime) else d
            day_name = local_date.strftime("%A")
            tip_local = dt_local.strftime("%a %I:%M %p") if isinstance(dt_local, dt.datetime) else "Unknown"
            tip_et = dt_et.strftime("%a %I:%M %p") if isinstance(dt_et, dt.datetime) else "Unknown"
            tip_short = _fmt_tip_short(dt_local)

            home_wp = float(get_win_pct(home, winpct_map, default=0.5))
            away_wp = float(get_win_pct(away, winpct_map, default=0.5))
            w_home_rec, l_home_rec = get_record(home, record_map)
            w_away_rec, l_away_rec = get_record(away, record_map)
            home_record = "—" if (w_home_rec is None or l_home_rec is None) else f"{w_home_rec}-{l_home_rec}"
            away_record = "—" if (w_away_rec is None or l_away_rec is None) else f"{w_away_rec}-{l_away_rec}"

            hk = _team_feature(team_features, home_key, float(cfg.default_health), float(default_star_factor))
            ak = _team_feature(team_features, away_key, float(cfg.default_health), float(default_star_factor))

            odds_key = (local_date.isoformat(), home_key, away_key)
            odds = odds_map.get(odds_key)

            if odds is not None and odds.home_spread is not None:
                home_spread = float(odds.home_spread)
                spread_source = str(odds.spread_source or "odds")
                spread_mode = "odds"
            else:
                home_spread = predict_home_spread(
                    home_wp=home_wp,
                    away_wp=away_wp,
                    home_avg_spread_7d=float(hk["avg_team_spread_7d"]),
                    away_avg_spread_7d=float(ak["avg_team_spread_7d"]),
                    a1=float(cfg.a1),
                    a2=float(cfg.a2),
                    home_intercept=float(cfg.home_intercept),
                )
                spread_source = "forecast_model"
                spread_mode = "forecast"

            # Forecasted adjusted win%.
            adj_home = max(0.0, min(1.0, home_wp * float(hk["avg_health_7d"]) + float(hk["avg_star_factor_7d"])))
            adj_away = max(0.0, min(1.0, away_wp * float(ak["avg_health_7d"]) + float(ak["avg_star_factor_7d"])))

            w = watch.compute_watchability(adj_home, adj_away, abs(float(home_spread)))

            away_score = g.get("away_score")
            home_score = g.get("home_score")
            tr = g.get("time_remaining")
            is_live = state == "in"
            if is_live:
                if away_score is not None and home_score is not None:
                    tip_display = f"🚨 {int(float(away_score))}-{int(float(home_score))}{(' ' + str(tr)) if tr else ''}"
                else:
                    tip_display = f"🚨 LIVE{(' ' + str(tr)) if tr else ''}"
            else:
                tip_display = tip_short if "PT" in tip_short else f"{tip_short} PT"

            rows.append(
                {
                    "Tip (PT)": tip_local,
                    "Tip (ET)": tip_et,
                    "Tip short": tip_short,
                    "Tip dt (PT)": dt_local,
                    "Tip dt (ET)": dt_et,
                    "Tip dt (UTC)": dt_utc,
                    "Local date": local_date,
                    "Day": day_name,
                    "Matchup": f"{away} @ {home}",
                    "Away team": away,
                    "Home team": home,
                    "Away logo": get_logo_url(away) or "",
                    "Home logo": get_logo_url(home) or "",
                    "Home spread": float(home_spread),
                    "|spread|": abs(float(home_spread)),
                    "Home spread effective": float(home_spread),
                    "|spread effective|": abs(float(home_spread)),
                    "Home spread close": None,
                    "Minutes remaining": None,
                    "a_close(t)": 0.0,
                    "a_live(t)": 1.0,
                    "Record (away)": away_record,
                    "Record (home)": home_record,
                    "Spread source": spread_source,
                    "Spread mode": spread_mode,
                    "Win% (away raw)": away_wp,
                    "Win% (home raw)": home_wp,
                    "Adj win% (away)": adj_away,
                    "Adj win% (home)": adj_home,
                    "Adj win% (away) pre-star": away_wp * float(ak["avg_health_7d"]),
                    "Adj win% (home) pre-star": home_wp * float(hk["avg_health_7d"]),
                    "Avg adj win% pre-star": 0.5 * (
                        away_wp * float(ak["avg_health_7d"]) + home_wp * float(hk["avg_health_7d"])
                    ),
                    "Avg adj win% post-star": 0.5 * (adj_away + adj_home),
                    "Health (away)": float(ak["avg_health_7d"]),
                    "Health (home)": float(hk["avg_health_7d"]),
                    "Star factor (away)": float(ak["avg_star_factor_7d"]),
                    "Star factor (home)": float(hk["avg_star_factor_7d"]),
                    "Away Star Player": "",
                    "Home Star Player": "",
                    "Away Star Raw": 0.0,
                    "Home Star Raw": 0.0,
                    "Team quality pre-star": watch.team_quality(
                        home_wp * float(hk["avg_health_7d"]), away_wp * float(ak["avg_health_7d"])
                    ),
                    "Team Quality bump (away)": float(ak["avg_star_factor_7d"]) * 100.0,
                    "Team Quality bump (home)": float(hk["avg_star_factor_7d"]) * 100.0,
                    "Away Star Factor": "",
                    "Home Star Factor": "",
                    "Away Key Injuries": "",
                    "Home Key Injuries": "",
                    "Away injuries detail JSON": "[]",
                    "Home injuries detail JSON": "[]",
                    "Team quality": float(w.team_quality),
                    "Team Quality": float(w.team_quality),
                    "Closeness": float(w.closeness),
                    "Competitiveness": float(w.closeness),
                    "Uavg": float(w.uavg),
                    "aWI": float(w.awi),
                    "Region": str(w.label),
                    "Status": state,
                    "Is live": bool(is_live),
                    "ESPN game id": str(g.get("game_id") or ""),
                    "Away score": away_score,
                    "Home score": home_score,
                    "Time remaining": tr,
                    "Tip display": tip_display,
                    "Where to watch URL": "",
                    "Where to watch provider": "League Pass",
                    "Forecast": True,
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Populate "Where to watch" context for forecast rows too.
    game_ids = sorted({str(x) for x in df.get("ESPN game id", pd.Series(dtype=object)).dropna().tolist() if str(x).strip()})
    _injury_reports, watch_providers, _close_spreads = (
        _load_espn_game_summary_maps(game_ids) if game_ids else ({}, {}, {})
    )

    pt_dates_iso = {str(d) for d in df.get("Local date", pd.Series(dtype=object)).dropna().tolist() if str(d).strip()}
    nba_game_id_map = _load_nba_schedule_game_id_map_by_pt_date(pt_dates_iso, pt_tz_name=tz_name)
    nba_provider_by_gid = _load_nba_provider_map_by_game_id()

    def _nba_tricode(team_name: str) -> str:
        abbr = (get_team_abbr(team_name) or "").upper()
        if abbr == "NO":
            return "NOP"
        if abbr == "UTAH":
            return "UTA"
        return abbr

    def _nba_game_url_row(r) -> str:
        pt_date = r.get("Local date")
        if pt_date is None:
            return ""
        home_abbr = _nba_tricode(str(r.get("Home team", ""))).lower()
        away_abbr = _nba_tricode(str(r.get("Away team", ""))).lower()
        if not (home_abbr and away_abbr):
            return ""
        gid = nba_game_id_map.get((str(pt_date), home_abbr, away_abbr))
        if not gid:
            return ""
        return f"https://www.nba.com/game/{away_abbr}-vs-{home_abbr}-{gid}"

    def _provider_row(r) -> str:
        # Prefer ESPN summary provider when specific; fallback to nba.com schedule provider.
        gid_espn = str(r.get("ESPN game id") or "").strip()
        p = watch_providers.get(gid_espn, "League Pass") if gid_espn else "League Pass"
        if p and p != "League Pass":
            return p

        pt_date = r.get("Local date")
        if pt_date is None:
            return "League Pass"
        home_abbr = _nba_tricode(str(r.get("Home team", ""))).lower()
        away_abbr = _nba_tricode(str(r.get("Away team", ""))).lower()
        if not (home_abbr and away_abbr):
            return "League Pass"
        gid_nba = nba_game_id_map.get((str(pt_date), home_abbr, away_abbr))
        if not gid_nba:
            return "League Pass"
        return nba_provider_by_gid.get(str(gid_nba), "League Pass")

    df["Where to watch URL"] = df.apply(_nba_game_url_row, axis=1)
    df["Where to watch provider"] = df.apply(_provider_row, axis=1)

    df = df.sort_values(["Local date", "Tip dt (PT)", "aWI"], ascending=[True, True, False]).reset_index(drop=True)
    return df
