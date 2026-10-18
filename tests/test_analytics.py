from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from app import analytics


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def capture(self, event: str, *, distinct_id: str, properties: dict) -> None:
        self.calls.append((event, distinct_id, properties))


class AnalyticsTests(unittest.TestCase):
    def test_capture_event_is_anonymous_and_personless(self) -> None:
        client = FakeClient()
        state: dict = {}
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=client),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            self.assertTrue(
                analytics.capture_event("filter_changed", {"teams": ("Boston Celtics",)})
            )

        event, distinct_id, properties = client.calls[0]
        self.assertEqual(event, "filter_changed")
        self.assertTrue(distinct_id.startswith("anonymous-session:"))
        self.assertIs(properties["$process_person_profile"], False)
        self.assertIn(properties["$session_id"], distinct_id)
        self.assertEqual(properties["teams"], ["Boston Celtics"])

    def test_capture_event_normalizes_numpy_and_non_finite_values(self) -> None:
        client = FakeClient()
        state: dict = {}
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=client),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            analytics.capture_event(
                "game_selected",
                {"watchability": np.float64(88.4), "missing_score": float("nan")},
            )

        properties = client.calls[0][2]
        self.assertEqual(properties["watchability"], 88.4)
        self.assertIsNone(properties["missing_score"])

    def test_capture_once_deduplicates_successful_events(self) -> None:
        client = FakeClient()
        state: dict = {}
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=client),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            self.assertTrue(analytics.capture_once("slate_viewed", "slate:2026-10-20"))
            self.assertFalse(analytics.capture_once("slate_viewed", "slate:2026-10-20"))
        self.assertEqual(len(client.calls), 1)

    def test_capture_once_retries_when_analytics_is_unavailable(self) -> None:
        state: dict = {}
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=None),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            self.assertFalse(analytics.capture_once("session_started", "session_started"))
        self.assertEqual(state[analytics.CAPTURED_ONCE_KEY], set())


if __name__ == "__main__":
    unittest.main()
