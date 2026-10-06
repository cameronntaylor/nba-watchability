import datetime as dt
import unittest

from core.config import SPORT_KEY_NBA, SPORT_KEY_NBA_PRESEASON
from core.odds_api import _parse_games, _sport_key_for_date, _sport_keys_for_window


class OddsApiStrategyTests(unittest.TestCase):
    def test_sport_key_handoff(self):
        self.assertEqual(_sport_key_for_date(dt.date(2026, 10, 19)), SPORT_KEY_NBA_PRESEASON)
        self.assertEqual(_sport_key_for_date(dt.date(2026, 10, 20)), SPORT_KEY_NBA)

    def test_window_crossing_opening_day_fetches_both_keys(self):
        start = dt.datetime(2026, 10, 19, tzinfo=dt.timezone.utc)
        end = dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc)
        self.assertEqual(_sport_keys_for_window(start, end), [SPORT_KEY_NBA_PRESEASON, SPORT_KEY_NBA])

    def test_preseason_spreads_are_parsed_and_traced(self):
        data = [
            {
                "id": "game-1",
                "commence_time": "2026-10-10T23:00:00Z",
                "home_team": "New York Knicks",
                "away_team": "San Antonio Spurs",
                "bookmakers": [
                    {
                        "markets": [
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "New York Knicks", "point": -2.5},
                                    {"name": "San Antonio Spurs", "point": 2.5},
                                ],
                            }
                        ]
                    },
                    {
                        "markets": [
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "New York Knicks", "point": -3.5},
                                    {"name": "San Antonio Spurs", "point": 3.5},
                                ],
                            }
                        ]
                    },
                ],
            }
        ]

        games = _parse_games(data, SPORT_KEY_NBA_PRESEASON)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].home_spread, -3.0)
        self.assertIn(SPORT_KEY_NBA_PRESEASON, games[0].spread_source)


if __name__ == "__main__":
    unittest.main()
