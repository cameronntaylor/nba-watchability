import requests

from core.standings import _normalize_team_name

ESPN_STANDINGS_URL = (
    "https://site.web.api.espn.com/apis/v2/sports/basketball/nba/standings"
)


def _extract_entries(data):
    entries = []

    def walk(obj):
        if isinstance(obj, dict):
            standings = obj.get("standings")
            if isinstance(standings, dict):
                s_entries = standings.get("entries")
                if isinstance(s_entries, list) and s_entries:
                    entries.extend(s_entries)
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(data)
    return entries


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
        win_pct = stats.get("winPercent")
        if win_pct is None:
            wins = stats.get("wins")
            losses = stats.get("losses")
            if wins is not None and losses is not None:
                win_pct = wins / (wins + losses)
        if win_pct is not None:
            out[_normalize_team_name(team)] = float(win_pct)

    return out
