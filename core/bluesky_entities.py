from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from core.team_meta import TEAM_ABBR, TEAM_MASCOT, normalize_team_name


# Aliases already used by the Bluesky first-pass vocabulary that are not simply
# a team's full name or mascot.
EXTRA_TEAM_ALIASES: dict[str, str] = {
    "cavs": "cleveland cavaliers",
    "mavs": "dallas mavericks",
    "la clippers": "los angeles clippers",
    "la lakers": "los angeles lakers",
    "sixers": "philadelphia 76ers",
    "76ers": "philadelphia 76ers",
    "blazers": "portland trail blazers",
}

# Player shorthand present in config/bluesky_nba_terms.json. ESPN provides full
# roster names, so these aliases bridge the collector vocabulary to that roster.
PLAYER_ALIASES: dict[str, str] = {
    "lebron": "lebron james",
    "steph curry": "stephen curry",
    "sga": "shai gilgeous-alexander",
    "wembanyama": "victor wembanyama",
}


def normalize_entity_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.casefold().replace("’", "'")
    ascii_text = re.sub(r"[^a-z0-9\s'-]", " ", ascii_text)
    return " ".join(ascii_text.split())


def team_alias_index() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for team_name in TEAM_ABBR:
        canonical = normalize_team_name(team_name)
        aliases[normalize_entity_name(team_name)] = canonical
        mascot = TEAM_MASCOT.get(canonical)
        if mascot:
            aliases[normalize_entity_name(mascot)] = canonical
    for alias, team_name in EXTRA_TEAM_ALIASES.items():
        aliases[normalize_entity_name(alias)] = normalize_team_name(team_name)
    return aliases


@dataclass(frozen=True)
class RosterLoadResult:
    player_teams: dict[str, str]
    teams_loaded: tuple[str, ...]
    teams_failed: tuple[str, ...]


def build_player_team_map(
    team_ids: Mapping[str, str],
    rosters: Mapping[str, Sequence[tuple[str, str, str | None]]],
) -> dict[str, str]:
    """Build normalized player name -> canonical team name from ESPN-shaped data."""
    player_teams: dict[str, str] = {}
    for raw_team_name, team_id in team_ids.items():
        team_name = normalize_team_name(raw_team_name)
        if team_name not in TEAM_ABBR:
            continue
        for _athlete_id, player_name, _status in rosters.get(str(team_id), ()):  # pragma: no branch
            normalized_player = normalize_entity_name(player_name)
            if normalized_player:
                player_teams[normalized_player] = team_name
    return player_teams


def load_espn_player_team_map(*, roster_ttl_seconds: int = 24 * 60 * 60) -> RosterLoadResult:
    """Fetch current NBA rosters while tolerating an individual team failure."""
    from core.health_espn import fetch_team_id_map, fetch_team_roster

    team_ids = fetch_team_id_map(ttl_seconds=roster_ttl_seconds)
    rosters: dict[str, Sequence[tuple[str, str, str | None]]] = {}
    loaded: list[str] = []
    failed: list[str] = []
    for raw_team_name, team_id in sorted(team_ids.items()):
        team_name = normalize_team_name(raw_team_name)
        if team_name not in TEAM_ABBR:
            continue
        try:
            rosters[str(team_id)] = fetch_team_roster(
                str(team_id), ttl_seconds=roster_ttl_seconds
            )
            loaded.append(team_name)
        except Exception:
            failed.append(team_name)

    return RosterLoadResult(
        player_teams=build_player_team_map(team_ids, rosters),
        teams_loaded=tuple(sorted(loaded)),
        teams_failed=tuple(sorted(failed)),
    )


@dataclass(frozen=True)
class ResolvedEntities:
    teams: tuple[str, ...]
    direct_teams: tuple[str, ...]
    player_teams: tuple[str, ...]
    players: tuple[str, ...]


class BlueskyEntityResolver:
    """Resolve retained post terms and roster-player mentions to canonical teams."""

    def __init__(
        self,
        player_teams: Mapping[str, str],
        *,
        team_aliases: Mapping[str, str] | None = None,
        player_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self.team_aliases = dict(team_aliases or team_alias_index())
        self.player_aliases = {
            normalize_entity_name(alias): normalize_entity_name(player)
            for alias, player in (player_aliases or PLAYER_ALIASES).items()
        }
        self.player_teams = {
            normalize_entity_name(player): normalize_team_name(team)
            for player, team in player_teams.items()
            if normalize_entity_name(player) and normalize_team_name(team) in TEAM_ABBR
        }
        player_patterns: list[tuple[str, re.Pattern[str]]] = []
        for player in sorted(self.player_teams, key=lambda value: (-len(value), value)):
            escaped_player = re.escape(player).replace(r"\ ", r"\s+")
            player_patterns.append(
                (
                    player,
                    re.compile(rf"(?<!\w){escaped_player}(?!\w)", re.IGNORECASE),
                )
            )
        self._player_patterns = tuple(player_patterns)

    def resolve(self, matched_terms: Iterable[str], *, text: str = "") -> ResolvedEntities:
        normalized_terms = {normalize_entity_name(term) for term in matched_terms if term}
        direct_teams = {
            self.team_aliases[term]
            for term in normalized_terms
            if term in self.team_aliases
        }

        players: set[str] = set()
        for term in normalized_terms:
            canonical_player = self.player_aliases.get(term, term)
            if canonical_player in self.player_teams:
                players.add(canonical_player)

        normalized_text = normalize_entity_name(text)
        if normalized_text:
            for player, pattern in self._player_patterns:
                if pattern.search(normalized_text):
                    players.add(player)

        player_teams = {self.player_teams[player] for player in players}
        return ResolvedEntities(
            teams=tuple(sorted(direct_teams | player_teams)),
            direct_teams=tuple(sorted(direct_teams)),
            player_teams=tuple(sorted(player_teams)),
            players=tuple(sorted(players)),
        )
