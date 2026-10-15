from __future__ import annotations

import datetime as dt
import json
import math
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

from core.team_meta import TEAM_ABBR, normalize_team_name
from core.watchability import awi_label


# These are intentionally centralized so the first-pass product weights are easy to tune.
TEAM_FAN_LAMBDA = 0.35
FAVORITE_PLAYER_LAMBDA = 0.25
TEAM_COMPONENT_WEIGHTS = {
    "own_team": 0.45,
    "upcoming_opponent": 0.20,
    "rival": 0.20,
    "former_player": 0.15,
}


NBA_TEAMS = tuple(
    sorted(
        {
            "Atlanta Hawks",
            "Boston Celtics",
            "Brooklyn Nets",
            "Charlotte Hornets",
            "Chicago Bulls",
            "Cleveland Cavaliers",
            "Dallas Mavericks",
            "Denver Nuggets",
            "Detroit Pistons",
            "Golden State Warriors",
            "Houston Rockets",
            "Indiana Pacers",
            "LA Clippers",
            "Los Angeles Lakers",
            "Memphis Grizzlies",
            "Miami Heat",
            "Milwaukee Bucks",
            "Minnesota Timberwolves",
            "New Orleans Pelicans",
            "New York Knicks",
            "Oklahoma City Thunder",
            "Orlando Magic",
            "Philadelphia 76ers",
            "Phoenix Suns",
            "Portland Trail Blazers",
            "Sacramento Kings",
            "San Antonio Spurs",
            "Toronto Raptors",
            "Utah Jazz",
            "Washington Wizards",
        }
    )
)


# Primary/secondary colors are used for a restrained team-themed dashboard background.
TEAM_COLORS = {
    "atlanta hawks": ("#E03A3E", "#C1D32F"),
    "boston celtics": ("#007A33", "#BA9653"),
    "brooklyn nets": ("#000000", "#FFFFFF"),
    "charlotte hornets": ("#1D1160", "#00788C"),
    "chicago bulls": ("#CE1141", "#000000"),
    "cleveland cavaliers": ("#860038", "#FDBB30"),
    "dallas mavericks": ("#00538C", "#B8C4CA"),
    "denver nuggets": ("#0E2240", "#FEC524"),
    "detroit pistons": ("#C8102E", "#1D42BA"),
    "golden state warriors": ("#1D428A", "#FFC72C"),
    "houston rockets": ("#CE1141", "#000000"),
    "indiana pacers": ("#002D62", "#FDBB30"),
    "los angeles clippers": ("#C8102E", "#1D428A"),
    "los angeles lakers": ("#552583", "#FDB927"),
    "memphis grizzlies": ("#5D76A9", "#12173F"),
    "miami heat": ("#98002E", "#F9A01B"),
    "milwaukee bucks": ("#00471B", "#EEE1C6"),
    "minnesota timberwolves": ("#0C2340", "#78BE20"),
    "new orleans pelicans": ("#0C2340", "#C8102E"),
    "new york knicks": ("#006BB6", "#F58426"),
    "oklahoma city thunder": ("#007AC1", "#EF3B24"),
    "orlando magic": ("#0077C0", "#C4CED4"),
    "philadelphia 76ers": ("#006BB6", "#ED174C"),
    "phoenix suns": ("#1D1160", "#E56020"),
    "portland trail blazers": ("#E03A3E", "#000000"),
    "sacramento kings": ("#5A2D81", "#63727A"),
    "san antonio spurs": ("#000000", "#C4CED4"),
    "toronto raptors": ("#CE1141", "#000000"),
    "utah jazz": ("#002B5C", "#F9A01B"),
    "washington wizards": ("#002B5C", "#E31837"),
}


