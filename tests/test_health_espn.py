import unittest

from core.health_espn import PlayerImpact, blend_player_impact_shares
from core.season_strategy import current_season_weight


def _player(athlete_id: str, name: str, share: float, raw: float) -> PlayerImpact:
    return PlayerImpact(
        athlete_id=athlete_id,
        name=name,
        points_per_game=raw,
        assists_per_game=0.0,
        rebounds_per_game=0.0,
        steals_per_game=0.0,
        blocks_per_game=0.0,
        raw_impact=raw,
        impact_share=share,
        relative_raw_impact=share,
        injury_status="Available",
        injury_weight=0.0,
    )


def _shares(players: list[PlayerImpact]) -> dict[str, float]:
    return {player.athlete_id: player.impact_share for player in players}


class PlayerImpactBlendTests(unittest.TestCase):
    def setUp(self):
        self.prior = [
            _player("chet", "Chet Holmgren", 0.40, 28.0),
            _player("shai", "Shai Gilgeous-Alexander", 0.60, 42.0),
        ]
        self.current = [
            _player("chet", "Chet Holmgren", 0.50, 32.0),
            _player("shai", "Shai Gilgeous-Alexander", 0.50, 32.0),
        ]

    def test_zero_games_uses_prior_season_shares(self):
        players = blend_player_impact_shares(
            self.prior,
            self.current,
            current_weight=current_season_weight((0, 0)),
        )
        self.assertEqual(_shares(players), {"chet": 0.40, "shai": 0.60})

    def test_one_game_uses_ten_percent_current_season_shares(self):
        players = blend_player_impact_shares(
            self.prior,
            self.current,
            current_weight=current_season_weight((1, 0)),
        )
        shares = _shares(players)
        self.assertAlmostEqual(shares["chet"], 0.41)
        self.assertAlmostEqual(shares["shai"], 0.59)

    def test_ten_games_uses_current_season_shares(self):
        players = blend_player_impact_shares(
            self.prior,
            self.current,
            current_weight=current_season_weight((7, 3)),
        )
        self.assertEqual(_shares(players), {"chet": 0.50, "shai": 0.50})

    def test_players_in_only_one_season_receive_the_other_seasons_zero_share(self):
        prior = [
            _player("veteran", "Veteran", 0.60, 30.0),
            _player("departed", "Departed", 0.40, 20.0),
        ]
        current = [
            _player("veteran", "Veteran", 0.50, 25.0),
            _player("rookie", "Rookie", 0.50, 25.0),
        ]
        players = blend_player_impact_shares(
            prior,
            current,
            current_weight=current_season_weight((1, 1)),
        )
        shares = _shares(players)
        self.assertAlmostEqual(shares["veteran"], 0.58)
        self.assertAlmostEqual(shares["departed"], 0.32)
        self.assertAlmostEqual(shares["rookie"], 0.10)
        self.assertAlmostEqual(sum(shares.values()), 1.0)

    def test_missing_current_data_keeps_prior_shares_undiluted(self):
        players = blend_player_impact_shares(
            self.prior,
            [],
            current_weight=current_season_weight((3, 2)),
        )
        self.assertEqual(_shares(players), {"chet": 0.40, "shai": 0.60})


if __name__ == "__main__":
    unittest.main()
