from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable

from core.http_cache import get_json_cached

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"


def fetch_game_summary(
    game_id: str,
    *,
    ttl_seconds: int = 60 * 60 * 6,
    cache_key_prefix: str = "summary",
) -> dict[str, Any]:
    resp = get_json_cached(
        ESPN_SUMMARY,
        params={"event": str(game_id)},
        namespace="espn",
        cache_key=f"{cache_key_prefix}:{game_id}",
        ttl_seconds=int(ttl_seconds),
        timeout_seconds=15,
    )
    data = resp.data
    if not isinstance(data, dict):
        return {}
    return data


def _clock_to_seconds_remaining(display_value: str | None) -> float | None:
    if not display_value:
        return None
    s = str(display_value).strip()
    if not s:
        return None
    if ":" in s:
        try:
            minutes_s, seconds_s = s.split(":", 1)
            minutes = int(minutes_s)
            seconds = float(seconds_s)
            return float(minutes * 60) + float(seconds)
        except Exception:
            return None
    try:
        return float(s)
    except Exception:
        return None


def _period_number(period: Any) -> int | None:
    if period is None:
        return None
    if isinstance(period, dict):
        n = period.get("number")
        try:
            return int(n)
        except Exception:
            return None
    try:
        return int(period)
    except Exception:
        return None


@dataclass(frozen=True)
class WinProbSnapshot:
    period: int
    seconds_remaining: float | None
    wallclock_utc: str | None
    home_score: int | None
    away_score: int | None
    home_wp: float | None
    away_wp: float | None


def extract_winprobability_snapshots(summary: dict[str, Any]) -> list[WinProbSnapshot]:
    """
    ESPN summary JSON contains:
      - plays[] (period, clock, awayScore, homeScore, wallclock)
      - winprobability[] (homeWinPercentage, tiePercentage?, playId)
    We join winprobability -> plays via playId to produce time-aligned snapshots.
    """
    plays = summary.get("plays")
    winprob = summary.get("winprobability")
    if not isinstance(winprob, list) or not winprob:
        return []

    play_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(plays, list):
        for p in plays:
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            if pid is None:
                continue
            play_by_id[str(pid)] = p

    out: list[WinProbSnapshot] = []
    for wp in winprob:
        if not isinstance(wp, dict):
            continue

        # Prefer playId join (most detailed).
        play = None
        pid = wp.get("playId")
        if pid is not None:
            play = play_by_id.get(str(pid))

        if play:
            period_n = _period_number(play.get("period"))
            clock = play.get("clock") or {}
            seconds_remaining = _clock_to_seconds_remaining(
                clock.get("displayValue") if isinstance(clock, dict) else None
            )
            try:
                home_score = int(play.get("homeScore")) if play.get("homeScore") is not None else None
            except Exception:
                home_score = None
            try:
                away_score = int(play.get("awayScore")) if play.get("awayScore") is not None else None
            except Exception:
                away_score = None
            wallclock = play.get("wallclock")
        else:
            # Fallback for schemas where winprobability includes timing + scores directly.
            period_n = _period_number(wp.get("period"))
            seconds_remaining = _clock_to_seconds_remaining(
                wp.get("displayClock") or wp.get("clock") or wp.get("timeRemaining")
            )
            try:
                home_score = int(wp.get("homeScore")) if wp.get("homeScore") is not None else None
            except Exception:
                home_score = None
            try:
                away_score = int(wp.get("awayScore")) if wp.get("awayScore") is not None else None
            except Exception:
                away_score = None
            wallclock = wp.get("wallclock")

        if period_n is None:
            continue

        home_wp = wp.get("homeWinPercentage")
        tie_wp = wp.get("tiePercentage", 0.0)
        try:
            home_wp_f = float(home_wp) if home_wp is not None else None
        except Exception:
            home_wp_f = None
        try:
            tie_wp_f = float(tie_wp) if tie_wp is not None else 0.0
        except Exception:
            tie_wp_f = 0.0

        away_wp_f: float | None
        if home_wp_f is None:
            away_wp_f = None
        else:
            away_wp_f = max(0.0, min(1.0, 1.0 - home_wp_f - tie_wp_f))

        out.append(
            WinProbSnapshot(
                period=period_n,
                seconds_remaining=seconds_remaining,
                wallclock_utc=wallclock,
                home_score=home_score,
                away_score=away_score,
                home_wp=home_wp_f,
                away_wp=away_wp_f,
            )
        )

    return out


