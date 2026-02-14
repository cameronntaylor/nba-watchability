from __future__ import annotations

from datetime import date
from pathlib import Path
import json
import os
import sys
import csv

from dateutil import tz

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.build_watchability_df import build_watchability_df


TWEET_META_PATH = Path("output") / "tweet_meta.json"
LOGS_DIR = Path("output") / "logs"


def _try_load_counts_from_dashboard_meta() -> tuple[str | None, dict[str, int] | None, dict | None]:
    if not TWEET_META_PATH.exists():
        return None, None, None
    try:
        meta = json.loads(TWEET_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None

    tweet_date = meta.get("tweet_date")
    counts_raw = meta.get("counts")
    if not isinstance(counts_raw, dict):
        return tweet_date if isinstance(tweet_date, str) else None, None, meta

    counts: dict[str, int] = {}
    for k, v in counts_raw.items():
        try:
            counts[str(k)] = int(v)
        except Exception:
            continue
    return tweet_date if isinstance(tweet_date, str) else None, counts, meta


def _bucket_summary_from_counts(counts: dict[str, int]) -> str:
    x1 = int(counts.get("Must Watch", 0))
    x2 = int(counts.get("Strong Watch", 0))
    x3 = int(counts.get("Watchable", 0))
    x4 = int(counts.get("Skippable", 0))
    x5 = int(counts.get("Hard Skip", 0))
    return f"Must Watch: {x1} | Strong: {x2} | Watchable: {x3} | Skip: {x4} | Hard Skip: {x5}"

def _try_load_counts_from_latest_log() -> tuple[str | None, dict[str, int] | None]:
    if not LOGS_DIR.exists():
        return None, None
    csv_files = sorted(LOGS_DIR.glob("watchability_*.csv"))
    if not csv_files:
        return None, None
    latest = max(csv_files, key=lambda p: p.stat().st_mtime)
    try:
        with latest.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return None, None
    if not rows:
        return None, None

    # Match dashboard default: earliest PT slate in the window.
    dates = sorted({str(r.get("game_date") or "").strip() for r in rows if str(r.get("game_date") or "").strip()})
    if not dates:
        return None, None
    slate_day = dates[0]
    slate_rows = [r for r in rows if str(r.get("game_date") or "").strip() == slate_day]
    counts: dict[str, int] = {}
    for r in slate_rows:
        label = str(r.get("text_label") or "").strip()
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1

    tweet_date = None
    try:
        y, m, d = (int(x) for x in slate_day.split("-"))
        tweet_date = date(y, m, d).strftime("%b %d").replace(" 0", " ")
    except Exception:
        tweet_date = None
    return tweet_date, counts


def _bucket_summary_fallback() -> tuple[str | None, str | None]:
    df = build_watchability_df(days_ahead=2, tz_name="America/Los_Angeles", include_post=False)
    if df.empty or "Local date" not in df.columns:
        return None, None

    dates = sorted({d for d in df["Local date"].dropna().tolist()})
    if not dates:
        return None, None

    # Match dashboard default: earliest PT slate in the window.
    selected_date = dates[0]
    df_slate = df[df["Local date"] == selected_date].copy()
    if df_slate.empty or "Region" not in df_slate.columns:
        return None, None

    counts = df_slate["Region"].astype(str).value_counts()
    summary = _bucket_summary_from_counts({str(k): int(v) for k, v in counts.items()})
    tweet_date = selected_date.strftime("%b %d").replace(" 0", " ")
    return tweet_date, summary

def compose_tweet_text():
    # Prefer counts embedded in the deployed dashboard metadata captured alongside the screenshot.
    tweet_date, counts, meta = _try_load_counts_from_dashboard_meta()
    summary = None
    n_games = None
    if counts:
        summary = _bucket_summary_from_counts(counts)
        slate_day = meta.get("slate_day") if isinstance(meta, dict) else None
        try:
            n_games = int(meta.get("n_games")) if isinstance(meta, dict) and meta.get("n_games") is not None else None
        except Exception:
            n_games = None
        print(f"[tweet] using dashboard meta (slate_day={slate_day}) -> {summary}")
    else:
        tweet_date, counts = _try_load_counts_from_latest_log()
        if counts:
            summary = _bucket_summary_from_counts(counts)
            try:
                n_games = sum(int(v) for v in counts.values())
            except Exception:
                n_games = None
            print(f"[tweet] using latest log -> {summary}")
    if not summary:
        try:
            tweet_date2, summary2 = _bucket_summary_fallback()
            if summary2:
                tweet_date = tweet_date or tweet_date2
                summary = summary2
                print(f"[tweet] using fallback computation -> {summary}")
        except Exception:
            pass

    if not tweet_date:
        # Last resort: PT calendar date.
        tweet_date = date.today().strftime("%b %d").replace(" 0", " ")

    # If we can't confidently identify a slate with games, skip tweeting.
    if (isinstance(n_games, int) and n_games == 0) or (n_games is None and summary is None):
        return None

    header = f"🏀 NBA Watchability — {tweet_date}"
    if isinstance(n_games, int) and n_games >= 0:
        header = f"{header} — {n_games} games"
    parts = [header, ""]
    if summary:
        parts.append("")
        parts.append(summary)
        parts.append("")
    parts.append("Full slate + details: https://nba-watchability.streamlit.app/")
    return "\n".join(parts)
