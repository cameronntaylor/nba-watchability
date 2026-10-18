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

    client = _posthog_client()
    if client is None:
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
            distinct_id=f"anonymous-session:{anonymous_session_id}",
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
    return capture_once(
        "session_started",
        "session_started",
        {
            "identity_scope": "streamlit_session",
            "authentication_required": False,
        },
    )