def _closest_snapshot(
    snapshots: Iterable[WinProbSnapshot],
    *,
    period: int,
    target_seconds_remaining: float,
) -> WinProbSnapshot | None:
    best: WinProbSnapshot | None = None
    best_dist: float | None = None
    for s in snapshots:
        if s.period != period:
            continue
        if s.seconds_remaining is None:
            continue
        dist = abs(float(s.seconds_remaining) - float(target_seconds_remaining))
        if best is None or best_dist is None or dist < best_dist:
            best = s
            best_dist = dist
    return best


def compute_game_checkpoints(summary: dict[str, Any]) -> dict[str, Any]:
    """
    Returns away win probability + score differential checkpoints:
      - end of Q1/Q2/Q3 (clock ~ 0)
      - 5:00 left in Q4 (clock ~ 300s)
    and overall away win prob swing (max-min).
    """
    snaps = extract_winprobability_snapshots(summary)
    if not snaps:
        return {
            "away_wp_swing": None,
            "away_wp_end_q1": None,
            "score_diff_end_q1": None,
            "away_wp_end_q2": None,
            "score_diff_end_q2": None,
            "away_wp_end_q3": None,
            "score_diff_end_q3": None,
            "away_wp_5m_left_q4": None,
            "score_diff_5m_left_q4": None,
        }

    def _score_diff(s: WinProbSnapshot | None) -> int | None:
        if not s or s.away_score is None or s.home_score is None:
            return None
        return int(s.away_score) - int(s.home_score)

    q1 = _closest_snapshot(snaps, period=1, target_seconds_remaining=0.0)
    q2 = _closest_snapshot(snaps, period=2, target_seconds_remaining=0.0)
    q3 = _closest_snapshot(snaps, period=3, target_seconds_remaining=0.0)
    q4_5m = _closest_snapshot(snaps, period=4, target_seconds_remaining=300.0)

    away_wps = [s.away_wp for s in snaps if s.away_wp is not None]
    away_wp_swing = None
    if away_wps:
        away_wp_swing = float(max(away_wps) - min(away_wps))

    return {
        "away_wp_swing": away_wp_swing,
        "away_wp_end_q1": q1.away_wp if q1 else None,
        "score_diff_end_q1": _score_diff(q1),
        "away_wp_end_q2": q2.away_wp if q2 else None,
        "score_diff_end_q2": _score_diff(q2),
        "away_wp_end_q3": q3.away_wp if q3 else None,
        "score_diff_end_q3": _score_diff(q3),
        "away_wp_5m_left_q4": q4_5m.away_wp if q4_5m else None,
        "score_diff_5m_left_q4": _score_diff(q4_5m),
    }


def extract_final_score(summary: dict[str, Any]) -> tuple[int | None, int | None]:
    """
    Returns (away_final, home_final) if present; otherwise (None, None).
    """
    header = summary.get("header") or {}
    competitions = header.get("competitions") or []
    if not competitions or not isinstance(competitions, list):
        return None, None
    comp = competitions[0] if isinstance(competitions[0], dict) else {}
    competitors = comp.get("competitors") or []
    if not isinstance(competitors, list):
        return None, None

    away_final = None
    home_final = None
    for c in competitors:
        if not isinstance(c, dict):
            continue
        side = c.get("homeAway")
        try:
            score = int(float(c.get("score"))) if c.get("score") is not None else None
        except Exception:
            score = None
        if side == "away":
            away_final = score
        elif side == "home":
            home_final = score
    return away_final, home_final


def _parse_line_float(x: Any) -> float | None:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    try:
        return float(s.replace("+", ""))
    except Exception:
        return None


