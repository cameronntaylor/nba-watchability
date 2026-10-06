from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

from core.standings import _normalize_team_name
from core.watchability import WIN_MAX, WIN_MIN


PRESEASON_TEAM_QUALITY = 0.40
REGULAR_SEASON_START_MONTH_DAY = (10, 20)
EARLY_SEASON_SMOOTHING_GAMES = 10

# Season keys use the NBA season-ending year (for example, 2026 means 2025-26).
# Values are individual team-quality scores on the same 0..1 scale used by the app.
PRIOR_SEASON_QUALITY_OVERRIDES = {
    2026: {
        _normalize_team_name("New York Knicks"): 1.00,
        _normalize_team_name("San Antonio Spurs"): 0.98,
    }
}


def nba_season_year(game_date: dt.date) -> int:
    """Return the NBA season-ending year for a game date."""
    return game_date.year + 1 if game_date.month >= 7 else game_date.year


def is_preseason_date(game_date: Optional[dt.date]) -> bool:
    """The requested calendar strategy treats games through Oct. 19 as preseason."""
    if not isinstance(game_date, dt.date):
        return False
    return game_date.month >= 7 and (game_date.month, game_date.day) < REGULAR_SEASON_START_MONTH_DAY


def games_played(record: Tuple[Optional[int], Optional[int]]) -> int:
    wins, losses = record
    if wins is None or losses is None:
        return 0
    return max(0, int(wins) + int(losses))


def current_season_weight(
    record: Tuple[Optional[int], Optional[int]],
    smoothing_games: int = EARLY_SEASON_SMOOTHING_GAMES,
) -> float:
    """
    Weight on current-season quality: 0 at 0 games and 1 after 10 games.

    Equivalently, the prior-season weight is max(0, (10 - games_played) / 10).
    """
    if smoothing_games <= 0:
        return 1.0
    return min(1.0, max(0.0, games_played(record) / float(smoothing_games)))


def _quality_to_win_pct(quality: float) -> float:
    """Convert an individual quality score back to the win% input used by current rules."""
    q = min(1.0, max(0.0, float(quality)))
    return float(WIN_MIN) + q * (float(WIN_MAX) - float(WIN_MIN))


def prior_season_baseline_win_pct(
    team_name: str,
    prior_win_pct: float,
    prior_season_year: int,
    fully_healthy_star_factor: float = 0.0,
) -> float:
    """Healthy prior-season baseline, including champion/runner-up overrides."""
    overrides = PRIOR_SEASON_QUALITY_OVERRIDES.get(int(prior_season_year), {})
    override = overrides.get(_normalize_team_name(team_name))
    if override is not None:
        return _quality_to_win_pct(override)
    return min(1.0, max(0.0, float(prior_win_pct) + max(0.0, float(fully_healthy_star_factor))))


def smoothed_win_pct_input(
    *,
    team_name: str,
    current_adjusted_win_pct: float,
    current_record: Tuple[Optional[int], Optional[int]],
    prior_win_pct: float,
    prior_season_year: int,
    prior_fully_healthy_star_factor: float = 0.0,
) -> tuple[float, float]:
    """
    Blend the current adjusted win% with a fully healthy prior-season baseline.

    Blending in win%-input space lets the existing team-quality formula remain the
    source of truth. The returned second value is the current-season weight.
    """
    alpha = current_season_weight(current_record)
    prior = prior_season_baseline_win_pct(
        team_name,
        prior_win_pct,
        prior_season_year,
        fully_healthy_star_factor=prior_fully_healthy_star_factor,
    )
    current = min(1.0, max(0.0, float(current_adjusted_win_pct)))
    return alpha * current + (1.0 - alpha) * prior, alpha
