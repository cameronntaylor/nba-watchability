#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.build_watchability_df import build_watchability_df, build_watchability_sources_summary


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def main() -> int:
    p = argparse.ArgumentParser(description="Log daily per-game Watchability scores to output/logs/.")
    p.add_argument("--days-ahead", type=int, default=2)
    p.add_argument("--tz", type=str, default="America/Los_Angeles")
    p.add_argument("--data-version", type=str, default=os.getenv("WATCHABILITY_DATA_VERSION", "v2"))
    args = p.parse_args()

    df = build_watchability_df(days_ahead=int(args.days_ahead), tz_name=str(args.tz))
    if df.empty:
        print("No games returned; nothing to log.")
        return 0

    now_utc = _utc_now()
    time_log_utc = now_utc.isoformat().replace("+00:00", "Z")
    sources = build_watchability_sources_summary(df)

    def _fmt_tip(dt_pt) -> str:
        if dt_pt is None or (isinstance(dt_pt, float) and pd.isna(dt_pt)):
            return ""
        if isinstance(dt_pt, dt.datetime):
            return dt_pt.strftime("%a %I:%M %p")
        return str(dt_pt)

    out = pd.DataFrame(
        {
            "game_date": df["Local date"].astype(str),
            "tip_time_pt": df["Tip dt (PT)"].apply(_fmt_tip),
            "time_log_utc": time_log_utc,
            "away_team": df["Away team"].astype(str),
            "home_team": df["Home team"].astype(str),
            "away_win_pct": df["Win% (away raw)"].astype(float),
            "home_win_pct": df["Win% (home raw)"].astype(float),
            "home_spread": df["Home spread"],
            "health_score_away": df["Health (away)"].astype(float),
            "health_score_home": df["Health (home)"].astype(float),
            "team_quality_score": df["Team quality"].astype(float),
            "competitiveness_score": df["Closeness"].astype(float),
            "watchability_score": df["aWI"].astype(float),
            "text_label": df["Region"].astype(str),
            "data_version": str(args.data_version),
            "sources": sources,
        }
    )

    out_dir = os.path.join(PROJECT_ROOT, "output", "logs")
    os.makedirs(out_dir, exist_ok=True)

    date_str = now_utc.strftime("%Y-%m-%d")
    ts_str = now_utc.strftime("%H%M%SZ")
    base = f"watchability_{date_str}_{ts_str}"
    parquet_path = os.path.join(out_dir, f"{base}.parquet")
    csv_path = os.path.join(out_dir, f"{base}.csv")

    try:
        out.to_parquet(parquet_path, index=False)
    except Exception as e:
        raise RuntimeError(
            "Failed to write parquet. Install `pyarrow` (recommended) or `fastparquet`."
        ) from e

    out.to_csv(csv_path, index=False)
    print(f"Wrote {len(out)} rows:")
    print(f"- {parquet_path}")
    print(f"- {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