RIVALS = {
    "Atlanta Hawks": ((), ("New York Knicks", "Miami Heat")),
    "Boston Celtics": (("Los Angeles Lakers", "Philadelphia 76ers", "Miami Heat"), ("New York Knicks", "Milwaukee Bucks")),
    "Brooklyn Nets": ((), ("New York Knicks", "Boston Celtics", "Philadelphia 76ers")),
    "Charlotte Hornets": ((), ("Miami Heat",)),
    "Chicago Bulls": (("Detroit Pistons",), ("Milwaukee Bucks", "New York Knicks")),
    "Cleveland Cavaliers": ((), ("Boston Celtics", "New York Knicks", "Golden State Warriors")),
    "Dallas Mavericks": (("Los Angeles Lakers",), ("San Antonio Spurs", "LA Clippers")),
    "Denver Nuggets": (("Minnesota Timberwolves",), ("Oklahoma City Thunder", "Los Angeles Lakers")),
    "Detroit Pistons": (("Indiana Pacers",), ("Chicago Bulls", "New York Knicks", "Boston Celtics")),
    "Golden State Warriors": (("Houston Rockets", "Los Angeles Lakers"), ("Sacramento Kings", "Memphis Grizzlies")),
    "Houston Rockets": (("Golden State Warriors", "San Antonio Spurs"), ("Utah Jazz", "Dallas Mavericks")),
    "Indiana Pacers": (("New York Knicks", "Detroit Pistons", "Milwaukee Bucks"), ("Boston Celtics",)),
    "LA Clippers": (("Los Angeles Lakers",), ("Dallas Mavericks", "Phoenix Suns")),
    "Los Angeles Lakers": (("Boston Celtics", "Golden State Warriors"), ("Dallas Mavericks", "Denver Nuggets")),
    "Memphis Grizzlies": (("Golden State Warriors",), ("Oklahoma City Thunder", "Los Angeles Lakers", "LA Clippers")),
    "Miami Heat": (("Boston Celtics", "New York Knicks"), ("Milwaukee Bucks", "Indiana Pacers")),
    "Milwaukee Bucks": (("Indiana Pacers",), ("Boston Celtics", "Miami Heat", "Chicago Bulls")),
    "Minnesota Timberwolves": (("Denver Nuggets",), ("Oklahoma City Thunder", "Golden State Warriors")),
    "New Orleans Pelicans": ((), ("Memphis Grizzlies",)),
    "New York Knicks": (("Indiana Pacers", "Boston Celtics"), ("Miami Heat", "Philadelphia 76ers")),
    "Oklahoma City Thunder": (("San Antonio Spurs",), ("Denver Nuggets", "Minnesota Timberwolves", "Dallas Mavericks")),
    "Orlando Magic": ((), ("Cleveland Cavaliers", "Miami Heat")),
    "Philadelphia 76ers": (("Boston Celtics",), ("New York Knicks", "Toronto Raptors")),
    "Phoenix Suns": ((), ("Los Angeles Lakers", "Dallas Mavericks", "San Antonio Spurs")),
    "Portland Trail Blazers": (("Los Angeles Lakers",), ("Denver Nuggets",)),
    "Sacramento Kings": (("Golden State Warriors", "Los Angeles Lakers"), ()),
    "San Antonio Spurs": (("Oklahoma City Thunder", "Houston Rockets"), ("Dallas Mavericks", "New York Knicks")),
    "Toronto Raptors": ((), ("Philadelphia 76ers", "Boston Celtics")),
    "Utah Jazz": ((), ("Houston Rockets", "Los Angeles Lakers")),
    "Washington Wizards": ((), ()),
}


@dataclass(frozen=True)
class PlayerTeam:
    name: str
    team: str


