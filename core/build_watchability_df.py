from __future__ import annotations

import datetime as dt
import json
from typing import Any

import concurrent.futures as cf
import os
import pandas as pd
from dateutil import parser as dtparser
from dateutil import tz

from core.health_espn import PlayerImpact, compute_team_player_impacts, injury_weight
from core.http_cache import get_json_cached
from core.importance import compute_importance_detail_map
from core.odds_api import fetch_nba_spreads_window
from core.schedule_espn import fetch_games_for_date
from core.standings import _normalize_team_name, get_record, get_win_pct
from core.standings_espn import fetch_team_standings_detail_maps
from core.team_meta import get_logo_url
from core.watchability_v2_params import (
    INJURY_OVERALL_IMPORTANCE_WEIGHT,
    KEY_INJURY_IMPACT_SHARE_THRESHOLD,
    STAR_AST_WEIGHT,
    STAR_DENOM,
    STAR_REB_WEIGHT,
    STAR_WINPCT_BUMP,
)

import core.watchability as watch


def _parse_score(x: Any) -> int | None:
    try:
        if x is None:
            return None
        return int(float(x))
    except Exception:
        return None


def _normalize_status_for_display(status: str | None) -> str:
    s = (status or "").strip()
    if not s:
        return "Available"
    if s.upper() == "GTD":
        return "GTD"
    return s


def _load_espn_game_map(local_dates_iso: list[str]) -> dict[tuple[str, str, str], dict]:
    """
    Map (date_iso, home_team_key, away_team_key) -> dict with:
      - state ('pre'/'in'/'post')
      - game_id (str)
      - home_score (int|None)
      - away_score (int|None)
      - time_remaining (str|None) e.g. '5:32 Q3'

    Note: ESPN's scoreboard "dates=" is not always aligned with PT local dates for late games,
    so we fetch an extra day window and map events back into PT dates.
    """
    out: dict[tuple[str, str, str], dict] = {}
    if not local_dates_iso:
        return out

    targets = set(str(x) for x in local_dates_iso)
    local_tz = tz.gettz("America/Los_Angeles")

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


def _load_espn_game_injury_report_map(game_ids: list[str]) -> dict[str, dict[str, dict[str, str]]]:
    """
    Returns: game_id -> team_key -> athlete_id -> status.
    """
    out: dict[str, dict[str, dict[str, str]]] = {}
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"

    ids = [str(g).strip() for g in game_ids if str(g).strip()]
    if not ids:
        return out

    max_workers = int(os.getenv("NBA_WATCH_SUMMARY_WORKERS", "8"))

    def _fetch_one(gid_s: str) -> tuple[str, dict[str, dict[str, str]] | None]:
        try:
            resp = get_json_cached(
                url,
                params={"event": gid_s},
                namespace="espn",
                cache_key=f"summary:{gid_s}",
                ttl_seconds=10 * 60,
                timeout_seconds=12,
            )
            data = resp.data
        except Exception:
            return gid_s, None

        injuries = data.get("injuries") if isinstance(data, dict) else None
        if not isinstance(injuries, list):
            return gid_s, {}

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
                        fs = (
                            fantasy.get("displayDescription")
                            or fantasy.get("description")
                            or fantasy.get("abbreviation")
                        )

                chosen = _normalize_status_for_display(
                    str(fs) if fs else (str(status) if status else "")
                )
                m[athlete_id] = chosen
            by_team[team_key] = m

        return gid_s, by_team

    # Parallelize per-game summary fetches; this is the biggest cold-load hotspot.
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch_one, gid) for gid in ids]
        for fut in cf.as_completed(futures):
            gid_s, by_team = fut.result()
            if by_team is None:
                continue
            out[gid_s] = by_team

    return out


