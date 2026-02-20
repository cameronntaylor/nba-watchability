from __future__ import annotations

import datetime as dt
import json
import re
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
from core.team_meta import get_team_abbr
from core.results_espn import extract_closing_spreads
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
    m = re.search(r"(\\d{1,2})[:.](\\d{1,2})\\s*Q(\\d)", s)
    if not m:
        return None, None
    mm = int(m.group(1))
    ss = int(m.group(2))
    q = int(m.group(3))
    return q, mm * 60 + ss


def _minutes_remaining_from_time_remaining(tr: str | None) -> float | None:
    q, sec = _parse_time_remaining(tr)
    if q is None or sec is None:
        return None
    mins_in_current = float(sec) / 60.0
    quarters_left_after = max(0, 4 - int(q))
    return quarters_left_after * 12.0 + mins_in_current


def _live_weight_a(minutes_remaining: float | None) -> float:
    """
    a(t) = 1 - (t mins remaining)/48, clamped to [0, 1]
    """
    if minutes_remaining is None:
        return 0.0
    try:
        t = float(minutes_remaining)
    except Exception:
        return 0.0
    a = 1.0 - (t / 48.0)
    return float(max(0.0, min(1.0, a)))


def _close_spread_store_path() -> str:
    return os.getenv(
        "NBA_WATCH_CLOSE_SPREAD_STORE",
        os.path.join("output", "state", "close_spreads.json"),
    )


