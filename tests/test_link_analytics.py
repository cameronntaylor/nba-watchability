from __future__ import annotations

import json
import unittest
from html.parser import HTMLParser

from app.dashboard_views import _follow_chip_html, _watch_chip_html


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.attributes: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            self.attributes = dict(attrs)


class LinkAnalyticsTests(unittest.TestCase):
    row = {
        "ESPN game id": "401909088",
        "Local date": "2026-10-20",
        "Matchup": "Boston Celtics @ Detroit Pistons",
        "Away team": "Boston Celtics",
        "Home team": "Detroit Pistons",
        "aWI": 98.6,
        "Region": "Must Watch",
    }

    def _attributes(self, markup: str) -> dict[str, str | None]:
        parser = _AnchorParser()
        parser.feed(markup)
        return parser.attributes

    def test_watch_link_contains_analytics_context(self) -> None:
        attributes = self._attributes(
            _watch_chip_html(
                "https://www.nba.com/watch/league-pass-stream",
                "League Pass",
                self.row,
            )
        )
        properties = json.loads(str(attributes["data-analytics-properties"]))

        self.assertEqual(attributes["data-analytics-event"], "where_to_watch_clicked")
        self.assertEqual(properties["provider"], "League Pass")
        self.assertEqual(properties["destination_domain"], "www.nba.com")
        self.assertEqual(properties["matchup"], self.row["Matchup"])
        self.assertEqual(properties["watchability"], 98.6)

    def test_follow_link_contains_analytics_context(self) -> None:
        attributes = self._attributes(_follow_chip_html("401909088", self.row))
        properties = json.loads(str(attributes["data-analytics-properties"]))

        self.assertEqual(attributes["data-analytics-event"], "where_to_follow_clicked")
        self.assertEqual(properties["provider"], "ESPN")
        self.assertEqual(properties["destination_domain"], "www.espn.com")
        self.assertEqual(properties["game_id"], "401909088")


if __name__ == "__main__":
    unittest.main()
