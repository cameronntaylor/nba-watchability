from __future__ import annotations

import datetime as dt
import unittest

import pandas as pd
from dateutil import tz

from app.dashboard_views import filter_dashboard_games, _selected_chart_game_id


def _games(now: dt.datetime) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Away team": "Boston Celtics",
                "Home team": "New York Knicks",
                "aWI": 82,
                "Status": "pre",
                "Is live": False,
                "Tip dt (PT)": now + dt.timedelta(minutes=45),
            },
            {
                "Away team": "Los Angeles Lakers",
                "Home team": "Golden State Warriors",
                "aWI": 71,
                "Status": "in",
                "Is live": True,
                "Tip dt (PT)": now - dt.timedelta(minutes=30),
            },
            {
                "Away team": "Chicago Bulls",
                "Home team": "Miami Heat",
                "aWI": 44,
                "Status": "pre",
                "Is live": False,
                "Tip dt (PT)": now + dt.timedelta(hours=4),
            },
        ]
    )


class DashboardAnalyticsTests(unittest.TestCase):
    def test_team_and_watchability_filters_can_be_combined(self) -> None:
        now = dt.datetime(2026, 10, 20, 16, 0, tzinfo=tz.gettz("America/Los_Angeles"))
        result = filter_dashboard_games(
            _games(now),
            teams=["Boston Celtics", "Chicago Bulls"],
            minimum_watchability=50,
            now_pt=now,
        )

        self.assertEqual(result["Away team"].tolist(), ["Boston Celtics"])

    def test_timing_filters_distinguish_live_soon_and_later(self) -> None:
        now = dt.datetime(2026, 10, 20, 16, 0, tzinfo=tz.gettz("America/Los_Angeles"))
        games = _games(now)

        live = filter_dashboard_games(games, timing="Live now", now_pt=now)
        soon = filter_dashboard_games(games, timing="Starting in 2 hours", now_pt=now)
        later = filter_dashboard_games(games, timing="Later", now_pt=now)

        self.assertEqual(live["Away team"].tolist(), ["Los Angeles Lakers"])
        self.assertEqual(soon["Away team"].tolist(), ["Boston Celtics"])
        self.assertEqual(later["Away team"].tolist(), ["Chicago Bulls"])

    def test_selected_chart_game_id_handles_streamlit_selection_shape(self) -> None:
        event = {
            "selection": {
                "game_selection": {
                    "_analytics_game_id": ["2026-10-20|Boston Celtics|New York Knicks"]
                }
            }
        }

        self.assertEqual(
            _selected_chart_game_id(event),
            "2026-10-20|Boston Celtics|New York Knicks",
        )
        self.assertIsNone(_selected_chart_game_id({"selection": {"game_selection": {}}}))


if __name__ == "__main__":
    unittest.main()
