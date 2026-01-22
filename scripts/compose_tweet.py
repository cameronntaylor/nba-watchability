from __future__ import annotations

from datetime import date
import os
import sys

from dateutil import tz
from dateutil import parser as dtparser

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.odds_api import fetch_nba_spreads_window
from core.schedule_espn import fetch_games_for_date
from core.standings import _normalize_team_name, get_win_pct
from core.standings_espn import fetch_team_standings_detail_maps
from core.health_espn import compute_team_health
from core.importance import compute_importance_map
import core.watchability as watch


def _bucket_summary() -> str | None:
    """
    Returns a short string like:
    '2 Must Watch Games, 3 Strong Watch Games, 4 Watchable Games, 1 Skippable Games and 0 Hard Skip Games'
    for today's PT slate.
    """
    local_tz = tz.gettz("America/Los_Angeles")
    today_local = date.today()

    games = fetch_nba_spreads_window(days_ahead=2)
    winpct_map, _, detail_map = fetch_team_standings_detail_maps()
    compute_importance_map(detail_map)  # kept for future use
    team_names = sorted({g.home_team for g in games} | {g.away_team for g in games})
    health_map = {}
    for name in team_names:
        try:
            health, _ = compute_team_health(name)
        except Exception:
            health = 1.0
        health_map[_normalize_team_name(name)] = float(health)

    rows = []
    dates = set()
    for g in games:
        if not g.commence_time_utc:
            continue
        try:
            dt_local = dtparser.isoparse(g.commence_time_utc).astimezone(local_tz)
        except Exception:
            continue
        local_date = dt_local.date()
        dates.add(local_date)

        home_key = _normalize_team_name(g.home_team)
        away_key = _normalize_team_name(g.away_team)

        w_home_raw = get_win_pct(g.home_team, winpct_map, default=0.5)
        w_away_raw = get_win_pct(g.away_team, winpct_map, default=0.5)
        w_home = w_home_raw * float(health_map.get(home_key, 1.0))
        w_away = w_away_raw * float(health_map.get(away_key, 1.0))

        abs_spread = None if g.home_spread is None else abs(float(g.home_spread))
        wi = watch.compute_watchability(w_home, w_away, abs_spread).awi

        rows.append(
            {
                "date": local_date,
                "home": str(g.home_team).lower().strip(),
                "away": str(g.away_team).lower().strip(),
                "wi": float(wi),
            }
        )

    if not rows:
        return None

    # Choose "today PT" if present, else earliest date we have.
    selected_date = today_local if today_local in dates else min(dates)
    date_iso = selected_date.isoformat()

    # Build ESPN status map so we can exclude post games.
    status_map = {}
    try:
        for e in fetch_games_for_date(selected_date):
            home = _normalize_team_name(str(e.get("home_team", "")))
            away = _normalize_team_name(str(e.get("away_team", "")))
            state = str(e.get("state", ""))
            if home and away and state:
                status_map[(date_iso, home, away)] = state
    except Exception:
        status_map = {}

    wis = []
    for r in rows:
        if r["date"] != selected_date:
            continue
        state = status_map.get((date_iso, _normalize_team_name(r["home"]), _normalize_team_name(r["away"])))
        if state == "post":
            continue
        wis.append(r["wi"])

    if not wis:
        return None

    buckets = ["Must Watch", "Strong Watch", "Watchable", "Skippable", "Hard Skip"]
    counts = {b: 0 for b in buckets}
    for wi in wis:
        b = watch.awi_label(float(wi))
        if b in counts:
            counts[b] += 1

    x1 = counts["Must Watch"]
    x2 = counts["Strong Watch"]
    x3 = counts["Watchable"]
    x4 = counts["Skippable"]
    x5 = counts["Hard Skip"]
    return (
        f"{x1} Must Watch Games, {x2} Strong Watch Games, {x3} Watchable Games, "
        f"{x4} Skippable Games and {x5} Hard Skip Games"
    )

def compose_tweet_text():
    today = date.today().strftime("%b %d")
    avg_line = None
    try:
        avg_line = _bucket_summary()
    except Exception:
        avg_line = None

    parts = [f"🏀 NBA Watchability — {today}"]
    if avg_line:
        parts.append(avg_line)
    parts.append("")
    parts.append("What to watch tonight, ranked by Watchability (competitiveness + injury-adjusted team quality).")
    return "\n".join(parts)
