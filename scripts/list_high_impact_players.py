#!/usr/bin/env python3
"""
List players whose impact_share meets a threshold for every NBA team.

Impact share is computed from ESPN season per-game stats:
  raw = avgPoints + avgAssists + avgRebounds
  impact_share = raw / sum(raw over team roster)

This ignores injury status; it answers "who would count as a key injury" if
they appeared on a game injury report.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.health_espn import compute_team_player_impacts
from core.team_meta import TEAM_ABBR
from core.watchability_v2_params import KEY_INJURY_IMPACT_SHARE_THRESHOLD


def _iter_teams() -> Iterable[str]:
    # TEAM_ABBR keys are normalized display names.
    return sorted(TEAM_ABBR.keys())


def main() -> int:
    p = argparse.ArgumentParser(
        description="List high-impact players (by impact_share) for all teams."
    )
    p.add_argument(
        "--teams",
        type=str,
        default="",
        help='Comma-separated team names to run (default: all teams in TEAM_ABBR). Example: "denver nuggets,boston celtics".',
    )
    p.add_argument(
        "--max-teams",
        type=int,
        default=0,
        help="If > 0, only process the first N teams after filtering (default: 0 = no limit).",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=float(KEY_INJURY_IMPACT_SHARE_THRESHOLD),
        help="Minimum impact_share to display (default: KEY_INJURY_IMPACT_SHARE_THRESHOLD).",
    )
    p.add_argument(
        "--season",
        type=int,
        default=None,
        help="NBA season year (e.g. 2026). Defaults to current season year logic.",
    )
    p.add_argument(
        "--type",
        type=int,
        default=2,
        help="ESPN season type (default: 2 = regular season).",
    )
    args = p.parse_args()

    threshold = float(args.threshold)
    if args.teams.strip():
        teams = [t.strip().lower() for t in args.teams.split(",") if t.strip()]
    else:
        teams = list(_iter_teams())
    if int(args.max_teams or 0) > 0:
        teams = teams[: int(args.max_teams)]

    for team in teams:
        print(f"\n== {team} ==")
        try:
            players = compute_team_player_impacts(
                team, season_year=args.season, season_type=int(args.type)
            )
        except Exception as e:
            print(f"ERROR ({e})")
            continue

        keep = [p for p in players if float(p.impact_share) >= threshold]
        if not keep:
            print(f"(none >= {threshold:.2f})")
            continue

        for pl in keep:
            print(
                f"  - {pl.name} | share={pl.impact_share:.3f} | raw={pl.raw_impact:.1f} | rel={pl.relative_raw_impact:.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
