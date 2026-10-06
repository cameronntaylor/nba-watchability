import datetime as dt
import unittest

from core.season_strategy import (
    current_season_weight,
    is_preseason_date,
    prior_season_baseline_win_pct,
    smoothed_win_pct_input,
)
from core.watchability import team_quality


class SeasonStrategyTests(unittest.TestCase):
    def test_preseason_ends_after_october_19(self):
        self.assertTrue(is_preseason_date(dt.date(2026, 9, 30)))
        self.assertTrue(is_preseason_date(dt.date(2026, 10, 19)))
        self.assertFalse(is_preseason_date(dt.date(2026, 10, 20)))
        self.assertFalse(is_preseason_date(dt.date(2027, 1, 10)))

    def test_current_season_weight_reaches_one_at_ten_games(self):
        self.assertEqual(current_season_weight((0, 0)), 0.0)
        self.assertEqual(current_season_weight((1, 0)), 0.1)
        self.assertEqual(current_season_weight((3, 2)), 0.5)
        self.assertEqual(current_season_weight((8, 2)), 1.0)
        self.assertEqual(current_season_weight((20, 10)), 1.0)

    def test_2026_finalists_receive_quality_overrides(self):
        knicks = prior_season_baseline_win_pct("New York Knicks", 0.50, 2026, 0.04)
        spurs = prior_season_baseline_win_pct("San Antonio Spurs", 0.50, 2026, 0.04)
        self.assertAlmostEqual(team_quality(knicks, knicks), 1.00)
        self.assertAlmostEqual(team_quality(spurs, spurs), 0.98)

    def test_prior_baseline_assumes_healthy_star_for_other_teams(self):
        baseline = prior_season_baseline_win_pct("Boston Celtics", 0.60, 2026, 0.02)
        self.assertAlmostEqual(baseline, 0.62)

    def test_smoothing_uses_prior_at_zero_and_current_at_ten(self):
        at_zero, alpha_zero = smoothed_win_pct_input(
            team_name="Boston Celtics",
            current_adjusted_win_pct=1.0,
            current_record=(0, 0),
            prior_win_pct=0.6,
            prior_season_year=2026,
        )
        at_five, alpha_five = smoothed_win_pct_input(
            team_name="Boston Celtics",
            current_adjusted_win_pct=0.8,
            current_record=(3, 2),
            prior_win_pct=0.6,
            prior_season_year=2026,
        )
        at_ten, alpha_ten = smoothed_win_pct_input(
            team_name="Boston Celtics",
            current_adjusted_win_pct=0.8,
            current_record=(7, 3),
            prior_win_pct=0.6,
            prior_season_year=2026,
        )

        self.assertEqual((at_zero, alpha_zero), (0.6, 0.0))
        self.assertAlmostEqual(at_five, 0.7)
        self.assertEqual(alpha_five, 0.5)
        self.assertEqual((at_ten, alpha_ten), (0.8, 1.0))


if __name__ == "__main__":
    unittest.main()
