#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bluesky_entities import (  # noqa: E402
    BlueskyEntityResolver,
    load_espn_player_team_map,
)
from core.team_meta import TEAM_ABBR  # noqa: E402


DEFAULT_DB = ROOT / "data" / "conversation" / "bluesky.sqlite"


def recent_posts(connection: sqlite3.Connection, hours: int) -> list[sqlite3.Row]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=max(0, hours))
    cutoff_iso = cutoff.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return connection.execute(
        """
        SELECT uri, observed_at, text, matched_terms_json
        FROM posts
        WHERE is_relevant = 1 AND deleted_at IS NULL AND observed_at >= ?
        ORDER BY observed_at
        """,
        (cutoff_iso,),
    ).fetchall()


def aggregate_team_trends(
    rows: Iterable[sqlite3.Row],
    resolver: BlueskyEntityResolver,
) -> tuple[
    dict[str, Counter[str]],
    dict[str, Counter[str]],
    Counter[tuple[str, str]],
]:
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    hourly: dict[str, Counter[str]] = defaultdict(Counter)
    player_counts: Counter[tuple[str, str]] = Counter()

    for row in rows:
        try:
            matched_terms = json.loads(row["matched_terms_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            matched_terms = []
        resolved = resolver.resolve(matched_terms, text=row["text"] or "")
        hour = str(row["observed_at"])[:13] + ":00Z"
        direct_teams = set(resolved.direct_teams)
        player_teams = set(resolved.player_teams)

        for team in resolved.teams:
            totals[team]["posts"] += 1
            hourly[hour][team] += 1
            if team in direct_teams:
                totals[team]["direct_posts"] += 1
            if team in player_teams:
                totals[team]["player_posts"] += 1
        for player in resolved.players:
            player_counts[(player, resolver.player_teams[player])] += 1

    return totals, hourly, player_counts


def _display_team(team: str) -> str:
    abbreviation = TEAM_ABBR.get(team, "")
    return f"{team.title()} ({abbreviation})" if abbreviation else team.title()


def print_report(
    *,
    totals: dict[str, Counter[str]],
    hourly: dict[str, Counter[str]],
    player_counts: Counter[tuple[str, str]],
    hours: int,
    top: int,
) -> None:
    ranked_teams = sorted(
        totals,
        key=lambda team: (-totals[team]["posts"], team),
    )[: max(0, top)]

    print(f"Team conversation, last {hours} hours")
    print("posts  direct  via_player  team")
    if not ranked_teams:
        print("No team-attributed posts found.")
    for team in ranked_teams:
        counts = totals[team]
        print(
            f"{counts['posts']:>5}  {counts['direct_posts']:>6}  "
            f"{counts['player_posts']:>10}  {_display_team(team)}"
        )

    print(f"\nTop player mentions, last {hours} hours")
    if not player_counts:
        print("No roster-player mentions found.")
    for (player, team), count in player_counts.most_common(max(0, top)):
        print(f"{count:>5}  {player.title()} -> {_display_team(team)}")

    print("\nHourly team-attributed posts (UTC)")
    if not ranked_teams or not hourly:
        print("No hourly rows.")
        return
    print("hour\t" + "\t".join(TEAM_ABBR.get(team, team) for team in ranked_teams))
    for hour in sorted(hourly):
        print(hour + "\t" + "\t".join(str(hourly[hour][team]) for team in ranked_teams))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map retained Bluesky posts and ESPN roster players to NBA teams."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--hours", type=int, default=72)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--roster-ttl-hours", type=int, default=24)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    roster = load_espn_player_team_map(
        roster_ttl_seconds=max(0, args.roster_ttl_hours) * 60 * 60
    )
    print(
        f"ESPN roster map: {len(roster.player_teams)} players from "
        f"{len(roster.teams_loaded)} teams"
    )
    if roster.teams_failed:
        print("Roster fetch failed for: " + ", ".join(roster.teams_failed))

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise SystemExit(f"Capture database not found: {db_path}")
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = recent_posts(connection, args.hours)
        totals, hourly, player_counts = aggregate_team_trends(
            rows, BlueskyEntityResolver(roster.player_teams)
        )
    finally:
        connection.close()

    print_report(
        totals=totals,
        hourly=hourly,
        player_counts=player_counts,
        hours=args.hours,
        top=args.top,
    )


if __name__ == "__main__":
    main()
