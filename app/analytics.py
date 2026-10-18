from __future__ import annotations

import atexit
import datetime as dt
import math
import os
import uuid
from functools import lru_cache
from typing import Any, Mapping

import streamlit as st


DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"
ANALYTICS_SCHEMA_VERSION = 1
SESSION_ID_KEY = "_analytics_session_id"
CAPTURED_ONCE_KEY = "_analytics_captured_once"
VISITOR_IDENTITY_COMPONENT_KEY = "_analytics_visitor_identity_component"
VISITOR_IDENTITY_STATE_KEY = "_analytics_visitor_identity"

_VISITOR_IDENTITY_JS = r"""
export default function(component) {
    const { data, parentElement, setStateValue } = component;
    const sessionId = data?.session_id;
    if (!sessionId) return;

    const visitorIdKey = "nba_watchability_visitor_id_v1";
    const firstSeenKey = "nba_watchability_visitor_first_seen_v1";
    const visitNumberKey = "nba_watchability_visit_number_v1";
    const lastSessionKey = "nba_watchability_last_session_id_v1";
    const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

    try {
        let visitorId = window.localStorage.getItem(visitorIdKey);
        if (!visitorId || !uuidPattern.test(visitorId)) {
            visitorId = window.crypto.randomUUID();
            window.localStorage.setItem(visitorIdKey, visitorId);
        }

        let firstSeenAt = window.localStorage.getItem(firstSeenKey);
        if (!firstSeenAt) {
            firstSeenAt = new Date().toISOString();
            window.localStorage.setItem(firstSeenKey, firstSeenAt);
        }

        let visitNumber = Number.parseInt(
            window.localStorage.getItem(visitNumberKey) || "0",
            10,
        );
        if (!Number.isFinite(visitNumber) || visitNumber < 0) visitNumber = 0;

        const lastSessionId = window.localStorage.getItem(lastSessionKey);
        if (lastSessionId !== sessionId) {
            visitNumber += 1;
            window.localStorage.setItem(visitNumberKey, String(visitNumber));
            window.localStorage.setItem(lastSessionKey, sessionId);
        }

        const identity = {
            visitor_id: visitorId,
            visitor_first_seen_at: firstSeenAt,
            visit_number: Math.max(visitNumber, 1),
            is_returning_visitor: visitNumber > 1,
            persistence: "localStorage",
        };
        const serialized = JSON.stringify(identity);
        if (parentElement.__nbaWatchabilityAnalyticsIdentity !== serialized) {
            parentElement.__nbaWatchabilityAnalyticsIdentity = serialized;
            setStateValue("identity", identity);
        }
    } catch (_error) {
        // If browser storage is unavailable, analytics stays disabled. This
        // avoids silently turning a session ID into a misleading visitor ID.
    }
}
"""

_visitor_identity_component = st.components.v2.component(
    "nba_watchability_visitor_identity",
    html="<span aria-hidden='true'></span>",
    css=":host { display: none; }",
    js=_VISITOR_IDENTITY_JS,
)


def _secret_value(key: str) -> str | None:
    """Read analytics config without requiring a local secrets file."""

    try:
        section = st.secrets.get("analytics", {})
        value = section.get(key) if hasattr(section, "get") else None
    except Exception:
        value = None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _settings() -> tuple[str | None, str]:
    token = os.getenv("POSTHOG_PROJECT_TOKEN") or _secret_value("posthog_project_token")
    host = os.getenv("POSTHOG_HOST") or _secret_value("posthog_host") or DEFAULT_POSTHOG_HOST
    return token, host.rstrip("/")


@lru_cache(maxsize=1)
def _posthog_client():
    token, host = _settings()
    if not token:
        return None

    try:
        from posthog import Posthog

        client = Posthog(
            token,
            host=host,
            disable_geoip=True,
            enable_exception_autocapture=False,
        )
    except Exception:
        return None

    def _shutdown() -> None:
        try:
            client.shutdown()
        except Exception:
            pass

    atexit.register(_shutdown)
    return client


