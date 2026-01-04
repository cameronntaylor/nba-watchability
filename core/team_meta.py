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
    return name.lower().strip()


def get_team_abbr(team_name: str) -> str | None:
    return TEAM_ABBR.get(normalize_team_name(team_name))


def get_logo_url(team_name: str, size: int = 500) -> str | None:
    abbr = get_team_abbr(team_name)
    if not abbr:
        return None
    return f"https://a.espncdn.com/i/teamlogos/nba/{size}/{abbr}.png"
