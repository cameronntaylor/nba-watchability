import datetime as dt
import unittest
from unittest.mock import patch

from dateutil import tz

import core.build_watchability_forecast_df as forecast
from core.health_espn import PlayerImpact


def _player(athlete_id: str, name: str, points: float) -> PlayerImpact:
    return PlayerImpact(
        athlete_id=athlete_id,
        name=name,
        points_per_game=points,
        assists_per_game=0.0,
        rebounds_per_game=0.0,
        steals_per_game=0.0,
        blocks_per_game=0.0,
        raw_impact=points,
        impact_share=1.0,
        relative_raw_impact=1.0,
        injury_status="Available",
        injury_weight=0.0,
    )


class _FixedDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 20, 9, 0, 0)
        return value.replace(tzinfo=tz) if tz else value


class ForecastContextTests(unittest.TestCase):
    def test_forecast_uses_smoothed_quality_stars_and_watch_fallback(self):
        current = {
            "Boston Celtics": [_player("current-bos", "Current Boston Star", 20.0)],
            "Washington Wizards": [_player("current-was", "Current Washington Star", 20.0)],
        }
        prior = {
            "Boston Celtics": [_player("prior-bos", "Prior Boston Star", 40.0)],
            "Washington Wizards": [_player("prior-was", "Prior Washington Star", 20.0)],
        }
        current_standings = (
            {"boston celtics": 0.5, "washington wizards": 0.5},
            {"boston celtics": (0, 0), "washington wizards": (0, 0)},
            {},
        )
        prior_standings = (
            {"boston celtics": 0.8, "washington wizards": 0.2},
            {},
            {},
        )
        game = {
            "game_id": "401000001",
            "start_time_utc": "2026-10-21T00:00:00Z",
            "home_team": "Washington Wizards",
            "away_team": "Boston Celtics",
            "state": "pre",
            "home_score": None,
            "away_score": None,
            "time_remaining": None,
        }

        with (
            patch.object(forecast.dt, "datetime", _FixedDateTime),
            patch.object(
                forecast,
                "fetch_team_standings_detail_maps",
                side_effect=[current_standings, prior_standings],
            ),
            patch.object(forecast, "last_standings_fetch_meta", return_value={"season_year": 2027}),
            patch.object(forecast, "build_team_recent_feature_map", return_value={}),
            patch.object(forecast, "_build_odds_map", return_value={}),
            patch.object(forecast, "fetch_games_for_date", return_value=[game]),
            patch.object(
                forecast,
                "_load_espn_game_summary_maps",
                return_value=({}, {"401000001": "ESPN"}, {}),
            ),
            patch.object(forecast, "_load_nba_schedule_game_id_map_by_pt_date", return_value={}),
            patch.object(forecast, "_load_nba_provider_map_by_game_id", return_value={}),
        ):
            df = forecast.build_watchability_forecast_df(
                days_ahead=1,
                precomputed_team_impacts=current,
                precomputed_prior_team_impacts=prior,
            )

        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        expected_spread = -2.0 - 30.0 * (
            row["Team quality input win% (home)"]
            - row["Team quality input win% (away)"]
        )
        self.assertAlmostEqual(row["Home spread"], expected_spread)
        self.assertNotEqual(row["Home spread"], -2.0)
        self.assertEqual(row["Away Star Player"], "Prior Boston Star")
        self.assertEqual(row["Home Star Player"], "Prior Washington Star")
        self.assertGreater(row["Team Quality bump (away)"], 0.0)
        self.assertEqual(row["Where to watch provider"], "ESPN")
        self.assertEqual(
            row["Where to watch URL"],
            "https://www.espn.com/watch/player/_/eventCalendarId/401000001",
        )


if __name__ == "__main__":
    unittest.main()
