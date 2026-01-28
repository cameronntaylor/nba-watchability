from core.http_cache import get_json_cached

from core.standings import _normalize_team_name

ESPN_STANDINGS_URL = (
    "https://site.web.api.espn.com/apis/v2/sports/basketball/nba/standings"
)

def _to_int(x):
    try:
        return int(float(x))
    except Exception:
        return None


def _to_float(x):
    try:
        if x is None:
            return None
        if isinstance(x, str) and x.strip() in {"—", "-", ""}:
            return 0.0
        return float(x)
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
    resp = get_json_cached(
        ESPN_STANDINGS_URL,
        namespace="espn",
        cache_key="standings:v2",
        ttl_seconds=60 * 60,
        timeout_seconds=10,
    )
    data = resp.data

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


def _extract_conference_entries(data):
    """
    Attempts to extract separate entries lists for East/West from ESPN's nested structure.
    Falls back to a single list if conference nodes aren't found.
    """
    out = []

    def walk(obj):
        if isinstance(obj, dict):
            name = obj.get("name")
            standings = obj.get("standings")
            if isinstance(name, str) and isinstance(standings, dict):
                entries = standings.get("entries")
                if isinstance(entries, list) and entries:
                    n = name.lower()
                    if "conference" in n and ("east" in n or "west" in n):
                        out.append((name, entries))
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(data)
    if out:
        return out
    return [("Unknown", _extract_entries(data))]


def fetch_team_standings_detail_maps():
    """
    Returns (winpct_map, record_map, detail_map) where keys are normalized team names.

    detail_map[name] = {
      'wins': int|None,
      'losses': int|None,
      'win_pct': float|None,
      'games_behind': float|None,
      'playoff_seed': int|None,
      'conference': 'east'|'west'|None
    }
    """
    resp = get_json_cached(
        ESPN_STANDINGS_URL,
        namespace="espn",
        cache_key="standings:v2",
        ttl_seconds=60 * 60,
        timeout_seconds=10,
    )
    data = resp.data

    winpct_map = {}
    record_map = {}
    detail_map = {}

    for conf_name, entries in _extract_conference_entries(data):
        conf = None
        n = str(conf_name).lower()
        if "east" in n:
            conf = "east"
        elif "west" in n:
            conf = "west"

        for entry in entries:
            team = entry.get("team", {}).get("displayName")
            if not team:
                continue
            key = _normalize_team_name(team)
            stats = {s.get("name"): s.get("value") for s in entry.get("stats", [])}

            wins = _to_int(stats.get("wins"))
            losses = _to_int(stats.get("losses"))
            win_pct = stats.get("winPercent")
            if win_pct is None and wins is not None and losses is not None:
                win_pct = wins / (wins + losses) if (wins + losses) else None
            if win_pct is not None:
                winpct_map[key] = float(win_pct)
            if wins is not None and losses is not None:
                record_map[key] = (wins, losses)

            gb = _to_float(stats.get("gamesBehind"))
            seed = _to_int(stats.get("playoffSeed"))

            detail_map[key] = {
                "wins": wins,
                "losses": losses,
                "win_pct": None if win_pct is None else float(win_pct),
                "games_behind": gb,
                "playoff_seed": seed,
                "conference": conf,
            }

    if not detail_map:
        # Fallback to win/record only.
        winpct_map, record_map = fetch_team_standings_maps()
        for k in set(list(winpct_map.keys()) + list(record_map.keys())):
            w, l = record_map.get(k, (None, None))
            detail_map[k] = {
                "wins": w,
                "losses": l,
                "win_pct": winpct_map.get(k),
                "games_behind": None,
                "playoff_seed": None,
                "conference": None,
            }

    return winpct_map, record_map, detail_map