def _load_close_spread_store(path: str) -> dict[str, float]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        out: dict[str, float] = {}
        for k, v in data.items():
            try:
                if k is None:
                    continue
                out[str(k)] = float(v)
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _save_close_spread_store(path: str, data: dict[str, float]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        return


def _normalize_status_for_display(status: str | None) -> str:
    s = (status or "").strip()
    if not s:
        return "Available"
    if s.upper() == "OUT":
        return "Out"
    if s.upper() == "GTD":
        return "GTD"
    if s.lower() in {"day-to-day", "day to day", "daytoday", "dtd"}:
        return "GTD"
    return s


def _normalize_player_name(name: str) -> str:
    """
    Normalize player names to improve cross-endpoint matching.
    """
    n = (name or "").strip().lower()
    if not n:
        return ""
    # Remove punctuation, keep spaces.
    n = re.sub(r"[^a-z0-9\\s]", " ", n)
    # Collapse suffixes.
    parts = [p for p in n.split() if p not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    return " ".join(parts)


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


def _load_espn_league_injuries_by_team(*, ttl_seconds: int = 10 * 60) -> dict[str, dict[str, dict[str, str]]]:
    """
    Returns:
      team_key -> {
        "by_id": {athlete_id: fantasy_status_abbr},
        "by_name": {normalized_name: fantasy_status_abbr},
        "detail_by_id": {athlete_id: {"abbr": str, "shortComment": str, "longComment": str}},
        "detail_by_name": {normalized_name: {"abbr": str, "shortComment": str, "longComment": str}},
      }

    Uses ESPN's league injuries endpoint (more comprehensive than per-game summary injuries list):
      https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries
    """
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
    try:
        resp = get_json_cached(
            url,
            namespace="espn",
            cache_key="league_injuries",
            ttl_seconds=ttl_seconds,
            timeout_seconds=30,
        )
        data = resp.data
    except Exception:
        return {}

    blocks = data.get("injuries") if isinstance(data, dict) else None
    if not isinstance(blocks, list):
        return {}

    def _athlete_id_from_links(athlete: dict[str, Any]) -> str | None:
        athlete_id = athlete.get("id")
        if athlete_id is not None and str(athlete_id).strip():
            return str(athlete_id).strip()
        links = athlete.get("links")
        if not isinstance(links, list):
            return None
        for link in links:
            if not isinstance(link, dict):
                continue
            href = str(link.get("href") or "")
            # Example: https://www.espn.com/nba/player/_/id/3102531/kristaps-porzingis
            m = None
            if "/id/" in href:
                import re
                m = re.search(r"/id/(\d+)", href)
                if not m:
                    m = re.search(r"/id/(\d+)(?:/|$)", href)
            if m:
                return str(m.group(1))
        return None

    def _parse_fantasy_abbr(inj: dict[str, Any]) -> str:
        # Display label should match details.fantasyStatus.abbreviation when possible.
        details = inj.get("details")
        if isinstance(details, dict):
            fantasy = details.get("fantasyStatus")
            if isinstance(fantasy, dict):
                abbr = fantasy.get("abbreviation")
                if isinstance(abbr, str) and abbr.strip():
                    return str(abbr).strip().upper()
                desc = fantasy.get("description") or fantasy.get("displayDescription")
                if isinstance(desc, str) and desc.strip():
                    return _normalize_status_for_display(desc.strip()).upper()
            t = details.get("type")
            if isinstance(t, str) and t.strip():
                return _normalize_status_for_display(t.strip()).upper()

        # Fallback to the top-level status if fantasyStatus isn't present.
        status = inj.get("status")
        if isinstance(status, str) and status.strip():
            return _normalize_status_for_display(status).upper()

        # Safe default: treat unknowns as GTD.
        return "GTD"

    out: dict[str, dict[str, dict[str, str]]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        team_name = block.get("displayName")
        if not team_name:
            continue
        team_key = _normalize_team_name(str(team_name))
        team_inj = block.get("injuries")
        if not isinstance(team_inj, list):
            continue
        by_id: dict[str, str] = {}
        by_name: dict[str, str] = {}
        detail_by_id: dict[str, dict[str, str]] = {}
        detail_by_name: dict[str, dict[str, str]] = {}
        for inj in team_inj:
            if not isinstance(inj, dict):
                continue
            athlete = inj.get("athlete")
            if not isinstance(athlete, dict):
                continue
            athlete_id = _athlete_id_from_links(athlete)
            abbr = _parse_fantasy_abbr(inj)
            short_comment = str(inj.get("shortComment") or "")
            long_comment = str(inj.get("longComment") or "")
            athlete_name = athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or ""
            if athlete_id:
                by_id[str(athlete_id)] = abbr
                detail_by_id[str(athlete_id)] = {
                    "abbr": abbr,
                    "name": str(athlete_name),
                    "shortComment": short_comment,
                    "longComment": long_comment,
                }
            name = athlete_name
            if isinstance(name, str) and name.strip():
                key = name.lower().strip()
                by_name[key] = abbr
                detail_by_name[key] = {
                    "abbr": abbr,
                    "name": str(name),
                    "shortComment": short_comment,
                    "longComment": long_comment,
                }
        if by_id or by_name:
            out[team_key] = {
                "by_id": by_id,
                "by_name": by_name,
                "detail_by_id": detail_by_id,
                "detail_by_name": detail_by_name,
            }
    return out


def _load_espn_game_summary_maps(
    game_ids: list[str],
) -> tuple[dict[str, dict[str, dict[str, str]]], dict[str, str], dict[str, float]]:
    """
    Returns:
      - injury_reports: game_id -> team_key -> athlete_id -> status
      - watch_providers: game_id -> simplified provider label (ESPN/Peacock/Prime/League Pass)
      - close_spreads: game_id -> home_spread_close (float)

    Uses ESPN's game summary endpoint (cached on disk):
      https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=<GAME_ID>
    """
    injury_reports: dict[str, dict[str, dict[str, str]]] = {}
    watch_providers: dict[str, str] = {}
    close_spreads: dict[str, float] = {}
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"

    ids = [str(g).strip() for g in game_ids if str(g).strip()]
    if not ids:
        return injury_reports, watch_providers, close_spreads

    max_workers = int(os.getenv("NBA_WATCH_SUMMARY_WORKERS", "8"))

    def _fetch_one(gid_s: str) -> tuple[str, dict[str, dict[str, str]] | None, str, float | None]:
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
            return gid_s, None, "League Pass", None

        if not isinstance(data, dict):
            return gid_s, {}, "League Pass", None

        provider = _map_watch_provider_label(_extract_espn_broadcast_media_names(data))
        close = None
        try:
            close = extract_closing_spreads(data).get("home_spread_close")
        except Exception:
            close = None

        injuries = data.get("injuries")
        if not isinstance(injuries, list):
            return gid_s, {}, provider, close

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

        return gid_s, by_team, provider, close

    # Parallelize per-game summary fetches; this is the biggest cold-load hotspot.
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch_one, gid) for gid in ids]
        for fut in cf.as_completed(futures):
            gid_s, by_team, provider, close = fut.result()
            watch_providers[gid_s] = provider
            if close is not None:
                try:
                    close_spreads[gid_s] = float(close)
                except Exception:
                    pass
            if by_team is None:
                continue
            injury_reports[gid_s] = by_team

    return injury_reports, watch_providers, close_spreads


def _map_watch_provider_label(names: list[str]) -> str:
    """
    Map ESPN broadcast/media names into a simplified label set for UI display.

    User-facing categories:
      - ESPN
      - Peacock
      - Prime
      - League Pass (fallback for everything else / unknown)
    """
    combined = " ".join([str(x) for x in names if str(x).strip()]).lower()
    if not combined:
        return "League Pass"
    if "peacock" in combined:
        return "Peacock"
    if "prime" in combined or "amazon" in combined:
        return "Prime"
    # ESPN family (including ABC/ESPN2/ESPN+ labels) collapses into "ESPN".
    if "espn" in combined or combined.strip() == "abc" or " abc" in combined:
        return "ESPN"
    return "League Pass"


def _extract_espn_broadcast_media_names(summary: dict[str, Any]) -> list[str]:
    names: list[str] = []

    def _pull(bcasts: Any) -> None:
        if not isinstance(bcasts, list):
            return
        for b in bcasts:
            if not isinstance(b, dict):
                continue
            media = b.get("media")
            if isinstance(media, dict):
                sn = media.get("shortName") or media.get("name")
                if isinstance(sn, str) and sn.strip():
                    names.append(sn.strip())
            # Some summaries encode broadcast name at the top-level.
            sn2 = b.get("shortName") or b.get("name")
            if isinstance(sn2, str) and sn2.strip():
                names.append(sn2.strip())

    _pull(summary.get("broadcasts"))
    header = summary.get("header")
    if isinstance(header, dict):
        comps = header.get("competitions")
        if isinstance(comps, list) and comps and isinstance(comps[0], dict):
            _pull(comps[0].get("broadcasts"))

    # De-dup while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _load_nba_schedule_game_id_map_by_pt_date(
    pt_dates_iso: set[str],
    *,
    pt_tz_name: str = "America/Los_Angeles",
) -> dict[tuple[str, str, str], str]:
    """
    Map (pt_date_iso, home_tricode_lower, away_tricode_lower) -> nba_game_id.

    Uses nba.com schedule JSON (public) which includes gameIds for the full season:
    https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json
    """
    out: dict[tuple[str, str, str], str] = {}
    if not pt_dates_iso:
        return out

    pt_tz = tz.gettz(pt_tz_name)

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
            start_utc_raw = str(g.get("gameDateTimeUTC") or "").strip()
            if not (gid and start_utc_raw):
                continue
            try:
                t_utc = dtparser.isoparse(start_utc_raw)
                t_utc = t_utc.astimezone(dt.timezone.utc) if t_utc.tzinfo else t_utc.replace(tzinfo=dt.timezone.utc)
            except Exception:
                continue
            t_pt = t_utc.astimezone(pt_tz) if pt_tz else t_utc
            pt_date_iso = t_pt.date().isoformat()
            if pt_date_iso not in pt_dates_iso:
                continue

            home = g.get("homeTeam") if isinstance(g.get("homeTeam"), dict) else {}
            away = g.get("awayTeam") if isinstance(g.get("awayTeam"), dict) else {}
            home_abbr = str(home.get("teamTricode") or "").strip().lower()
            away_abbr = str(away.get("teamTricode") or "").strip().lower()
            if not (home_abbr and away_abbr):
                continue
            out[(pt_date_iso, home_abbr, away_abbr)] = gid

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
            dt_utc = dt_utc.astimezone(dt.timezone.utc) if dt_utc.tzinfo else dt_utc.replace(tzinfo=dt.timezone.utc)
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
                "Tip dt (UTC)": dt_utc,
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
            tip = str(r["Tip short"])
            return tip if "PT" in tip else f"{tip} PT"
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
    injury_reports, watch_providers, close_spreads_espn = (
        _load_espn_game_summary_maps(game_ids) if game_ids else ({}, {}, {})
    )
    league_injuries_by_team = _load_espn_league_injuries_by_team(ttl_seconds=5 * 60)

    # --- Close-spread freezing + live blending (Odds API) ---
    # We treat Odds API "Home spread" as the current spread signal (often updates live).
    # For the "close spread", prefer ESPN's summary close spread when available because it can be fetched
    # even if the app wasn't loaded pre-tip. If missing, fall back to freezing the last pre-game Odds API
    # "Home spread" observed to a small local store.
    store_path = _close_spread_store_path()
    close_store = _load_close_spread_store(store_path)
    store_changed = False

    def _gid(r) -> str:
        return str(r.get("ESPN game id") or "").strip()

    def _is_pre(r) -> bool:
        return str(r.get("Status") or "").lower() == "pre"

    for _, r in df.iterrows():
        gid = _gid(r)
        if not gid:
            continue
        if not _is_pre(r):
            continue
        s = r.get("Home spread")
        if s is None:
            continue
        try:
            close_store[gid] = float(s)
            store_changed = True
        except Exception:
            continue

    if store_changed:
        _save_close_spread_store(store_path, close_store)

    def _close_spread_row(r) -> float | None:
        gid = _gid(r)
        cur = r.get("Home spread")
        if gid and gid in close_spreads_espn:
            try:
                return float(close_spreads_espn[gid])
            except Exception:
                pass
        if not gid:
            return None if cur is None else float(cur)
        v = close_store.get(gid)
        if v is None:
            return None if cur is None else float(cur)
        return float(v)

    df["Home spread close"] = df.apply(_close_spread_row, axis=1)
    df["Minutes remaining"] = df["Time remaining"].apply(_minutes_remaining_from_time_remaining)
    df["a(t)"] = df["Minutes remaining"].apply(_live_weight_a)

    def _effective_spread_row(r) -> float | None:
        cur = r.get("Home spread")
        close = r.get("Home spread close")
        if cur is None:
            return None
        try:
            cur_f = float(cur)
        except Exception:
            return None
        if str(r.get("Status") or "").lower() != "in":
            return cur_f
        if close is None:
            return cur_f
        try:
            close_f = float(close)
        except Exception:
            close_f = cur_f
        a = float(r.get("a(t)") or 0.0)
        a = max(0.0, min(1.0, a))
        return a * cur_f + (1.0 - a) * close_f

    df["Home spread effective"] = df.apply(_effective_spread_row, axis=1)
    df["|spread effective|"] = df["Home spread effective"].apply(lambda x: None if x is None else abs(float(x)))

    # NBA.com game URLs (match by PT date + teams; teams play at most once per date).
    pt_dates_iso = {
        str(d) for d in df.get("Local date", pd.Series(dtype=object)).dropna().tolist() if str(d).strip()
    }
    nba_game_id_map = _load_nba_schedule_game_id_map_by_pt_date(pt_dates_iso, pt_tz_name=tz_name)

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
        pt_date_iso = str(pt_date)

        home_abbr = _nba_tricode(str(r.get("Home team", ""))).lower()
        away_abbr = _nba_tricode(str(r.get("Away team", ""))).lower()
        if not (home_abbr and away_abbr):
            return ""

        gid = nba_game_id_map.get((pt_date_iso, home_abbr, away_abbr))
        if not gid:
            return ""
        # nba.com uses format: https://www.nba.com/game/bos-vs-dal-0022500721
        return f"https://www.nba.com/game/{away_abbr}-vs-{home_abbr}-{gid}"

    df["Where to watch URL"] = df.apply(_nba_game_url_row, axis=1)
    df["Where to watch provider"] = df["ESPN game id"].apply(
        lambda gid: watch_providers.get(str(gid), "League Pass") if gid is not None else "League Pass"
    )

    teams_with_injuries: set[str] = set()
    for _, by_team in injury_reports.items():
        for team_key, inj in (by_team or {}).items():
            if isinstance(inj, dict) and inj:
                teams_with_injuries.add(str(team_key))
    for team_key, payload in (league_injuries_by_team or {}).items():
        if not isinstance(payload, dict):
            continue
        by_id = payload.get("by_id")
        if isinstance(by_id, dict) and by_id:
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
            # Keep the full list for robust injury matching and logging.
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

    def _status_priority(status: str) -> int:
        s = (status or "").strip().lower()
        if "out" in s or "injur" in s:
            return 3
        if "doubt" in s:
            return 2
        if "question" in s or s in {"gtd", "dtd", "day-to-day", "day to day", "game-time decision", "game time decision"}:
            return 1
        return 0

    def _worst_status(a: str | None, b: str | None) -> str | None:
        if not a and not b:
            return None
        if not a:
            return b
        if not b:
            return a
        return a if _status_priority(a) >= _status_priority(b) else b

    def _weight_for_abbr_with_short_comment(*, abbr: str | None, short_comment: str | None, target_dow: str | None) -> float:
        a = (abbr or "").strip().upper()
        if not a:
            return float(injury_weight("Available"))
        if a in {"OUT", "OFS"}:
            return float(injury_weight("Out"))
        if a != "GTD":
            return float(injury_weight("Available"))

        inferred = "Questionable"
        sc = (short_comment or "")
        sc_l = sc.lower()
        dow = (target_dow or "").strip().lower()
        if dow and dow in sc_l:
            if "probable" in sc_l:
                inferred = "Probable"
            elif "doubtful" in sc_l:
                inferred = "Doubtful"
            elif "questionable" in sc_l:
                inferred = "Questionable"
        return float(injury_weight(inferred))

    def _merged_team_status_map(
        team_key: str,
        game_id: str | None,
        *,
        players: list[PlayerImpact] | None = None,
    ) -> dict[str, str]:
        by_game = injury_reports.get(str(game_id or ""), {}).get(team_key, {}) or {}
        payload = (league_injuries_by_team or {}).get(team_key, {}) or {}
        by_league_id = payload.get("by_id") if isinstance(payload, dict) else {}
        by_league_name = payload.get("by_name") if isinstance(payload, dict) else {}

        # Start from league fantasyStatus abbreviations (label source-of-truth).
        merged: dict[str, str] = dict(by_league_id) if isinstance(by_league_id, dict) else {}

        # Only use per-game report as a fallback when the league feed doesn't contain the player.
        for pid, st in (by_game or {}).items():
            pid_s = str(pid)
            if pid_s in merged:
                continue
            if st is None:
                continue
            merged[pid_s] = _normalize_status_for_display(str(st)).upper()

        # Name-based fallback: if athlete ids don't line up, use displayName matching.
        if players and isinstance(by_league_name, dict) and by_league_name:
            for p in players:
                pid = str(p.athlete_id)
                if pid in merged:
                    continue
                name_key = str(p.name).lower().strip()
                st = by_league_name.get(name_key)
                if st:
                    merged[pid] = str(st)
        return merged

    def _team_key_injuries_and_health(team_key: str, game_id: str | None, *, target_dow: str | None) -> tuple[float, str, str]:
        players = team_impacts.get(team_key, []) or []
        by_team = _merged_team_status_map(team_key, game_id, players=players)
        payload = (league_injuries_by_team or {}).get(team_key, {}) or {}
        detail_by_id = payload.get("detail_by_id") if isinstance(payload, dict) else {}

        if not by_team:
            return 1.0, "", "[]"

        impact_by_id: dict[str, PlayerImpact] = {str(p.athlete_id): p for p in players}
        impact_by_norm_name: dict[str, PlayerImpact] = {_normalize_player_name(p.name): p for p in players if _normalize_player_name(p.name)}
        top = top_scorer.get(team_key)
        top_athlete_id = str(top[0]) if top else ""

        penalty = 0.0
        injured_players: list[tuple[float, float, str, str, str]] = []
        detail: list[dict[str, Any]] = []

        for pid, st in (by_team or {}).items():
            pid_str = str(pid)
            st_norm = _normalize_status_for_display(str(st) if st is not None else None).upper()
            st_display = _normalize_status_for_display(st_norm)
            sc = None
            inj_name = ""
            if isinstance(detail_by_id, dict):
                det = detail_by_id.get(pid_str)
                if isinstance(det, dict):
                    sc = det.get("shortComment")
                    inj_name = str(det.get("name") or "")
            w = _weight_for_abbr_with_short_comment(abbr=st_norm, short_comment=sc, target_dow=target_dow)

            p = impact_by_id.get(pid_str)
            if p is None and inj_name:
                p = impact_by_norm_name.get(_normalize_player_name(inj_name))
            if p is None:
                detail.append(
                    {
                        "player": inj_name,
                        "player_id": pid_str,
                        "status": st_display,
                        "injury_weight": w,
                        "impact_share": None,
                        "raw_impact": None,
                        "health_delta": None,
                        "health_delta_share": None,
                    }
                )
                continue

            name = str(p.name)
            share = float(p.impact_share)
            raw = float(p.raw_impact)
            penalty += w * share

            health_delta = float(INJURY_OVERALL_IMPORTANCE_WEIGHT) * w * share
            injured_players.append((raw, share, pid_str, name, st_display))
            detail.append(
                {
                    "player": name,
                    "player_id": pid_str,
                    "status": st_display,
                    "injury_weight": w,
                    "impact_share": share,
                    "raw_impact": raw,
                    "health_delta": health_delta,
                    "health_delta_share": None,
                }
            )

        health = 1.0 - float(INJURY_OVERALL_IMPORTANCE_WEIGHT) * penalty
        health = max(0.0, min(1.0, float(health)))

        injured_players.sort(key=lambda x: x[0], reverse=True)
        key_injuries: list[str] = []
        for raw, share, pid_str, name, st_display in injured_players:
            is_key = float(share) >= KEY_INJURY_IMPACT_SHARE_THRESHOLD
            is_top_out = bool(top_athlete_id) and pid_str == top_athlete_id and _status_priority(st_display) >= 3
            if is_key or is_top_out:
                key_injuries.append(f"{name}: {st_display}")

        total_delta = sum(float(d["health_delta"]) for d in detail if d.get("health_delta") is not None)
        if total_delta > 0:
            for d in detail:
                if d.get("health_delta") is None:
                    continue
                d["health_delta_share"] = float(d["health_delta"]) / float(total_delta)

        detail.sort(
            key=lambda d: (
                d.get("health_delta") is None,
                -float(d.get("health_delta") or 0.0),
                str(d.get("player") or ""),
            )
        )
        detail_json = json.dumps(detail, ensure_ascii=False)
        return health, ", ".join(key_injuries), detail_json

    injury_info_cache: dict[tuple[str, str, str], tuple[float, str, str]] = {}

    def _memo_team_injury_info(team_key: str, game_id: str | None, target_dow: str | None) -> tuple[float, str, str]:
        k = (team_key, str(game_id or ""), str(target_dow or ""))
        if k in injury_info_cache:
            return injury_info_cache[k]
        v = _team_key_injuries_and_health(team_key, game_id, target_dow=target_dow)
        injury_info_cache[k] = v
        return v

    df["Health (away)"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Away team"]), r.get("ESPN game id"), r.get("Day"))[0],
        axis=1,
    )
    df["Health (home)"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Home team"]), r.get("ESPN game id"), r.get("Day"))[0],
        axis=1,
    )
    df["Away Key Injuries"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Away team"]), r.get("ESPN game id"), r.get("Day"))[1] or "",
        axis=1,
    )
    df["Home Key Injuries"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Home team"]), r.get("ESPN game id"), r.get("Day"))[1] or "",
        axis=1,
    )
    df["Away injuries detail JSON"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Away team"]), r.get("ESPN game id"), r.get("Day"))[2] or "[]",
        axis=1,
    )
    df["Home injuries detail JSON"] = df.apply(
        lambda r: _memo_team_injury_info(_normalize_team_name(r["Home team"]), r.get("ESPN game id"), r.get("Day"))[2] or "[]",
        axis=1,
    )


    # Baseline adjusted win% prior to star bump (health-adjusted only).
    df["Adj win% (away)"] = df["Win% (away raw)"].astype(float) * df["Health (away)"].astype(float)
    df["Adj win% (home)"] = df["Win% (home raw)"].astype(float) * df["Health (home)"].astype(float)
    df["Adj win% (away) pre-star"] = df["Adj win% (away)"].astype(float)
    df["Adj win% (home) pre-star"] = df["Adj win% (home)"].astype(float)
    df["Avg adj win% pre-star"] = 0.5 * (df["Adj win% (away) pre-star"] + df["Adj win% (home) pre-star"])

    def _star_factor(team_key: str, game_id: str | None, target_dow: str | None) -> float:
        top = top_scorer.get(team_key)
        if not top:
            return 0.0
        athlete_id, _, star_raw, _ = top
        merged = _merged_team_status_map(team_key, game_id, players=team_impacts.get(team_key, []) or [])
        abbr = merged.get(str(athlete_id))
        payload = (league_injuries_by_team or {}).get(team_key, {}) or {}
        detail_by_id = payload.get("detail_by_id") if isinstance(payload, dict) else {}
        sc = None
        if isinstance(detail_by_id, dict):
            det = detail_by_id.get(str(athlete_id))
            if isinstance(det, dict):
                sc = det.get("shortComment")
        w = _weight_for_abbr_with_short_comment(abbr=str(abbr) if abbr is not None else None, short_comment=sc, target_dow=target_dow)
        availability = max(0.0, 1.0 - float(w))
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

    df["Star factor (away)"] = df.apply(
        lambda r: _star_factor(_normalize_team_name(r["Away team"]), r.get("ESPN game id"), r.get("Day")),
        axis=1,
    )
    df["Star factor (home)"] = df.apply(
        lambda r: _star_factor(_normalize_team_name(r["Home team"]), r.get("ESPN game id"), r.get("Day")),
        axis=1,
    )
    df["Away Star Player"] = df.apply(lambda r: _star_player_name(_normalize_team_name(r["Away team"])), axis=1)
    df["Home Star Player"] = df.apply(lambda r: _star_player_name(_normalize_team_name(r["Home team"])), axis=1)
    df["Away Star Raw"] = df.apply(lambda r: _star_player_raw(_normalize_team_name(r["Away team"])), axis=1)
    df["Home Star Raw"] = df.apply(lambda r: _star_player_raw(_normalize_team_name(r["Home team"])), axis=1)

    # Add star factor as a small additive bump to win% (then clip to [0,1]).
    df["Adj win% (away)"] = (df["Adj win% (away)"].astype(float) + df["Star factor (away)"].astype(float)).clip(0.0, 1.0)
    df["Adj win% (home)"] = (df["Adj win% (home)"].astype(float) + df["Star factor (home)"].astype(float)).clip(0.0, 1.0)
    df["Avg adj win% post-star"] = 0.5 * (df["Adj win% (away)"] + df["Adj win% (home)"])

    # Convert star bumps into the same units as the displayed "Team Quality" component (0..1 then scaled to 0..100).
    def _quality_bumps_row(r) -> pd.Series:
        away_pre = float(r.get("Adj win% (away) pre-star") or 0.0)
        home_pre = float(r.get("Adj win% (home) pre-star") or 0.0)
        away_sf = float(r.get("Star factor (away)") or 0.0)
        home_sf = float(r.get("Star factor (home)") or 0.0)

        q_pre = float(watch.team_quality(home_pre, away_pre))

        away_only = min(1.0, away_pre + away_sf)
        home_only = min(1.0, home_pre + home_sf)
        dq_away = float(watch.team_quality(home_pre, away_only)) - q_pre
        dq_home = float(watch.team_quality(home_only, away_pre)) - q_pre
        return pd.Series(
            {
                "Team quality pre-star": q_pre,
                "Team Quality bump (away)": 100.0 * dq_away,
                "Team Quality bump (home)": 100.0 * dq_home,
            }
        )

    df[["Team quality pre-star", "Team Quality bump (away)", "Team Quality bump (home)"]] = df.apply(
        _quality_bumps_row, axis=1
    )

    def _star_factor_display(name: str, bump_points: float) -> str:
        if not name:
            return ""
        try:
            b = float(bump_points)
        except Exception:
            b = 0.0
        if b <= 0:
            return ""
        return f"{name} +{int(round(b))} TQ"

    df["Away Star Factor"] = df.apply(
        lambda r: _star_factor_display(str(r.get("Away Star Player") or ""), float(r.get("Team Quality bump (away)") or 0.0)),
        axis=1,
    )
    df["Home Star Factor"] = df.apply(
        lambda r: _star_factor_display(str(r.get("Home Star Player") or ""), float(r.get("Team Quality bump (home)") or 0.0)),
        axis=1,
    )

    def _compute_watchability_row(r) -> pd.Series:
        abs_spread = r.get("|spread effective|")
        if abs_spread is None:
            abs_spread = r.get("|spread|")
        w = watch.compute_watchability(
            float(r["Adj win% (home)"]),
            float(r["Adj win% (away)"]),
            abs_spread,
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
        "injuries_source": "ESPN league injuries + summary fallback",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return json.dumps(payload, sort_keys=True)
