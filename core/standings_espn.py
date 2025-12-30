import requests

from core.standings import _normalize_team_name

ESPN_STANDINGS_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/standings"
)

def _extract_entries(data):
    standings = data.get("standings")
    if standings and "entries" in standings:
        return standings["entries"]

    for child in data.get("children", []):
        standings = child.get("standings")
        if standings and "entries" in standings:
            return standings["entries"]

    for sport in data.get("sports", []):
        for league in sport.get("leagues", []):
            standings = league.get("standings")
            if standings and "entries" in standings:
                return standings["entries"]

    return []


def fetch_team_win_pct_map():
    r = requests.get(ESPN_STANDINGS_URL, timeout=10)
    r.raise_for_status()
    data = r.json()

    entries = _extract_entries(data)
    if not entries:
        return {}

    out = {}
    for entry in entries:
        team = entry.get("team", {}).get("displayName")
        if not team:
            continue
        stats = {s.get("name"): s.get("value") for s in entry.get("stats", [])}
        wins = stats.get("wins")
        losses = stats.get("losses")
        if wins is not None and losses is not None:
            out[_normalize_team_name(team)] = wins / (wins + losses)

    return out
