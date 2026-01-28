from core.http_cache import get_json_cached
from dateutil import parser as dtparser

ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)

def _format_live_clock(period, display_clock) -> str | None:
    """
    Returns a compact live-clock string like '5:32 Q3' or '1:12 OT'.
    """
    if not display_clock:
        return None
    try:
        p = int(period) if period is not None else None
    except Exception:
        p = None
    if not p:
        return str(display_clock)
    if p <= 4:
        return f"{display_clock} Q{p}"
    # Overtime periods: 5 => OT, 6 => 2OT, etc.
    ot_num = p - 4
    ot_label = "OT" if ot_num == 1 else f"{ot_num}OT"
    return f"{display_clock} {ot_label}"


def fetch_games_for_date(date):
    ymd = date.strftime("%Y%m%d")
    url = f"{ESPN_SCOREBOARD}?dates={ymd}"

    resp = get_json_cached(
        url,
        namespace="espn",
        cache_key=f"scoreboard:{ymd}",
        ttl_seconds=60,
        timeout_seconds=10,
    )
    data = resp.data

    games = []
    for event in data.get("events", []):
        competition = event["competitions"][0]
        teams = competition["competitors"]

        home = next(t for t in teams if t["homeAway"] == "home")
        away = next(t for t in teams if t["homeAway"] == "away")

        status_obj = competition.get("status", {})
        status = status_obj.get("type", {}).get("state")  # pre / in / post
        start_time = competition["date"]
        period = status_obj.get("period")
        display_clock = status_obj.get("displayClock") or status_obj.get("clock")
        time_remaining = _format_live_clock(period, display_clock) if status == "in" else None

        games.append({
            "game_id": event["id"],
            "date": date,
            "start_time_utc": start_time,
            "home_team": home["team"]["displayName"],
            "away_team": away["team"]["displayName"],
            "state": status,
            "home_score": home.get("score"),
            "away_score": away.get("score"),
            "time_remaining": time_remaining,
        })

    return games

def fetch_games_for_week(week_dates):
    all_games = []
    for d in week_dates:
        all_games.extend(fetch_games_for_date(d))
    return all_games