def extract_closing_spreads(summary: dict[str, Any]) -> dict[str, Any]:
    """
    Attempts to extract a *closing* point spread from ESPN summary JSON.

    Prefer `pickcenter[*].pointSpread.home/away.close.line` (DraftKings widget style).
    Fallback to `odds[*].spread.home/away.close.line` (older format).

    Returns keys:
      - home_spread_close (float|None)  # negative => home favored
      - away_spread_close (float|None)
      - spread_provider (str|None)
    """
    home_close = None
    away_close = None
    provider = None

    pickcenter = summary.get("pickcenter")
    if isinstance(pickcenter, list) and pickcenter:
        # Choose the first record that has a pointSpread dict.
        for rec in pickcenter:
            if not isinstance(rec, dict):
                continue
            ps = rec.get("pointSpread")
            if not isinstance(ps, dict):
                continue
            h = ps.get("home") if isinstance(ps.get("home"), dict) else None
            a = ps.get("away") if isinstance(ps.get("away"), dict) else None
            h_close = (h.get("close") if isinstance(h, dict) else None) if h else None
            a_close = (a.get("close") if isinstance(a, dict) else None) if a else None
            if isinstance(h_close, dict):
                home_close = _parse_line_float(h_close.get("line"))
            if isinstance(a_close, dict):
                away_close = _parse_line_float(a_close.get("line"))
            prov = rec.get("provider")
            if isinstance(prov, dict):
                provider = prov.get("name") or prov.get("displayName") or prov.get("id")
            if home_close is not None or away_close is not None:
                break

    if home_close is None and away_close is None:
        odds = summary.get("odds")
        if isinstance(odds, list) and odds:
            for rec in odds:
                if not isinstance(rec, dict):
                    continue
                sp = rec.get("spread")
                if not isinstance(sp, dict):
                    continue
                h = sp.get("home") if isinstance(sp.get("home"), dict) else None
                a = sp.get("away") if isinstance(sp.get("away"), dict) else None
                h_close = (h.get("close") if isinstance(h, dict) else None) if h else None
                a_close = (a.get("close") if isinstance(a, dict) else None) if a else None
                if isinstance(h_close, dict):
                    home_close = _parse_line_float(h_close.get("line"))
                if isinstance(a_close, dict):
                    away_close = _parse_line_float(a_close.get("line"))
                prov = rec.get("provider")
                if isinstance(prov, dict):
                    provider = prov.get("name") or prov.get("displayName") or prov.get("id")
                if home_close is not None or away_close is not None:
                    break

    # If only one side exists, infer the other.
    if home_close is None and away_close is not None:
        home_close = -float(away_close)
    if away_close is None and home_close is not None:
        away_close = -float(home_close)

    return {
        "home_spread_close": home_close,
        "away_spread_close": away_close,
        "spread_provider": provider,
    }


def extract_leading_scorers(summary: dict[str, Any]) -> dict[str, Any]:
    """
    Extract per-team leading scorer (points) from ESPN summary boxscore.

    Returns keys:
      - away_leading_scorer (str|None)
      - away_leading_scorer_pts (int|None)
      - home_leading_scorer (str|None)
      - home_leading_scorer_pts (int|None)
    """
    header = summary.get("header") or {}
    competitions = header.get("competitions") or []
    comp = competitions[0] if isinstance(competitions, list) and competitions and isinstance(competitions[0], dict) else {}
    competitors = comp.get("competitors") or []
    team_id_to_side: dict[str, str] = {}
    for c in competitors:
        if not isinstance(c, dict):
            continue
        team = c.get("team") or {}
        tid = team.get("id")
        side = c.get("homeAway")
        if tid is None or side not in {"home", "away"}:
            continue
        team_id_to_side[str(tid)] = str(side)

    box = summary.get("boxscore") or {}
    player_blocks = box.get("players") or []
    if not isinstance(player_blocks, list):
        player_blocks = []

    out: dict[str, Any] = {
        "away_leading_scorer": None,
        "away_leading_scorer_pts": None,
        "home_leading_scorer": None,
        "home_leading_scorer_pts": None,
    }

    def _parse_int(x: Any) -> int | None:
        try:
            if x is None:
                return None
            return int(float(str(x).strip()))
        except Exception:
            return None

    def _consider(side: str, name: str | None, pts: int | None) -> None:
        if side not in {"home", "away"} or not name or pts is None:
            return
        key_name = f"{side}_leading_scorer"
        key_pts = f"{side}_leading_scorer_pts"
        cur = out.get(key_pts)
        if cur is None or pts > int(cur):
            out[key_name] = str(name)
            out[key_pts] = int(pts)

    for block in player_blocks:
        if not isinstance(block, dict):
            continue
        team = block.get("team") or {}
        team_id = team.get("id")
        if team_id is None:
            continue
        side = team_id_to_side.get(str(team_id))
        if side not in {"home", "away"}:
            continue

        statistics = block.get("statistics") or []
        if not isinstance(statistics, list):
            continue
        if not statistics:
            continue
        stat0 = statistics[0] if isinstance(statistics[0], dict) else {}
        labels = stat0.get("labels") or []
        if not isinstance(labels, list) or "PTS" not in labels:
            continue
        pts_idx = labels.index("PTS")

        athletes = stat0.get("athletes") or []
        if not isinstance(athletes, list):
            continue
        for a in athletes:
            if not isinstance(a, dict):
                continue
            athlete = a.get("athlete") or {}
            name = athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName")
            stats = a.get("stats") or []
            if not isinstance(stats, list) or pts_idx >= len(stats):
                continue
            pts = _parse_int(stats[pts_idx])
            _consider(side, name, pts)

    return out
