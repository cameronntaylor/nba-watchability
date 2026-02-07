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


def _choose_slate_date(df) -> dt.date | None:
    local_tz = tz.gettz("America/Los_Angeles")
    today_local = dt.datetime.now(local_tz).date()
    dates = sorted({d for d in df["Local date"].dropna().tolist()})
    if not dates:
        return None
    return today_local if today_local in dates else dates[0]


def _bucket_counts(df, selected_date: dt.date) -> dict[str, int]:
    buckets = ["Must Watch", "Strong Watch", "Watchable", "Skippable", "Hard Skip"]
    counts = {b: 0 for b in buckets}
    slate = df[df["Local date"] == selected_date]

    # Prefer using the already-computed labels in the DF to avoid any float/threshold drift.
    if "Region" in slate.columns:
        for lbl in slate["Region"].dropna().astype(str).tolist():
            b = lbl.strip()
            if b in counts:
                counts[b] += 1
        return counts

    # Fallback: recompute from WI.
    for wi in slate.get("aWI", []).astype(float).dropna().tolist() if len(slate) else []:
        b = watch.awi_label(float(wi))
        if b in counts:
            counts[b] += 1
    return counts

def compose_tweet_text() -> str:
    local_tz = tz.gettz("America/Los_Angeles")
    df = build_watchability_df(days_ahead=2, tz_name="America/Los_Angeles", include_post=False)
    selected_date = _choose_slate_date(df) if not df.empty else None
    header_date = selected_date or dt.datetime.now(local_tz).date()
    today = f"{header_date.strftime('%b')} {header_date.day}"

    counts = None
    try:
        if selected_date and not df.empty:
            counts = _bucket_counts(df, selected_date)
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
