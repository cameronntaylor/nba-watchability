from __future__ import annotations

import datetime as dt
import os
import sys

from dateutil import tz

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import core.watchability as watch
from core.build_watchability_df import build_watchability_df


def _bucket_counts() -> dict[str, int] | None:
    """
    Returns bucket counts for today's PT slate.
    """
    local_tz = tz.gettz("America/Los_Angeles")
    today_local = dt.datetime.now(local_tz).date()

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

    return counts

def compose_tweet_text() -> str:
    local_tz = tz.gettz("America/Los_Angeles")
    today_dt = dt.datetime.now(local_tz)
    today = f"{today_dt.strftime('%b')} {today_dt.day}"

    counts = None
    try:
        counts = _bucket_counts()
    except Exception:
        counts = None

    parts = [f"🏀 NBA Watchability — {today}"]
    parts.append("")

    if counts:
        parts.append(
            "Must Watch: {mw} | Strong: {s} | Watchable: {w} | Skip: {sk} | Hard Skip: {hs}".format(
                mw=int(counts.get("Must Watch", 0)),
                s=int(counts.get("Strong Watch", 0)),
                w=int(counts.get("Watchable", 0)),
                sk=int(counts.get("Skippable", 0)),
                hs=int(counts.get("Hard Skip", 0)),
            )
        )
    else:
        parts.append("Must Watch: ? | Strong: ? | Watchable: ? | Skip: ? | Hard Skip: ?")

    parts.append("")
    parts.append("Full slate + details: https://nba-watchability.streamlit.app/")
    return "\n".join(parts)
