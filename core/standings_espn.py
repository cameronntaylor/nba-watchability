import requests

from core.standings import _normalize_team_name

ESPN_STANDINGS_URL = (
    "https://site.web.api.espn.com/apis/v2/sports/basketball/nba/standings"
)

def _to_int(x):
    try:
        return int(float(x))
    except Exception:
        return None


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


def fetch_team_standings_maps():
    """
    Returns (winpct_map, record_map) where keys are normalized team names.
      - winpct_map: name -> float (0..1)
      - record_map: name -> (wins:int, losses:int)
    """
    r = requests.get(ESPN_STANDINGS_URL, timeout=10)
    r.raise_for_status()
    data = r.json()

    entries = _extract_entries(data)
    if not entries:
        return {}, {}

    winpct_map = {}
    record_map = {}
    for entry in entries:
        team = entry.get("team", {}).get("displayName")
        if not team:
            continue
        stats = {s.get("name"): s.get("value") for s in entry.get("stats", [])}

        wins = _to_int(stats.get("wins"))
        losses = _to_int(stats.get("losses"))
        if wins is not None and losses is not None:
            record_map[_normalize_team_name(team)] = (wins, losses)

        win_pct = stats.get("winPercent")
        if win_pct is None and wins is not None and losses is not None:
            win_pct = wins / (wins + losses) if (wins + losses) else None
        if win_pct is not None:
            winpct_map[_normalize_team_name(team)] = float(win_pct)

    return winpct_map, record_map


def fetch_team_win_pct_map():
    winpct_map, _ = fetch_team_standings_maps()
    return winpct_map


def fetch_team_record_map():
    _, record_map = fetch_team_standings_maps()
    return record_map
