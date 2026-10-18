from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from app import analytics


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def capture(self, event: str, *, distinct_id: str, properties: dict) -> None:
        self.calls.append((event, distinct_id, properties))


class AnalyticsTests(unittest.TestCase):
    visitor_id = "d07878e5-82f4-4a53-8f55-243ef9c51a99"

    def _identity(self, *, visit_number: int = 1) -> dict:
        return {
            "visitor_id": self.visitor_id,
            "visitor_first_seen_at": "2026-10-17T20:15:30.000Z",
            "visit_number": visit_number,
            "is_returning_visitor": visit_number > 1,
            "persistence": "localStorage",
        }

    def test_capture_event_is_anonymous_and_personless(self) -> None:
        client = FakeClient()
        state: dict = {analytics.VISITOR_IDENTITY_STATE_KEY: self._identity()}
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=client),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            self.assertTrue(
                analytics.capture_event("sort_changed", {"new_value": "Tip time"})
            )

        event, distinct_id, properties = client.calls[0]
        self.assertEqual(event, "sort_changed")
        self.assertEqual(distinct_id, f"anonymous-visitor:{self.visitor_id}")
        self.assertIs(properties["$process_person_profile"], False)
        self.assertTrue(properties["$session_id"])
        self.assertEqual(properties["new_value"], "Tip time")

    def test_capture_event_normalizes_numpy_and_non_finite_values(self) -> None:
        client = FakeClient()
        state: dict = {analytics.VISITOR_IDENTITY_STATE_KEY: self._identity()}
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=client),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            analytics.capture_event(
                "slate_viewed",
                {"watchability": np.float64(88.4), "missing_score": float("nan")},
            )

        properties = client.calls[0][2]
        self.assertEqual(properties["watchability"], 88.4)
        self.assertIsNone(properties["missing_score"])

    def test_capture_once_deduplicates_successful_events(self) -> None:
        client = FakeClient()
        state: dict = {analytics.VISITOR_IDENTITY_STATE_KEY: self._identity()}
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=client),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            self.assertTrue(analytics.capture_once("slate_viewed", "slate:2026-10-20"))
            self.assertFalse(analytics.capture_once("slate_viewed", "slate:2026-10-20"))
        self.assertEqual(len(client.calls), 1)

    def test_capture_once_retries_when_analytics_is_unavailable(self) -> None:
        state: dict = {analytics.VISITOR_IDENTITY_STATE_KEY: self._identity()}
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=None),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            self.assertFalse(analytics.capture_once("session_started", "session_started"))
        self.assertEqual(state[analytics.CAPTURED_ONCE_KEY], set())

    def test_capture_waits_for_persistent_browser_identity(self) -> None:
        client = FakeClient()
        state: dict = {}
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=client),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            self.assertFalse(analytics.capture_event("session_started"))
        self.assertEqual(client.calls, [])

    def test_visitor_identity_validation_rejects_malformed_values(self) -> None:
        self.assertEqual(
            analytics._validated_visitor_identity(self._identity(visit_number=2)),
            self._identity(visit_number=2),
        )
        self.assertIsNone(
            analytics._validated_visitor_identity(
                {**self._identity(), "visitor_id": "not-a-uuid"}
            )
        )
        self.assertIsNone(
            analytics._validated_visitor_identity(
                {**self._identity(), "persistence": "sessionStorage"}
            )
        )

    def test_initialize_visitor_identity_bridges_component_state(self) -> None:
        state: dict = {}
        component_result = SimpleNamespace(identity=self._identity(visit_number=2))
        with (
            mock.patch.object(
                analytics,
                "_visitor_identity_component",
                return_value=component_result,
            ) as component,
            mock.patch.object(analytics.st, "session_state", state),
        ):
            identity = analytics.initialize_visitor_identity()

        self.assertEqual(identity, self._identity(visit_number=2))
        self.assertEqual(
            state[analytics.VISITOR_IDENTITY_STATE_KEY],
            self._identity(visit_number=2),
        )
        self.assertEqual(
            component.call_args.kwargs["data"]["session_id"],
            state[analytics.SESSION_ID_KEY],
        )

    def test_session_started_marks_return_visits(self) -> None:
        client = FakeClient()
        state: dict = {
            analytics.VISITOR_IDENTITY_STATE_KEY: self._identity(visit_number=3)
        }
        with (
            mock.patch.object(analytics, "_posthog_client", return_value=client),
            mock.patch.object(analytics.st, "session_state", state),
        ):
            self.assertTrue(analytics.track_session_started())

        properties = client.calls[0][2]
        self.assertEqual(properties["identity_scope"], "anonymous_browser")
        self.assertIs(properties["is_returning_visitor"], True)
        self.assertEqual(properties["visit_number"], 3)

    def test_link_click_trigger_captures_whitelisted_event_once(self) -> None:
        state: dict = {analytics.VISITOR_IDENTITY_STATE_KEY: self._identity()}
        component_result = SimpleNamespace(
            link_click={
                "click_id": "click-123",
                "event_name": "where_to_watch_clicked",
                "properties": {
                    "provider": "League Pass",
                    "matchup": "Boston Celtics @ Detroit Pistons",
                    "surface": "recommendation",
                },
            }
        )
        with (
            mock.patch.object(
                analytics,
                "_link_click_component",
                return_value=component_result,
            ),
            mock.patch.object(analytics.st, "session_state", state),
            mock.patch.object(analytics, "capture_event", return_value=True) as capture,
        ):
            self.assertTrue(analytics.track_link_clicks())
            self.assertFalse(analytics.track_link_clicks())

        capture.assert_called_once_with(
            "where_to_watch_clicked",
            {
                "provider": "League Pass",
                "matchup": "Boston Celtics @ Detroit Pistons",
                "surface": "recommendation",
            },
        )

    def test_link_click_trigger_rejects_unexpected_event_name(self) -> None:
        state: dict = {analytics.VISITOR_IDENTITY_STATE_KEY: self._identity()}
        component_result = SimpleNamespace(
            link_click={
                "click_id": "click-456",
                "event_name": "unapproved_event",
                "properties": {},
            }
        )
        with (
            mock.patch.object(
                analytics,
                "_link_click_component",
                return_value=component_result,
            ),
            mock.patch.object(analytics.st, "session_state", state),
            mock.patch.object(analytics, "capture_event") as capture,
        ):
            self.assertFalse(analytics.track_link_clicks())
        capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