FAVORITE_PLAYERS = (
    PlayerTeam("Stephen Curry", "Golden State Warriors"),
    PlayerTeam("LeBron James", "Philadelphia 76ers"),
    PlayerTeam("Luka Dončić", "Los Angeles Lakers"),
    PlayerTeam("Victor Wembanyama", "San Antonio Spurs"),
    PlayerTeam("Giannis Antetokounmpo", "Miami Heat"),
    PlayerTeam("Nikola Jokić", "Denver Nuggets"),
    PlayerTeam("Shai Gilgeous-Alexander", "Oklahoma City Thunder"),
    PlayerTeam("Anthony Edwards", "Minnesota Timberwolves"),
    PlayerTeam("Jalen Brunson", "New York Knicks"),
    PlayerTeam("Kevin Durant", "Houston Rockets"),
    PlayerTeam("Jayson Tatum", "Boston Celtics"),
    PlayerTeam("Cooper Flagg", "Dallas Mavericks"),
    PlayerTeam("Tyrese Maxey", "Philadelphia 76ers"),
    PlayerTeam("Cade Cunningham", "Detroit Pistons"),
    PlayerTeam("Devin Booker", "Phoenix Suns"),
    PlayerTeam("Donovan Mitchell", "Cleveland Cavaliers"),
    PlayerTeam("Jaylen Brown", "Philadelphia 76ers"),
    PlayerTeam("LaMelo Ball", "Minnesota Timberwolves"),
    PlayerTeam("Ja Morant", "Portland Trail Blazers"),
    PlayerTeam("Kyrie Irving", "Dallas Mavericks"),
    PlayerTeam("Karl-Anthony Towns", "New York Knicks"),
    PlayerTeam("Austin Reaves", "Los Angeles Lakers"),
    PlayerTeam("Trae Young", "Washington Wizards"),
    PlayerTeam("Deni Avdija", "Portland Trail Blazers"),
    PlayerTeam("Alperen Şengün", "Houston Rockets"),
    PlayerTeam("Kawhi Leonard", "Toronto Raptors"),
    PlayerTeam("Jimmy Butler", "Golden State Warriors"),
    PlayerTeam("Klay Thompson", "Miami Heat"),
    PlayerTeam("James Harden", "Cleveland Cavaliers"),
    PlayerTeam("Paolo Banchero", "Orlando Magic"),
)
FAVORITE_PLAYER_BY_NAME = {p.name: p for p in FAVORITE_PLAYERS}


# (player, prior team, current team, high-priority former-player story)
FORMER_PLAYERS = (
    ("Giannis Antetokounmpo", "Milwaukee Bucks", "Miami Heat", True),
    ("LeBron James", "Los Angeles Lakers", "Philadelphia 76ers", True),
    ("Jaylen Brown", "Boston Celtics", "Philadelphia 76ers", True),
    ("Ja Morant", "Memphis Grizzlies", "Portland Trail Blazers", True),
    ("LaMelo Ball", "Charlotte Hornets", "Minnesota Timberwolves", True),
    ("Kawhi Leonard", "LA Clippers", "Toronto Raptors", False),
    ("Julius Randle", "Minnesota Timberwolves", "Brooklyn Nets", False),
    ("Paul George", "Philadelphia 76ers", "Boston Celtics", False),
    ("Tyler Herro", "Miami Heat", "Milwaukee Bucks", True),
    ("DeMar DeRozan", "Sacramento Kings", "Denver Nuggets", False),
    ("Klay Thompson", "Dallas Mavericks", "Miami Heat", False),
    ("Brandon Ingram", "Toronto Raptors", "LA Clippers", False),
    ("Naz Reid", "Minnesota Timberwolves", "Charlotte Hornets", False),
    ("Nic Claxton", "Brooklyn Nets", "Chicago Bulls", False),
    ("Bobby Portis", "Milwaukee Bucks", "Miami Heat", True),
    ("Mitchell Robinson", "New York Knicks", "Boston Celtics", True),
    ("Luguentz Dort", "Oklahoma City Thunder", "Atlanta Hawks", True),
    ("Norman Powell", "Miami Heat", "Chicago Bulls", False),
    ("Miles Bridges", "Charlotte Hornets", "Phoenix Suns", False),
    ("Walker Kessler", "Utah Jazz", "Los Angeles Lakers", False),
    ("Jerami Grant", "Portland Trail Blazers", "Memphis Grizzlies", False),
    ("Santi Aldama", "Memphis Grizzlies", "Dallas Mavericks", False),
    ("Isaiah Stewart", "Detroit Pistons", "Memphis Grizzlies", False),
    ("Jaime Jaquez Jr.", "Miami Heat", "Milwaukee Bucks", False),
    ("Deandre Ayton", "Los Angeles Lakers", "Washington Wizards", False),
    ("Anfernee Simons", "Chicago Bulls", "Philadelphia 76ers", False),
    ("Rui Hachimura", "Los Angeles Lakers", "LA Clippers", False),
    ("Mike Conley", "Minnesota Timberwolves", "Boston Celtics", False),
    ("Klay Thompson", "Golden State Warriors", "Miami Heat", False),
)


