from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.health_espn import compute_team_health, current_nba_season_year


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Debug ESPN-based team health computation (tiers + injury status)."
    )
    parser.add_argument("team", help="Team name, e.g. 'Los Angeles Lakers'")
    parser.add_argument("--year", type=int, default=None, help="Season year (default: inferred)")
    parser.add_argument("--type", type=int, default=2, help="Season type (default: 2 regular season)")
    parser.add_argument("--top", type=int, default=15, help="How many players to print (default: 15)")
    args = parser.parse_args()

    year = args.year or current_nba_season_year()
    health, players = compute_team_health(args.team, season_year=year, season_type=args.type)

    print(f"Team: {args.team}")
    print(f"Season: {year} (type {args.type})")
    print(f"Health score: {health:.3f}")
    print("")

    if not players:
        print("No player impact data returned (API missing? rookies? rate limits?).")
        return 0

    print("Top players by raw impact (PTS+AST+REB):")
    for p in players[: max(0, int(args.top))]:
        contribution = float(p.injury_weight) * float(p.impact_share)
        print(
            f"- {p.name:28s} raw={p.raw_impact:5.1f} rel={p.relative_raw_impact:4.2f} "
            f"share={p.impact_share:4.2f} status={p.injury_status:12s} injury_w={p.injury_weight:0.1f} "
            f"penalty={contribution:0.3f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
