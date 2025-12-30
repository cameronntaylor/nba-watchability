import requests
from dateutil import parser as dtparser

ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)

def fetch_games_for_date(date):
    ymd = date.strftime("%Y%m%d")
    url = f"{ESPN_SCOREBOARD}?dates={ymd}"

    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()

    games = []
    for event in data.get("events", []):
        competition = event["competitions"][0]
        teams = competition["competitors"]

        home = next(t for t in teams if t["homeAway"] == "home")
        away = next(t for t in teams if t["homeAway"] == "away")

        status = competition["status"]["type"]["state"]  # pre / in / post
        start_time = competition["date"]

        games.append({
            "game_id": event["id"],
            "date": date,
            "start_time_utc": start_time,
            "home_team": home["team"]["displayName"],
            "away_team": away["team"]["displayName"],
            "state": status,
            "home_score": home.get("score"),
            "away_score": away.get("score"),
        })

    return games

def fetch_games_for_week(week_dates):
    all_games = []
    for d in week_dates:
        all_games.extend(fetch_games_for_date(d))
    return all_games