def build_watchability_df(
    *,
    days_ahead: int = 2,
    tz_name: str = "America/Los_Angeles",
    include_post: bool = False,
) -> pd.DataFrame:
    """
    Build the per-game DataFrame used by the dashboard and downstream scripts.
    """
    games = fetch_nba_spreads_window(days_ahead=days_ahead)
    winpct_map, record_map, detail_map = fetch_team_standings_detail_maps()
    importance_detail = compute_importance_detail_map(detail_map)

    local_tz = tz.gettz(tz_name)
    et_tz = tz.gettz("America/New_York")

    team_names = sorted({g.home_team for g in games} | {g.away_team for g in games})
    # Compute player impact shares lazily only for teams that have injuries in a specific matchup.
    # This is a major performance win vs. computing for every team on every refresh.
    team_name_by_key = { _normalize_team_name(n): n for n in team_names }
    team_impacts: dict[str, list[PlayerImpact]] = {}

    rows: list[dict[str, Any]] = []
    for g in games:
        w_home_raw = get_win_pct(g.home_team, winpct_map, default=0.5)
        w_away_raw = get_win_pct(g.away_team, winpct_map, default=0.5)

        home_key = _normalize_team_name(g.home_team)
        away_key = _normalize_team_name(g.away_team)

        imp_home = float(importance_detail.get(home_key, {}).get("importance", 0.1))
        imp_away = float(importance_detail.get(away_key, {}).get("importance", 0.1))
        game_importance = 0.5 * (imp_home + imp_away)

        seed_radius_home = importance_detail.get(home_key, {}).get("seed_radius")
        seed_radius_away = importance_detail.get(away_key, {}).get("seed_radius")
        playoff_radius_home = importance_detail.get(home_key, {}).get("playoff_radius")
        playoff_radius_away = importance_detail.get(away_key, {}).get("playoff_radius")

        w_home_rec, l_home_rec = get_record(g.home_team, record_map)
        w_away_rec, l_away_rec = get_record(g.away_team, record_map)
        home_record = "—" if (w_home_rec is None or l_home_rec is None) else f"{w_home_rec}-{l_home_rec}"
        away_record = "—" if (w_away_rec is None or l_away_rec is None) else f"{w_away_rec}-{l_away_rec}"

        abs_spread = None if g.home_spread is None else abs(float(g.home_spread))

        dt_et = None
        if g.commence_time_utc:
            dt_utc = dtparser.isoparse(g.commence_time_utc)
            dt_local = dt_utc.astimezone(local_tz) if local_tz else dt_utc
            dt_et = dt_utc.astimezone(et_tz) if et_tz else None
            local_date = dt_local.date()
            day_name = dt_local.strftime("%A")
            tip_local = dt_local.strftime("%a %I:%M %p")
            tip_short = dt_local.strftime("%a %I%p").replace(" 0", " ")
            tip_et = dt_et.strftime("%a %I:%M %p") if dt_et else "Unknown"
        else:
            dt_local = None
            local_date = None
            day_name = "Unknown"
            tip_local = "Unknown"
            tip_short = "?"
            tip_et = "Unknown"

        rows.append(
            {
                "Tip (PT)": tip_local,
                "Tip (ET)": tip_et,
                "Tip short": tip_short,
                "Tip dt (PT)": dt_local,
                "Tip dt (ET)": dt_et,
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
                "Team quality": None,
                "Closeness": None,
                "Importance": game_importance,
                "Importance (home)": imp_home,
                "Importance (away)": imp_away,
                "Seed radius (home)": seed_radius_home,
                "Seed radius (away)": seed_radius_away,
                "Playoff radius (home)": playoff_radius_home,
                "Playoff radius (away)": playoff_radius_away,
                "Uavg": None,
                "aWI": None,
                "Region": None,
                "Spread source": g.spread_source,
                "Win% (away raw)": float(w_away_raw),
                "Win% (home raw)": float(w_home_raw),
                "Adj win% (away)": float(w_away_raw),
                "Adj win% (home)": float(w_home_raw),
                "Health (away)": 1.0,
                "Health (home)": 1.0,
                "Away Key Injuries": "",
                "Home Key Injuries": "",
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df_dates = (
        df.dropna(subset=["Local date"])
        .sort_values("Local date")
        .loc[:, ["Local date", "Day"]]
        .drop_duplicates()
    )
    date_options = [d.isoformat() for d in df_dates["Local date"].tolist()]

    game_map = _load_espn_game_map(date_options)

    if date_options:

        def _lookup_game(r, key: str):
            iso = str(r["Local date"])
            home = _normalize_team_name(str(r["Home team"]))
            away = _normalize_team_name(str(r["Away team"]))
            rec = game_map.get((iso, home, away))
            if not rec:
                return None
            return rec.get(key)

        df["Status"] = df.apply(lambda r: _lookup_game(r, "state") or "pre", axis=1)
        df["ESPN game id"] = df.apply(lambda r: _lookup_game(r, "game_id"), axis=1)
        df["Away score"] = df.apply(lambda r: _lookup_game(r, "away_score"), axis=1)
        df["Home score"] = df.apply(lambda r: _lookup_game(r, "home_score"), axis=1)
        df["Time remaining"] = df.apply(lambda r: _lookup_game(r, "time_remaining"), axis=1)
    else:
        df["Status"] = "pre"
        df["ESPN game id"] = None
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

    if not include_post:
        df = df[df["Status"] != "post"].copy()

    game_ids = sorted({str(x) for x in df["ESPN game id"].dropna().tolist() if str(x).strip()})
    injury_reports = _load_espn_game_injury_report_map(game_ids) if game_ids else {}

    teams_with_injuries: set[str] = set()
    for _, by_team in injury_reports.items():
        for team_key, inj in (by_team or {}).items():
            if isinstance(inj, dict) and inj:
                teams_with_injuries.add(str(team_key))

    # Star/top-scorer map needed for all teams; compute impacts once per team (cached per-athlete stats).
    # Keep this parallelized and rely on the disk HTTP cache to make warm loads fast.
    star_workers = int(os.getenv("NBA_WATCH_STAR_WORKERS", "8"))
    # team_key -> (athlete_id, name, star_raw, star_sum)
    top_scorer: dict[str, tuple[str, str, float, float]] = {}

    def _fetch_team(team_key: str, team_name: str) -> tuple[str, list[PlayerImpact]]:
        try:
            return team_key, compute_team_player_impacts(team_name)
        except Exception:
            return team_key, []

    with cf.ThreadPoolExecutor(max_workers=star_workers) as ex:
        futures = [
            ex.submit(_fetch_team, team_key, team_name_by_key.get(team_key, team_key))
            for team_key in sorted(team_name_by_key.keys())
        ]
        for fut in cf.as_completed(futures):
            k, players = fut.result()
            # Keep the full list only if we might need it for injury penalty breakdown.
            if k in teams_with_injuries:
                team_impacts[k] = players
            if players:
                def _star_sum(pl: PlayerImpact) -> float:
                    return (
                        float(pl.points_per_game)
                        + float(STAR_REB_WEIGHT) * float(pl.rebounds_per_game)
                        + float(STAR_AST_WEIGHT) * float(pl.assists_per_game)
                        + float(pl.steals_per_game)
                        + float(pl.blocks_per_game)
                    )

                best = max(players, key=_star_sum)
                ssum = _star_sum(best)
                denom = float(STAR_DENOM) if float(STAR_DENOM) else 1.0
                sraw = float(ssum) / denom
                sraw = sraw * sraw * sraw
                top_scorer[k] = (best.athlete_id, best.name, sraw, ssum)

    def _team_key_injuries_and_health(team_key: str, game_id: str | None) -> tuple[float, str]:
        players = team_impacts.get(team_key, []) or []
        by_team = injury_reports.get(str(game_id or ""), {}).get(team_key, {})

        if not by_team:
            return 1.0, ""

        penalty = 0.0
        injured_players: list[tuple[float, float, str]] = []
        for p in players:
            pid = str(p.athlete_id)
            name = str(p.name)
            share = float(p.impact_share)
            raw = float(p.raw_impact)
            st = by_team.get(pid)
            if not st:
                continue
            st_norm = _normalize_status_for_display(st)
            penalty += float(injury_weight(st_norm)) * float(share)
            injured_players.append((raw, share, f"{name}: {st_norm}"))

        health = 1.0 - float(INJURY_OVERALL_IMPORTANCE_WEIGHT) * penalty
        health = max(0.0, min(1.0, float(health)))
        injured_players.sort(key=lambda x: x[0], reverse=True)
        key_injuries = [
            s for _, share, s in injured_players if float(share) >= KEY_INJURY_IMPACT_SHARE_THRESHOLD
        ]
        return health, ", ".join(key_injuries)

    injury_info_cache: dict[tuple[str, str], tuple[float, str]] = {}

    def _memo_team_injury_info(team_key: str, game_id: str | None) -> tuple[float, str]:
        k = (team_key, str(game_id or ""))
        if k in injury_info_cache:
            return injury_info_cache[k]
        v = _team_key_injuries_and_health(team_key, game_id)
        injury_info_cache[k] = v
        return v

    df["Health (away)"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Away team"]), r.get("ESPN game id"))[0],
        axis=1,
    )
    df["Health (home)"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Home team"]), r.get("ESPN game id"))[0],
        axis=1,
    )
    df["Away Key Injuries"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Away team"]), r.get("ESPN game id"))[1] or "",
        axis=1,
    )
    df["Home Key Injuries"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Home team"]), r.get("ESPN game id"))[1] or "",
        axis=1,
    )

    # Baseline adjusted win% prior to star bump (health-adjusted only).
    df["Adj win% (away)"] = df["Win% (away raw)"].astype(float) * df["Health (away)"].astype(float)
    df["Adj win% (home)"] = df["Win% (home raw)"].astype(float) * df["Health (home)"].astype(float)
    df["Adj win% (away) pre-star"] = df["Adj win% (away)"].astype(float)
    df["Adj win% (home) pre-star"] = df["Adj win% (home)"].astype(float)
    df["Avg adj win% pre-star"] = 0.5 * (df["Adj win% (away) pre-star"] + df["Adj win% (home) pre-star"])

    def _star_factor(team_key: str, game_id: str | None) -> float:
        top = top_scorer.get(team_key)
        if not top:
            return 0.0
        athlete_id, _, star_raw, _ = top
        # If the top scorer appears in the injury report, apply availability scaling.
        status = injury_reports.get(str(game_id or ""), {}).get(team_key, {}).get(str(athlete_id))
        status_norm = _normalize_status_for_display(status) if status else "Available"
        availability = max(0.0, 1.0 - float(injury_weight(status_norm)))
        return float(STAR_WINPCT_BUMP) * float(star_raw) * availability

    def _star_player_name(team_key: str) -> str:
        top = top_scorer.get(team_key)
        if not top:
            return ""
        _, name, _, _ = top
        return str(name)

    def _star_player_raw(team_key: str) -> float:
        top = top_scorer.get(team_key)
        if not top:
            return 0.0
        _, _, star_raw, _ = top
        return float(star_raw)

    def _star_display(team_key: str, game_id: str | None) -> str:
        name = _star_player_name(team_key)
        if not name:
            return ""
        f = _star_factor(team_key, game_id)
        # Show as percentage points added to win% for readability.
        return f"{name} +{(100.0 * float(f)):.1f}%"

    df["Star factor (away)"] = df.apply(
        lambda r: _star_factor(_normalize_team_name(r["Away team"]), r.get("ESPN game id")),
        axis=1,
    )
    df["Star factor (home)"] = df.apply(
        lambda r: _star_factor(_normalize_team_name(r["Home team"]), r.get("ESPN game id")),
        axis=1,
    )
    df["Away Star Player"] = df.apply(lambda r: _star_player_name(_normalize_team_name(r["Away team"])), axis=1)
    df["Home Star Player"] = df.apply(lambda r: _star_player_name(_normalize_team_name(r["Home team"])), axis=1)
    df["Away Star Raw"] = df.apply(lambda r: _star_player_raw(_normalize_team_name(r["Away team"])), axis=1)
    df["Home Star Raw"] = df.apply(lambda r: _star_player_raw(_normalize_team_name(r["Home team"])), axis=1)
    df["Away Star Factor"] = df.apply(
        lambda r: _star_display(_normalize_team_name(r["Away team"]), r.get("ESPN game id")),
        axis=1,
    )
    df["Home Star Factor"] = df.apply(
        lambda r: _star_display(_normalize_team_name(r["Home team"]), r.get("ESPN game id")),
        axis=1,
    )

    # Add star factor as a small additive bump to win% (then clip to [0,1]).
    df["Adj win% (away)"] = (df["Adj win% (away)"].astype(float) + df["Star factor (away)"].astype(float)).clip(0.0, 1.0)
    df["Adj win% (home)"] = (df["Adj win% (home)"].astype(float) + df["Star factor (home)"].astype(float)).clip(0.0, 1.0)
    df["Avg adj win% post-star"] = 0.5 * (df["Adj win% (away)"] + df["Adj win% (home)"])

    def _compute_watchability_row(r) -> pd.Series:
        w = watch.compute_watchability(
            float(r["Adj win% (home)"]),
            float(r["Adj win% (away)"]),
            r["|spread|"],
        )
        return pd.Series(
            {
                "Team quality": w.team_quality,
                "Closeness": w.closeness,
                "Uavg": w.uavg,
                "aWI": w.awi,
                "Region": w.label,
            }
        )

    df[["Team quality", "Closeness", "Uavg", "aWI", "Region"]] = df.apply(_compute_watchability_row, axis=1)
    df = df.sort_values("aWI", ascending=False).reset_index(drop=True)
    return df


def build_watchability_sources_summary(df: pd.DataFrame) -> str:
    """
    Optional sources blob for logging.
    """
    spread_sources = sorted({str(x) for x in df.get("Spread source", pd.Series(dtype=str)).dropna().tolist()})
    payload = {
        "odds_sources": spread_sources,
        "injuries_source": "ESPN summary (event)",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return json.dumps(payload, sort_keys=True)
