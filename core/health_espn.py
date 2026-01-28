from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.http_cache import get_json_cached
from core.standings import _normalize_team_name
from core.watchability_v2_params import (
    INJURY_WEIGHT_AVAILABLE,
    INJURY_WEIGHT_DOUBTFUL,
    INJURY_WEIGHT_OUT,
    INJURY_WEIGHT_QUESTIONABLE,
    INJURY_OVERALL_IMPORTANCE_WEIGHT,
)

import requests


ESPN_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
ESPN_TEAM_ROSTER_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
)
ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
ESPN_ATHLETE_COMMON_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}"


def current_nba_season_year(today: Optional[dt.date] = None) -> int:
    d = today or dt.date.today()
    return d.year + 1 if d.month >= 7 else d.year


def _walk(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _find_first_number(stats_json: Any, key: str) -> Optional[float]:
    for d in _walk(stats_json):
        if key in d:
            try:
                return float(d[key])
            except Exception:
                pass
        name = d.get("name")
        if name == key and "value" in d:
            try:
                return float(d["value"])
            except Exception:
                pass
    return None


def _injury_weight(status: str) -> float:
    s = (status or "").strip().lower()
    if not s:
        return INJURY_WEIGHT_AVAILABLE
    if "injur" in s:
        return INJURY_WEIGHT_OUT
    if "out" in s:
        return INJURY_WEIGHT_OUT
    if "doubt" in s:
        return INJURY_WEIGHT_DOUBTFUL
    if "question" in s:
        return INJURY_WEIGHT_QUESTIONABLE
    if s in {"gtd", "dtd", "day-to-day", "day to day", "game-time decision", "game time decision"}:
        return INJURY_WEIGHT_QUESTIONABLE
    if "prob" in s:
        return INJURY_WEIGHT_AVAILABLE
    if "active" in s or "available" in s or "probable" in s:
        return INJURY_WEIGHT_AVAILABLE
    return INJURY_WEIGHT_AVAILABLE


def injury_weight(status: str) -> float:
    """
    Public wrapper for converting a (possibly game-specific) ESPN status string into a weight.
    """
    return _injury_weight(status)


def _status_priority(status: str) -> int:
    """
    Higher means "less available".
    """
    s = (status or "").strip().lower()
    if "out" in s:
        return 3
    if "doubt" in s:
        return 2
    if "question" in s or s in {"gtd", "dtd", "day-to-day", "day to day", "game-time decision", "game time decision"}:
        return 1
    return 0


def _worst_status(statuses: list[str]) -> Optional[str]:
    if not statuses:
        return None
    return sorted(statuses, key=_status_priority, reverse=True)[0]


def _parse_status_from_text(*texts: str) -> Optional[str]:
    """
    Heuristic parser for ESPN text fields (shortComment/longComment) that often contain
    'probable', 'questionable', 'doubtful', 'out', 'game-time decision', etc.
    """
    joined = " ".join([t for t in texts if t]).lower()
    if not joined.strip():
        return None
    if "probable" in joined:
        return "Probable"
    if "doubtful" in joined:
        return "Doubtful"
    if "questionable" in joined:
        return "Questionable"
    if "game-time decision" in joined or "game time decision" in joined:
        return "Questionable"
    if "day-to-day" in joined or "day to day" in joined:
        return "Day-To-Day"
    if "out" in joined:
        return "Out"
    return None


def fetch_athlete_status_refined(athlete_id: str, *, ttl_seconds: int = 10 * 60) -> Optional[str]:
    """
    Refines an athlete status using ESPN's common athlete endpoint, which often contains
    richer text than the team roster feed (e.g. 'probable' in shortComment).
    """
    url = ESPN_ATHLETE_COMMON_URL.format(athlete_id=athlete_id)
    try:
        resp = get_json_cached(
            url,
            namespace="espn",
            cache_key=f"athlete_common:{athlete_id}",
            ttl_seconds=ttl_seconds,
            timeout_seconds=15,
        )
    except Exception:
        return None

    data = resp.data
    athlete = data.get("athlete") if isinstance(data, dict) else None
    if not isinstance(athlete, dict):
        return None

    injuries = athlete.get("injuries")
    if not isinstance(injuries, list) or not injuries:
        return None

    # Prefer shortComment-derived statuses when present; ESPN's raw 'status'
    # can lag behind what is shown in the player UI (e.g. shortComment says 'probable').
    for inj in injuries:
        if not isinstance(inj, dict):
            continue
        short_comment = str(inj.get("shortComment") or "")
        long_comment = str(inj.get("longComment") or "")
        parsed_short = _parse_status_from_text(short_comment)
        if parsed_short:
            return parsed_short
        else:
            parsed_long = _parse_status_from_text(long_comment)
            if parsed_long:
                return parsed_long

        details = inj.get("details")
        if isinstance(details, dict):
            fantasy = details.get("fantasyStatus")
            if isinstance(fantasy, dict):
                dd = fantasy.get("displayDescription") or fantasy.get("description") or fantasy.get("abbreviation")
                parsed2 = _parse_status_from_text(str(dd or ""))
                if parsed2:
                    return parsed2
                if isinstance(dd, str) and dd.strip():
                    if dd.strip().upper() == "GTD":
                        return "Questionable"
                    return dd.strip()

        status = inj.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()

    return None


@dataclass(frozen=True)
class PlayerImpact:
    athlete_id: str
    name: str
    points_per_game: float
    assists_per_game: float
    rebounds_per_game: float
    steals_per_game: float
    blocks_per_game: float
    raw_impact: float
    impact_share: float
    relative_raw_impact: float
    injury_status: str
    injury_weight: float


def compute_team_player_impacts(
    team_name: str,
    *,
    season_year: Optional[int] = None,
    season_type: int = 2,
    roster_ttl_seconds: int = 24 * 60 * 60,
    stats_ttl_seconds: int = 24 * 60 * 60,
) -> List[PlayerImpact]:
    """
    Returns per-player impact stats for a team. Injury fields are included but
    callers can ignore them (e.g., when using matchup-specific game injury reports).

    Raw impact = avgPoints + avgAssists + avgRebounds (per game).
    impact_share = raw / sum(raw over team)
    relative_raw_impact = raw / max(raw over team)
    """
    year = season_year or current_nba_season_year()
    team_key = _normalize_team_name(team_name)

    team_id_map = fetch_team_id_map()
    team_id = team_id_map.get(team_key)
    if not team_id:
        return []

    roster = fetch_team_roster(team_id, ttl_seconds=roster_ttl_seconds)
    if not roster:
        return []

    impacts_raw: List[Tuple[str, str, float, float, float, float, float, str]] = []
    for athlete_id, athlete_name, roster_status in roster:
        try:
            pts, ast, reb, stl, blk = fetch_athlete_per_game_stats(
                athlete_id, season_year=year, season_type=season_type, ttl_seconds=stats_ttl_seconds
            )
        except requests.HTTPError:
            continue
        except Exception:
            continue
        if pts is None and ast is None and reb is None and stl is None and blk is None:
            continue
        pts_f = float(pts or 0.0)
        ast_f = float(ast or 0.0)
        reb_f = float(reb or 0.0)
        stl_f = float(stl or 0.0)
        blk_f = float(blk or 0.0)
        raw = float(pts or 0.0) + float(ast or 0.0) + float(reb or 0.0)
        impacts_raw.append((athlete_id, athlete_name, pts_f, ast_f, reb_f, stl_f, blk_f, raw, roster_status or "Available"))

    if not impacts_raw:
        return []

    sum_raw = sum(r for _, _, _, _, _, _, _, r, _ in impacts_raw) or 0.0
    max_raw = max(r for _, _, _, _, _, _, _, r, _ in impacts_raw) or 0.0
    if sum_raw <= 0 or max_raw <= 0:
        return []

    players: List[PlayerImpact] = []
    for athlete_id, athlete_name, pts_f, ast_f, reb_f, stl_f, blk_f, raw, status in impacts_raw:
        share = raw / sum_raw if sum_raw else 0.0
        rel = raw / max_raw if max_raw else 0.0
        iw = _injury_weight(status)
        players.append(
            PlayerImpact(
                athlete_id=str(athlete_id),
                name=str(athlete_name),
                points_per_game=float(pts_f),
                assists_per_game=float(ast_f),
                rebounds_per_game=float(reb_f),
                steals_per_game=float(stl_f),
                blocks_per_game=float(blk_f),
                raw_impact=float(raw),
                impact_share=float(share),
                relative_raw_impact=float(rel),
                injury_status=str(status),
                injury_weight=float(iw),
            )
        )

    players.sort(key=lambda p: p.raw_impact, reverse=True)
    return players


def fetch_team_id_map(*, ttl_seconds: int = 7 * 24 * 60 * 60) -> Dict[str, str]:
    """
    Returns: normalized_team_name -> ESPN team id (string).
    """
    resp = get_json_cached(
        ESPN_TEAMS_URL,
        namespace="espn",
        cache_key="teams",
        ttl_seconds=ttl_seconds,
        timeout_seconds=10,
    )
    data = resp.data
    out: Dict[str, str] = {}
    for d in _walk(data):
        team = d.get("team")
        if not isinstance(team, dict):
            continue
        team_id = team.get("id")
        display = team.get("displayName") or team.get("name")
        if team_id and display:
            out[_normalize_team_name(str(display))] = str(team_id)
    return out


def fetch_team_roster(team_id: str, *, ttl_seconds: int = 24 * 60 * 60) -> List[Tuple[str, str, Optional[str]]]:
    """
    Returns list of (athlete_id, athlete_name, status) for a given ESPN team id.
    If present, status is derived from the roster payload's per-athlete injuries list.
    """
    url = ESPN_TEAM_ROSTER_URL.format(team_id=team_id)
    resp = get_json_cached(
        url,
        namespace="espn",
        cache_key=f"roster:{team_id}",
        ttl_seconds=ttl_seconds,
        timeout_seconds=15,
    )
    data = resp.data
    roster: List[Tuple[str, str, Optional[str]]] = []

    # The roster endpoint commonly returns an 'athletes' list of athlete dicts.
    athletes = data.get("athletes") if isinstance(data, dict) else None
    if isinstance(athletes, list):
        for a in athletes:
            if not isinstance(a, dict):
                continue
            athlete_id = a.get("id")
            name = a.get("displayName") or a.get("fullName") or a.get("name")
            injury_statuses = []
            injuries = a.get("injuries")
            if isinstance(injuries, list):
                for inj in injuries:
                    if not isinstance(inj, dict):
                        continue
                    st = inj.get("status")
                    if st:
                        injury_statuses.append(str(st))
            status = _worst_status(injury_statuses)
            if athlete_id and name:
                roster.append((str(athlete_id), str(name), status))

    # Fallback: some ESPN payloads nest {'athlete': {...}} objects.
    for d in _walk(data):
        athlete = d.get("athlete")
        if not isinstance(athlete, dict):
            continue
        athlete_id = athlete.get("id")
        name = athlete.get("displayName") or athlete.get("fullName") or athlete.get("name")
        if athlete_id and name:
            roster.append((str(athlete_id), str(name), None))
    # Deduplicate while preserving order.
    seen = set()
    uniq: List[Tuple[str, str, Optional[str]]] = []
    for aid, nm, st in roster:
        if aid in seen:
            continue
        seen.add(aid)
        uniq.append((aid, nm, st))
    return uniq


def fetch_injury_status_map(*, ttl_seconds: int = 10 * 60) -> Dict[str, str]:
    """
    Returns: athlete_id -> injury status string (e.g. Available/Questionable/Doubtful/Out).
    """
    resp = get_json_cached(
        ESPN_INJURIES_URL,
        namespace="espn",
        cache_key="injuries",
        ttl_seconds=ttl_seconds,
        timeout_seconds=15,
    )
    data = resp.data
    out: Dict[str, str] = {}
    for d in _walk(data):
        athlete = d.get("athlete")
        if not isinstance(athlete, dict):
            continue
        athlete_id = athlete.get("id")
        status = d.get("status") or d.get("type") or d.get("injuryStatus")
        if athlete_id and status:
            out[str(athlete_id)] = str(status)
    return out


def fetch_athlete_per_game_stats(
    athlete_id: str,
    *,
    season_year: int,
    season_type: int = 2,
    ttl_seconds: int = 24 * 60 * 60,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Returns (avg_points, avg_assists, avg_rebounds, avg_steals, avg_blocks) for a given athlete id.

    Uses sports.core API; values can be absent for some athletes.
    """
    url = (
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
        f"seasons/{season_year}/types/{season_type}/athletes/{athlete_id}/statistics/0"
    )
    resp = get_json_cached(
        url,
        params={"lang": "en", "region": "us"},
        namespace="espn",
        cache_key=f"athlete_stats:{season_year}:{season_type}:{athlete_id}",
        ttl_seconds=ttl_seconds,
        timeout_seconds=20,
    )
    data = resp.data
    pts = _find_first_number(data, "avgPoints")
    ast = _find_first_number(data, "avgAssists")
    reb = _find_first_number(data, "avgRebounds")
    stl = _find_first_number(data, "avgSteals")
    blk = _find_first_number(data, "avgBlocks")
    return pts, ast, reb, stl, blk


def compute_team_health(
    team_name: str,
    *,
    season_year: Optional[int] = None,
    season_type: int = 2,
    roster_ttl_seconds: int = 24 * 60 * 60,
    injuries_ttl_seconds: int = 10 * 60,
    stats_ttl_seconds: int = 24 * 60 * 60,
) -> Tuple[float, List[PlayerImpact]]:
    """
    Computes Team Health Score in [0,1] and returns per-player breakdown.

    Team Health Score = 1 - sum(Player Injury Weight * Player Tier Weight)
    where Tier Weight is based on relative impact within team.
    """
    year = season_year or current_nba_season_year()
    team_key = _normalize_team_name(team_name)

    team_id_map = fetch_team_id_map()
    team_id = team_id_map.get(team_key)
    if not team_id:
        return 1.0, []

    roster = fetch_team_roster(team_id, ttl_seconds=roster_ttl_seconds)
    if not roster:
        return 1.0, []

    injuries = fetch_injury_status_map(ttl_seconds=injuries_ttl_seconds)
    roster_status_map = {athlete_id: status for athlete_id, _, status in roster if status}

    impacts = compute_team_player_impacts(
        team_name,
        season_year=year,
        season_type=season_type,
        roster_ttl_seconds=roster_ttl_seconds,
        stats_ttl_seconds=stats_ttl_seconds,
    )
    if not impacts:
        return 1.0, []

    players: List[PlayerImpact] = []
    penalty = 0.0
    for p in impacts:
        athlete_id = p.athlete_id
        status = roster_status_map.get(athlete_id) or injuries.get(athlete_id, "Available")
        if status and _status_priority(status) > 0:
            refined = fetch_athlete_status_refined(athlete_id)
            if refined:
                status = refined
        iw = _injury_weight(status)
        penalty += float(iw) * float(p.impact_share)
        players.append(
            PlayerImpact(
                athlete_id=p.athlete_id,
                name=p.name,
                points_per_game=p.points_per_game,
                assists_per_game=p.assists_per_game,
                rebounds_per_game=p.rebounds_per_game,
                steals_per_game=p.steals_per_game,
                blocks_per_game=p.blocks_per_game,
                raw_impact=p.raw_impact,
                impact_share=p.impact_share,
                relative_raw_impact=p.relative_raw_impact,
                injury_status=str(status),
                injury_weight=float(iw),
            )
        )

    health = 1.0 - float(INJURY_OVERALL_IMPORTANCE_WEIGHT) * penalty
    health = max(0.0, min(1.0, float(health)))
    players.sort(key=lambda x: x.raw_impact, reverse=True)
    return health, players


def compute_health_map_for_teams(
    team_names: Iterable[str],
    *,
    season_year: Optional[int] = None,
    season_type: int = 2,
) -> Dict[str, float]:
    """
    Returns: normalized_team_name -> health score.
    """
    out: Dict[str, float] = {}
    for name in team_names:
        key = _normalize_team_name(name)
        try:
            health, _ = compute_team_health(name, season_year=season_year, season_type=season_type)
        except Exception:
            health = 1.0
        out[key] = float(health)
    return out
