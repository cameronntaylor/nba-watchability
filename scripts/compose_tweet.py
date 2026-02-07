from __future__ import annotations

from datetime import date
import os
import sys

from dateutil import tz
from dateutil import parser as dtparser

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import core.watchability as watch
from core.build_watchability_df import build_watchability_df


def _bucket_summary() -> str | None:
    """
    Returns a short string like:
    '2 Must Watch Games, 3 Strong Watch Games, 4 Watchable Games, 1 Skippable Games and 0 Hard Skip Games'
    for today's PT slate.
    """
    local_tz = tz.gettz("America/Los_Angeles")
    today_local = date.today()

    df = build_watchability_df(days_ahead=2, tz_name="America/Los_Angeles", include_post=False)
    if df.empty:
        return None

    dates = sorted({d for d in df["Local date"].dropna().tolist()})
    if not dates:
        return None

    selected_date = today_local if today_local in dates else dates[0]
    wis = df[df["Local date"] == selected_date]["aWI"].astype(float).dropna().tolist()

    if not wis:
        return None

    buckets = ["Must Watch", "Strong Watch", "Watchable", "Skippable", "Hard Skip"]
    counts = {b: 0 for b in buckets}
    for wi in wis:
        b = watch.awi_label(float(wi))
        if b in counts:
            counts[b] += 1

    x1 = counts["Must Watch"]
    x2 = counts["Strong Watch"]
    x3 = counts["Watchable"]
    x4 = counts["Skippable"]
    x5 = counts["Hard Skip"]
    return (
        f"Must Watch: {x1} | Strong: {x2} | Watchable: {x3} | Skippable: {x4} | Hard Skip: {x5}"
    )

def compose_tweet_text():
    today = date.today().strftime("%b %d")
    avg_line = None
    try:
        avg_line = _bucket_summary()
    except Exception:
        avg_line = None

    parts = [f"🏀 NBA Watchability — {today}"]
    if avg_line:
        parts.append(avg_line)
    parts.append("")
    parts.append("Full slate + details:: https://nba-watchability.streamlit.app/")
    return "\n".join(parts)