def _player_key(name: object) -> str:
    value = unicodedata.normalize("NFKD", str(name or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _to_date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def _float_score(value: object) -> float:
    try:
        score = float(value)
    except Exception:
        return 0.0
    if math.isnan(score):
        return 0.0
    return max(0.0, min(100.0, score))


def _injury_entries(row: pd.Series, side: str) -> list[dict]:
    raw = row.get(f"{side} injuries detail JSON")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    try:
        parsed = json.loads(str(raw))
    except Exception:
        return []
    return [x for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []


def _player_is_available(row: pd.Series, player: PlayerTeam) -> bool:
    player_team = normalize_team_name(player.team)
    side = None
    if normalize_team_name(str(row.get("Away team") or "")) == player_team:
        side = "Away"
    elif normalize_team_name(str(row.get("Home team") or "")) == player_team:
        side = "Home"
    if side is None:
        return False

    player_key = _player_key(player.name)
    unavailable_markers = ("out", "injured", "doubtful", "suspension")
    for entry in _injury_entries(row, side):
        if _player_key(entry.get("player")) != player_key:
            continue
        status = str(entry.get("status") or "").strip().lower()
        return not any(marker in status for marker in unavailable_markers)

    # Fallback for older artifacts that only include the compact key-injury string.
    compact = str(row.get(f"{side} Key Injuries") or "")
    compact_key = _player_key(compact)
    if player_key and player_key in compact_key:
        lowered = compact.lower()
        return not any(marker in lowered for marker in unavailable_markers)
    return True


def _team_opponent_schedule(df: pd.DataFrame, favorite_team: str) -> list[tuple[dt.date, str]]:
    team_key = normalize_team_name(favorite_team)
    games: list[tuple[dt.date, str]] = []
    for _, row in df.iterrows():
        away = normalize_team_name(str(row.get("Away team") or ""))
        home = normalize_team_name(str(row.get("Home team") or ""))
        game_date = _to_date(row.get("Local date"))
        if game_date is None:
            continue
        if away == team_key and home:
            games.append((game_date, home))
        elif home == team_key and away:
            games.append((game_date, away))
    return sorted(games)


def _upcoming_opponent_score(
    row: pd.Series,
    *,
    favorite_team_key: str,
    opponent_schedule: Sequence[tuple[dt.date, str]],
) -> tuple[float, str]:
    away = normalize_team_name(str(row.get("Away team") or ""))
    home = normalize_team_name(str(row.get("Home team") or ""))
    if favorite_team_key in {away, home}:
        return 0.0, ""
    row_date = _to_date(row.get("Local date"))
    if row_date is None:
        return 0.0, ""
    participants = {away, home} - {""}
    best = 0.0
    best_days = None
    for game_date, opponent in opponent_schedule:
        delta = (game_date - row_date).days
        if opponent not in participants or delta < 0 or delta > 7:
            continue
        score = 100.0 if delta <= 2 else 50.0
        if score > best or (score == best and (best_days is None or delta < best_days)):
            best = score
            best_days = delta
    if best_days is None:
        return 0.0, ""
    unit = "day" if best_days == 1 else "days"
    return best, f"Opponent in {best_days} {unit}"


def _rival_score(row: pd.Series, favorite_team: str) -> tuple[float, str]:
    major, meaningful = RIVALS.get(favorite_team, ((), ()))
    participants = {
        normalize_team_name(str(row.get("Away team") or "")),
        normalize_team_name(str(row.get("Home team") or "")),
    }
    if participants & {normalize_team_name(x) for x in major}:
        return 100.0, "Major rival"
    if participants & {normalize_team_name(x) for x in meaningful}:
        return 50.0, "Rival"
    return 0.0, ""


def _former_player_score(row: pd.Series, favorite_team: str) -> tuple[float, str]:
    favorite_key = normalize_team_name(favorite_team)
    participants = {
        normalize_team_name(str(row.get("Away team") or "")),
        normalize_team_name(str(row.get("Home team") or "")),
    }
    best_score = 0.0
    best_name = ""
    for name, old_team, new_team, high in FORMER_PLAYERS:
        if normalize_team_name(old_team) != favorite_key or normalize_team_name(new_team) not in participants:
            continue
        score = 100.0 if high else 50.0
        if score > best_score:
            best_score = score
            best_name = name
    return best_score, f"Former player: {best_name}" if best_name else ""


def apply_personalization(
    df: pd.DataFrame,
    *,
    favorite_team: str | None = None,
    favorite_players: Iterable[str] = (),
    team_lambda: float = TEAM_FAN_LAMBDA,
    player_lambda: float = FAVORITE_PLAYER_LAMBDA,
) -> pd.DataFrame:
    """Return a copy with contextual scores applied to ``aWI`` and ``Region``."""
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()

    out = df.copy()
    out["Base aWI"] = pd.to_numeric(out.get("aWI"), errors="coerce").fillna(0.0).clip(0.0, 100.0)
    out["Base Region"] = out.get("Region", "")
    out["Team fan score"] = 0.0
    out["Own team score"] = 0.0
    out["Upcoming opponent score"] = 0.0
    out["Rival score"] = 0.0
    out["Former player score"] = 0.0
    out["Favorite player score"] = 0.0
    out["Personalization notes"] = ""

    favorite_team = favorite_team if favorite_team in NBA_TEAMS else None
    selected_players = [FAVORITE_PLAYER_BY_NAME[name] for name in favorite_players if name in FAVORITE_PLAYER_BY_NAME]
    selected_players = selected_players[:5]
    team_mix = max(0.0, min(1.0, float(team_lambda)))
    player_mix = max(0.0, min(1.0, float(player_lambda)))
    opponent_schedule = _team_opponent_schedule(out, favorite_team) if favorite_team else []
    favorite_team_key = normalize_team_name(favorite_team) if favorite_team else ""

    def personalize_row(row: pd.Series) -> pd.Series:
        score = _float_score(row.get("Base aWI"))
        notes: list[str] = []
        own = upcoming = rival = former = team_score = 0.0

        if favorite_team:
            participants = {
                normalize_team_name(str(row.get("Away team") or "")),
                normalize_team_name(str(row.get("Home team") or "")),
            }
            if favorite_team_key in participants:
                own = 100.0
                notes.append("Your team")
            upcoming, upcoming_note = _upcoming_opponent_score(
                row,
                favorite_team_key=favorite_team_key,
                opponent_schedule=opponent_schedule,
            )
            rival, rival_note = _rival_score(row, favorite_team)
            former, former_note = _former_player_score(row, favorite_team)
            for value, note in ((upcoming, upcoming_note), (rival, rival_note), (former, former_note)):
                if value > 0 and note:
                    notes.append(note)
            team_score = (
                TEAM_COMPONENT_WEIGHTS["own_team"] * own
                + TEAM_COMPONENT_WEIGHTS["upcoming_opponent"] * upcoming
                + TEAM_COMPONENT_WEIGHTS["rival"] * rival
                + TEAM_COMPONENT_WEIGHTS["former_player"] * former
            )
            score = (1.0 - team_mix) * score + team_mix * team_score

        player_score = 0.0
        available_names: list[str] = []
        unavailable_names: list[str] = []
        participants = {
            normalize_team_name(str(row.get("Away team") or "")),
            normalize_team_name(str(row.get("Home team") or "")),
        }
        for player in selected_players:
            if normalize_team_name(player.team) not in participants:
                continue
            if _player_is_available(row, player):
                available_names.append(player.name)
            else:
                unavailable_names.append(player.name)
        if available_names:
            player_score = 100.0
            notes.extend(f"Favorite: {name}" for name in available_names)
        notes.extend(f"Unavailable: {name}" for name in unavailable_names)
        if selected_players:
            score = (1.0 - player_mix) * score + player_mix * player_score

        score = max(0.0, min(100.0, score))
        return pd.Series(
            {
                "aWI": score,
                "Uavg": score / 100.0,
                "Region": awi_label(score),
                "Team fan score": team_score,
                "Own team score": own,
                "Upcoming opponent score": upcoming,
                "Rival score": rival,
                "Former player score": former,
                "Favorite player score": player_score,
                "Personalization notes": "|".join(dict.fromkeys(notes)),
            }
        )

    personalized = out.apply(personalize_row, axis=1)
    for column in personalized.columns:
        out[column] = personalized[column]
    out["Personalization active"] = bool(favorite_team or selected_players)
    return out


def team_theme(team: str | None) -> tuple[str, str] | None:
    if not team:
        return None
    return TEAM_COLORS.get(normalize_team_name(team))


# Guard against accidentally dropping or adding a team without updating the UI list.
assert len(TEAM_ABBR) == 30
assert len(NBA_TEAMS) == 30
