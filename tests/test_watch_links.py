import unittest

from core.build_watchability_df import (
    _map_watch_provider_label,
    watch_destination_url,
)


class WatchLinkTests(unittest.TestCase):
    def test_direct_nba_game_url_wins(self):
        direct = "https://www.nba.com/game/bos-vs-nyk-0022600001"
        self.assertEqual(
            watch_destination_url(
                provider="Peacock",
                direct_game_url=direct,
                espn_game_id="401000001",
            ),
            direct,
        )

    def test_provider_fallbacks_keep_watch_button_visible(self):
        self.assertEqual(
            watch_destination_url(provider="League Pass"),
            "https://www.nba.com/watch/league-pass-stream",
        )
        self.assertEqual(
            watch_destination_url(provider="Peacock"),
            "https://www.peacocktv.com/sports/nba",
        )
        self.assertEqual(
            watch_destination_url(provider="Prime"),
            "https://www.amazon.com/gp/video/sports",
        )
        self.assertEqual(
            watch_destination_url(provider="ESPN", espn_game_id="401000001"),
            "https://www.espn.com/watch/player/_/eventCalendarId/401000001",
        )

    def test_nbc_broadcasts_map_to_peacock(self):
        self.assertEqual(_map_watch_provider_label(["NBC"]), "Peacock")


if __name__ == "__main__":
    unittest.main()
