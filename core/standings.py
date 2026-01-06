from __future__ import annotations

from typing import Dict, Optional, Tuple
import re

def _normalize_team_name(name: str) -> str:
    # Lightweight normalization to improve matching across data sources.
    n = name.lower().strip()
    n = re.sub(r"[^a-z0-9\s]", "", n)
    n = re.sub(r"\s+", " ", n)
    # common aliases
    n = n.replace("la clippers", "los angeles clippers")
    n = n.replace("la lakers", "los angeles lakers")
    n = n.replace("ny knicks", "new york knicks")
    n = n.replace("gs warriors", "golden state warriors")
    return n

def fetch_team_win_pct_map() -> Dict[str, float]:
    """
    Returns dict mapping normalized team name -> win_pct (0..1).
    Uses nba_api LeagueStandings endpoint.
    """
    try:
        from nba_api.stats.endpoints import leaguestandings
        ls = leaguestandings.LeagueStandings()
        df = ls.get_data_frames()[0]

        # Columns typically include: TeamName, WINS, LOSSES, WinPCT
        out: Dict[str, float] = {}
        for _, row in df.iterrows():
            team_name = str(row.get("TeamName", "")).strip()
            winpct = row.get("WinPCT", None)
            if winpct is None:
                # fallback compute
                w = float(row.get("WINS", 0))
                l = float(row.get("LOSSES", 0))
                winpct = w / (w + l) if (w + l) > 0 else 0.5
            out[_normalize_team_name(team_name)] = float(winpct)
        return out
    except Exception:
        # If nba_api fails (rate limits / endpoint quirks), fallback to neutral priors.
        return {}

def get_win_pct(team_name: str, winpct_map: Dict[str, float], default: float = 0.5) -> float:
    key = _normalize_team_name(team_name)
    return float(winpct_map.get(key, default))


def get_record(
    team_name: str,
    record_map: Dict[str, Tuple[int, int]],
    default: Tuple[Optional[int], Optional[int]] = (None, None),
) -> Tuple[Optional[int], Optional[int]]:
    key = _normalize_team_name(team_name)
    return record_map.get(key, default)  # type: ignore[return-value]
