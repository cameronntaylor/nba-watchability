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
from core.standings import get_win_pct
from core.standings_espn import fetch_team_win_pct_map
import core.watchability as watch


def _avg_wi_summary() -> str | None:
    """
    Returns a short string like 'Avg WI: 62 (Good)' for today's PT slate.
    """
    local_tz = tz.gettz("America/Los_Angeles")
    today_local = date.today()

    games = fetch_nba_spreads_window(days_ahead=2)
    winpct_map = fetch_team_win_pct_map()

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

        w_home = get_win_pct(g.home_team, winpct_map, default=0.5)
        w_away = get_win_pct(g.away_team, winpct_map, default=0.5)
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
            home = str(e.get("home_team", "")).lower().strip()
            away = str(e.get("away_team", "")).lower().strip()
            state = str(e.get("state", ""))
            if home and away and state:
                status_map[(date_iso, home, away)] = state
    except Exception:
        status_map = {}

    wis = []
    for r in rows:
        if r["date"] != selected_date:
            continue
        state = status_map.get((date_iso, r["home"], r["away"]))
        if state == "post":
            continue
        wis.append(r["wi"])

    if not wis:
        return None

    avg_wi = sum(wis) / len(wis)
    label = watch.awi_label(avg_wi).replace(" game", "")
    return f"Avg Watchability Index: {avg_wi:.0f} ({label})"

def compose_tweet_text():
    today = date.today().strftime("%b %d")
    avg_line = None
    try:
        avg_line = _avg_wi_summary()
    except Exception:
        avg_line = None

    parts = [f"🏀 NBA Watchability — {today}"]
    if avg_line:
        parts.append(avg_line)
    parts.append("")
    parts.append("What to watch tonight, ranked by Watchability Index (WI) (competitiveness + team quality).")
    return "\n".join(parts)
