from __future__ import annotations

import re
from typing import Optional

# Canonical mapping: normalized team name -> ESPN abbreviation

TEAM_ABBR = {
    "atlanta hawks": "ATL",
    "boston celtics": "BOS",
    "brooklyn nets": "BKN",
    "charlotte hornets": "CHA",
    "chicago bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",
    "denver nuggets": "DEN",
    "detroit pistons": "DET",
    "golden state warriors": "GSW",
    "houston rockets": "HOU",
    "indiana pacers": "IND",
    "los angeles clippers": "LAC",
    "los angeles lakers": "LAL",
    "memphis grizzlies": "MEM",
    "miami heat": "MIA",
    "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "new orleans pelicans": "NO",
    "new york knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX",
    "portland trail blazers": "POR",
    "sacramento kings": "SAC",
    "san antonio spurs": "SAS",
    "toronto raptors": "TOR",
    "utah jazz": "UTAH",
    "washington wizards": "WAS",
}


def normalize_team_name(name: str) -> str:
    # Keep in sync with `core.standings._normalize_team_name` behavior (but avoid importing it here).
    n = name.lower().strip()
    n = re.sub(r"[^a-z0-9\s]", "", n)
    n = re.sub(r"\s+", " ", n)
    # common aliases
    n = n.replace("la clippers", "los angeles clippers")
    n = n.replace("la lakers", "los angeles lakers")
    n = n.replace("ny knicks", "new york knicks")
    n = n.replace("gs warriors", "golden state warriors")
    return n


def get_team_abbr(team_name: str) -> Optional[str]:
    return TEAM_ABBR.get(normalize_team_name(team_name))


def get_logo_url(team_name: str, size: int = 500) -> Optional[str]:
    abbr = get_team_abbr(team_name)
    if not abbr:
        return None
    # ESPN's CDN does not consistently support arbitrary sizes (e.g. 80px 404s),
    # so clamp to known-safe sizes.
    size_i = int(size) if size is not None else 500
    if size_i not in {500, 200}:
        size_i = 500
    return f"https://a.espncdn.com/i/teamlogos/nba/{size_i}/{abbr}.png"
