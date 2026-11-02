from __future__ import annotations

import datetime as dt
import io
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
    def _game(self, tip: dt.datetime, *, home: str = "Oklahoma City Thunder", **overrides) -> dict:
        row = {
            "Local date": tip.date(),
            "Tip dt (PT)": tip,
            "Tip dt (ET)": tip.astimezone(tz.gettz("America/New_York")),
            "Tip dt (UTC)": tip.astimezone(dt.timezone.utc),
            "Status": "pre",
            "Is live": False,
            "Away team": "Denver Nuggets",
            "Home team": home,
            "Home spread": -3.5,
            "Forecast": False,
            "aWI": 73.5,
            "Closeness": 0.8,
            "Team quality": 0.7,
            "Region": "Watchable",
        }
        row.update(overrides)
        return row

    def _render_at(self, games: pd.DataFrame, now: dt.datetime, slate_day: str) -> str:
        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)

        with (
            patch.object(dashboard.dt, "datetime", Clock),
            patch.object(dashboard.st, "markdown") as markdown,
        ):
            dashboard.render_recommendations_module(games, slate_day=slate_day)
        return "\n".join(str(call.args[0]) for call in markdown.call_args_list)

    def test_previous_forecast_does_not_erase_live_tips_before_daily_refresh(self):
        pt = tz.gettz("America/Los_Angeles")
        today = dt.datetime(2026, 11, 2, 16, 10, tzinfo=pt)
        now = today.replace(hour=0, minute=0)
        live = pd.DataFrame([self._game(today)])
        forecast = pd.DataFrame([
            self._game(today - dt.timedelta(days=1), home="Boston Celtics", Forecast=True),
            self._game(today, Forecast=True),
            self._game(today + dt.timedelta(days=1), home="Houston Rockets", Forecast=True),
        ])
        # Reproduce the actual storage boundary: Parquet restores a different
        # timezone implementation from the live builder's dateutil objects.
        buffer = io.BytesIO()
        forecast.to_parquet(buffer, index=False)
        buffer.seek(0)
        forecast = pd.read_parquet(buffer)

        for refreshed in (False, True):
            with self.subTest(refreshed=refreshed):
                saved = forecast[forecast["Local date"] >= today.date()] if refreshed else forecast
                combined = dashboard._merge_live_and_forecast_df(live, saved)
                normalized = dashboard._normalize_dashboard_df_types(combined)
                for column in ("Tip dt (PT)", "Tip dt (ET)", "Tip dt (UTC)"):
                    self.assertTrue(normalized[column].notna().all())
                    self.assertEqual(
                        normalized.loc[normalized["Local date"] == today.date(), column].iloc[0],
                        today,
                    )

                class Clock(dt.datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return now.astimezone(tz)

                with patch.object(dashboard.dt, "datetime", Clock):
                    displayable = dashboard._filter_displayable_dashboard_rows(normalized)
                self.assertEqual(len(displayable), 2)
                rendered = self._render_at(displayable, now, today.date().isoformat())
                tonight = next(card for card in rendered.split('<div class="rec-card">') if "Best upcoming tonight" in card)
                self.assertIn("Oklahoma City Thunder", tonight)
                self.assertNotIn("Houston Rockets", tonight)

    def test_timezone_normalization_preserves_dst_offsets_and_invalid_times(self):
        pt = tz.gettz("America/Los_Angeles")
        tips = [dt.datetime(2026, 10, 31, 23, 30, tzinfo=pt), dt.datetime(2026, 11, 1, 3, 30, tzinfo=pt)]
        games = pd.DataFrame([self._game(tip) for tip in tips])
        # Cover the CSV fallback's mixed offset strings as well as bad input.
        for column in ("Tip dt (PT)", "Tip dt (ET)", "Tip dt (UTC)"):
            games[column] = games[column].map(str)
            games.loc[2, column] = "invalid"
        normalized = dashboard._normalize_dashboard_df_types(games)
        self.assertEqual(normalized.loc[0, "Tip dt (PT)"].utcoffset(), dt.timedelta(hours=-7))
        self.assertEqual(normalized.loc[1, "Tip dt (PT)"].utcoffset(), dt.timedelta(hours=-8))
        for column, zone in [("Tip dt (PT)", "America/Los_Angeles"), ("Tip dt (ET)", "America/New_York"), ("Tip dt (UTC)", "UTC")]:
            self.assertEqual(str(normalized[column].dt.tz), zone)
            self.assertEqual(normalized[column].iloc[:2].tolist(), tips)
            self.assertTrue(pd.isna(normalized.loc[2, column]))

    def test_tonight_is_available_from_midnight_until_tip(self):
        pt = tz.gettz("America/Los_Angeles")
        tip = dt.datetime(2026, 11, 2, 23, 30, tzinfo=pt)
        games = dashboard._normalize_dashboard_df_types(pd.DataFrame([self._game(tip)]))
        for now, expected in [
            (tip.replace(hour=0, minute=0), True),
            (tip - dt.timedelta(seconds=1), True),
            (tip, False),
            (tip + dt.timedelta(seconds=1), False),
            (tip + dt.timedelta(days=1), False),
        ]:
            with self.subTest(now=now):
                rendered = self._render_at(games, now, tip.date().isoformat())
                self.assertEqual("Best upcoming tonight" in rendered, expected)

    def test_future_slate_is_not_tonight(self):
        pt = tz.gettz("America/Los_Angeles")
        tip = dt.datetime(2026, 11, 3, 0, 5, tzinfo=pt)
        games = pd.DataFrame([self._game(tip)])
        rendered = self._render_at(games, tip - dt.timedelta(minutes=10), "2026-11-03")
        self.assertNotIn("Best upcoming tonight", rendered)
        self.assertIn("Best games upcoming next 7 days", rendered)

    def test_tonight_excludes_live_finished_and_unknown_tips(self):
        pt = tz.gettz("America/Los_Angeles")
        tip = dt.datetime(2026, 11, 2, 16, 10, tzinfo=pt)
        for overrides in [
            {"Is live": True},
            {"Status": "in", "Is live": False},
            {"Status": "post"},
            {"Status": "final"},
            {"Tip dt (PT)": pd.NaT},
        ]:
            with self.subTest(overrides=overrides):
                games = pd.DataFrame([self._game(tip, **overrides)])
                rendered = self._render_at(games, tip.replace(hour=0), "2026-11-02")
                self.assertNotIn("Best upcoming tonight", rendered)

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
