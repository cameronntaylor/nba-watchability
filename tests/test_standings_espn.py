import unittest
from unittest.mock import patch

import core.standings_espn as standings


def _standings_payload(wins, losses):
    games = wins + losses
    return {
        "children": [
            {
                "name": "Eastern Conference",
                "standings": {
                    "entries": [
                        {
                            "team": {"displayName": "New York Knicks"},
                            "stats": [
                                {"name": "wins", "value": wins},
                                {"name": "losses", "value": losses},
                                {"name": "winPercent", "value": wins / games if games else 0.0},
                            ],
                        }
                    ]
                },
            }
        ]
    }


class StandingsSeasonTests(unittest.TestCase):
    def test_current_zero_zero_records_can_be_kept_for_smoothing(self):
        with patch.object(standings, "current_nba_season_year", return_value=2027), patch.object(
            standings, "_fetch_standings_json", return_value=_standings_payload(0, 0)
        ):
            win_pct, records, _detail = standings.fetch_team_standings_detail_maps(
                allow_prior_fallback=False
            )

        self.assertEqual(records["new york knicks"], (0, 0))
        self.assertEqual(win_pct["new york knicks"], 0.0)
        self.assertEqual(standings.last_standings_fetch_meta()["season_year"], 2027)
        self.assertFalse(standings.last_standings_fetch_meta()["used_prior_season"])

    def test_prior_season_can_be_requested_explicitly(self):
        with patch.object(standings, "current_nba_season_year", return_value=2027), patch.object(
            standings, "_fetch_standings_json", return_value=_standings_payload(51, 31)
        ) as fetch:
            win_pct, records, _detail = standings.fetch_team_standings_detail_maps(
                season=2026,
                allow_prior_fallback=False,
            )

        fetch.assert_called_once_with(season=2026)
        self.assertEqual(records["new york knicks"], (51, 31))
        self.assertAlmostEqual(win_pct["new york knicks"], 51 / 82)


if __name__ == "__main__":
    unittest.main()
