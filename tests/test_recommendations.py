from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import patch

import pandas as pd
from dateutil import tz

import app.dashboard_views as dashboard


class _FixedDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 22, 9, 0, 0)
        return value.replace(tzinfo=tz) if tz else value


class RecommendationTests(unittest.TestCase):
    def test_tonight_recommendation_accepts_scheduled_status_without_row_apply(self):
        pt = tz.gettz("America/Los_Angeles")
        et = tz.gettz("America/New_York")
        tip_pt = dt.datetime(2026, 10, 22, 18, 40, tzinfo=pt)
        tip_et = tip_pt.astimezone(et)
        tip_utc = tip_pt.astimezone(dt.timezone.utc)
        games = pd.DataFrame(
            [
                {
                    "Tip dt (PT)": tip_pt,
                    "Tip dt (ET)": tip_et,
                    "Tip dt (UTC)": tip_utc,
                    "Status": "scheduled",
                    "Is live": False,
                    "Away team": "Denver Nuggets",
                    "Home team": "Oklahoma City Thunder",
                    "Away logo": "",
                    "Home logo": "",
                    "Record (away)": "0-0",
                    "Record (home)": "1-0",
                    "Star factor (away)": 0.0,
                    "Star factor (home)": 0.0,
                    "Home spread": -8.5,
                    "Spread mode": "odds",
                    "Spread source": "odds",
                    "Forecast": False,
                    "aWI": 73.5,
                    "Closeness": 0.49,
                    "Team quality": 1.0,
                    "Region": "Watchable",
                    "ESPN game id": "401909094",
                }
            ]
        )

        with (
            patch.object(dashboard.dt, "datetime", _FixedDateTime),
            patch.object(
                dashboard.pd.DataFrame,
                "apply",
                side_effect=AssertionError("recommendations must not materialize full rows"),
            ),
            patch.object(dashboard.st, "markdown") as markdown,
        ):
            dashboard.render_recommendations_module(
                games,
                slate_day="2026-10-22",
            )

        rendered = "\n".join(str(call.args[0]) for call in markdown.call_args_list)
        self.assertIn("Best upcoming tonight", rendered)
        self.assertIn("Denver Nuggets", rendered)


if __name__ == "__main__":
    unittest.main()