def analytics_configured() -> bool:
    token, _host = _settings()
    return bool(token)


def session_id() -> str:
    """Return an anonymous ID scoped to the current Streamlit session."""

    value = st.session_state.get(SESSION_ID_KEY)
    if not value:
        value = str(uuid.uuid4())
        st.session_state[SESSION_ID_KEY] = value
    return str(value)


def _validated_visitor_identity(value: Any) -> dict[str, Any] | None:
    """Return a safe browser identity payload or None for malformed state."""

    if not isinstance(value, Mapping):
        return None
    try:
        visitor_id = str(uuid.UUID(str(value.get("visitor_id", ""))))
        visitor_first_seen_at = str(value["visitor_first_seen_at"])
        dt.datetime.fromisoformat(visitor_first_seen_at.replace("Z", "+00:00"))
        visit_number = int(value["visit_number"])
    except (KeyError, TypeError, ValueError):
        return None
    if visit_number < 1 or value.get("persistence") != "localStorage":
        return None
    return {
        "visitor_id": visitor_id,
        "visitor_first_seen_at": visitor_first_seen_at,
        "visit_number": visit_number,
        "is_returning_visitor": visit_number > 1,
        "persistence": "localStorage",
    }


def initialize_visitor_identity() -> dict[str, Any] | None:
    """Load or create the persistent anonymous browser ID used by analytics."""

    result = _visitor_identity_component(
        key=VISITOR_IDENTITY_COMPONENT_KEY,
        data={"session_id": session_id()},
        default={"identity": None},
        height=0,
        on_identity_change=lambda: None,
    )
    identity = _validated_visitor_identity(getattr(result, "identity", None))
    if identity is None:
        st.session_state.pop(VISITOR_IDENTITY_STATE_KEY, None)
        return None
    st.session_state[VISITOR_IDENTITY_STATE_KEY] = identity
    return identity


def visitor_identity() -> dict[str, Any] | None:
    """Return the validated identity previously supplied by the browser."""

    return _validated_visitor_identity(st.session_state.get(VISITOR_IDENTITY_STATE_KEY))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    return str(value)


def _clean_properties(properties: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): _json_safe(value)
        for key, value in (properties or {}).items()
        if value is not None
    }


def capture_event(event: str, properties: Mapping[str, Any] | None = None) -> bool:
    """Queue one anonymous event; analytics must never break the dashboard."""

    identity = visitor_identity()
    client = _posthog_client()
    if identity is None or client is None:
        return False

    anonymous_session_id = session_id()
    payload = {
        "app": "nba-watchability",
        "analytics_schema_version": ANALYTICS_SCHEMA_VERSION,
        "$session_id": anonymous_session_id,
        "$process_person_profile": False,
        **_clean_properties(properties),
    }
    try:
        client.capture(
            event,
            distinct_id=f"anonymous-visitor:{identity['visitor_id']}",
            properties=payload,
        )
        return True
    except Exception:
        return False


def capture_once(
    event: str,
    once_key: str,
    properties: Mapping[str, Any] | None = None,
) -> bool:
    """Capture at most once per Streamlit session for a caller-defined key."""

    captured = st.session_state.get(CAPTURED_ONCE_KEY)
    if not isinstance(captured, set):
        captured = set(captured or [])
        st.session_state[CAPTURED_ONCE_KEY] = captured
    if once_key in captured:
        return False
    if not capture_event(event, properties):
        return False
    captured.add(once_key)
    return True


def track_session_started() -> bool:
    identity = visitor_identity()
    if identity is None:
        return False
    return capture_once(
        "session_started",
        "session_started",
        {
            "identity_scope": "anonymous_browser",
            "authentication_required": False,
            "is_returning_visitor": identity["is_returning_visitor"],
            "visit_number": identity["visit_number"],
            "visitor_first_seen_at": identity["visitor_first_seen_at"],
            "visitor_persistence": identity["persistence"],
        },
    )
