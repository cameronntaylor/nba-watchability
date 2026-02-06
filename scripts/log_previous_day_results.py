#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import pandas as pd
from dateutil import parser as dtparser
from dateutil import tz

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.results_espn import (
    compute_game_checkpoints,
    extract_game_injuries_detail,
    extract_closing_spreads,
    extract_leading_scorers,
    fetch_game_summary,
)
from core.schedule_espn import fetch_games_for_date


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _coerce_int(x):
    try:
        if x is None:
            return None
        return int(float(x))
    except Exception:
        return None


def _pt_game_date(start_time_utc: str | None, pt_tz) -> dt.date | None:
    if not start_time_utc:
        return None
    try:
        t = dtparser.isoparse(str(start_time_utc))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return t.astimezone(pt_tz).date()
    except Exception:
        return None


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Log previous-day completed game results (final score + ESPN win probability checkpoints) "
            "to output/logs/ for analysis."
        )
    )
    p.add_argument("--tz", type=str, default="America/Los_Angeles")
    p.add_argument("--days-back", type=int, default=1, help="How many PT days back to log (default: 1 = yesterday).")
    p.add_argument("--game-date", type=str, default="", help="Override PT date (YYYY-MM-DD).")
    p.add_argument("--data-version", type=str, default=os.getenv("WATCHABILITY_DATA_VERSION", "v2"))
    args = p.parse_args()

    pt_tz = tz.gettz(str(args.tz))
    if args.game_date:
        target_date = dt.date.fromisoformat(str(args.game_date))
    else:
        target_date = dt.datetime.now(pt_tz).date() - dt.timedelta(days=int(args.days_back))

    # ESPN's scoreboard "dates=" is not guaranteed to align with PT dates for late games.
    # Fetch two adjacent scoreboard days and re-bucket games by PT tip date.
    scoreboard_days = [target_date, target_date + dt.timedelta(days=1)]
    games = []
    for d in scoreboard_days:
        try:
            games.extend(fetch_games_for_date(d, ttl_seconds=60 * 15, cache_key_prefix="scoreboard_final"))
        except Exception as e:
            print(f"Failed to fetch ESPN scoreboard for {d.isoformat()}: {e}")
            return 0

    post_games = []
    for g in games:
        pt_date = _pt_game_date(g.get("start_time_utc"), pt_tz)
        if pt_date != target_date:
            continue
        if str(g.get("state")) != "post":
            continue
        post_games.append(g)

    if not post_games:
        print(f"No completed games found for PT date {target_date.isoformat()}.")
        return 0

    now_utc = _utc_now()
    time_log_utc = now_utc.isoformat().replace("+00:00", "Z")

    rows: list[dict] = []
    for g in post_games:
        game_id = str(g.get("game_id") or "")
        away_team = str(g.get("away_team") or "")
        home_team = str(g.get("home_team") or "")
        away_final = _coerce_int(g.get("away_score"))
        home_final = _coerce_int(g.get("home_score"))

        summary = {}
        if game_id:
            try:
                summary = fetch_game_summary(
                    game_id,
                    ttl_seconds=60 * 60 * 24 * 7,
                    cache_key_prefix="summary_final",
                )
            except Exception:
                summary = {}
        checkpoints = compute_game_checkpoints(summary) if summary else {}
        spreads = extract_closing_spreads(summary) if summary else {}
        scorers = extract_leading_scorers(summary) if summary else {}
        injuries = extract_game_injuries_detail(summary) if summary else {}

        rows.append(
            {
                "game_date": target_date.isoformat(),
                "time_log_utc": time_log_utc,
                "espn_game_id": game_id,
                "away_team": away_team,
                "home_team": home_team,
                "away_record": str(g.get("away_record") or ""),
                "home_record": str(g.get("home_record") or ""),
                "away_score_final": away_final,
                "home_score_final": home_final,
                "home_spread_close": spreads.get("home_spread_close"),
                "away_spread_close": spreads.get("away_spread_close"),
                "spread_provider": spreads.get("spread_provider"),
                "away_leading_scorer": scorers.get("away_leading_scorer"),
                "away_leading_scorer_pts": scorers.get("away_leading_scorer_pts"),
                "home_leading_scorer": scorers.get("home_leading_scorer"),
                "home_leading_scorer_pts": scorers.get("home_leading_scorer_pts"),
                "away_injuries_detail_json": injuries.get("away_injuries_detail_json", "[]"),
                "home_injuries_detail_json": injuries.get("home_injuries_detail_json", "[]"),
                "away_wp_swing": checkpoints.get("away_wp_swing"),
                "away_wp_end_q1": checkpoints.get("away_wp_end_q1"),
                "score_diff_end_q1": checkpoints.get("score_diff_end_q1"),
                "away_wp_end_q2": checkpoints.get("away_wp_end_q2"),
                "score_diff_end_q2": checkpoints.get("score_diff_end_q2"),
                "away_wp_end_q3": checkpoints.get("away_wp_end_q3"),
                "score_diff_end_q3": checkpoints.get("score_diff_end_q3"),
                "away_wp_5m_left_q4": checkpoints.get("away_wp_5m_left_q4"),
                "score_diff_5m_left_q4": checkpoints.get("score_diff_5m_left_q4"),
                "data_version": str(args.data_version),
                "sources": "espn_scoreboard+espn_summary",
            }
        )

    out = pd.DataFrame(rows)
    out_dir = os.path.join(PROJECT_ROOT, "output", "logs")
    os.makedirs(out_dir, exist_ok=True)

    ts_str = now_utc.strftime("%H%M%SZ")
    base = f"results_{target_date.isoformat()}_{ts_str}"
    parquet_path = os.path.join(out_dir, f"{base}.parquet")
    csv_path = os.path.join(out_dir, f"{base}.csv")

    try:
        out.to_parquet(parquet_path, index=False)
    except Exception as e:
        raise RuntimeError("Failed to write parquet. Install `pyarrow` (recommended) or `fastparquet`.") from e
    out.to_csv(csv_path, index=False)

    print(f"Wrote {len(out)} rows for PT date {target_date.isoformat()}:")
    print(f"- {parquet_path}")
    print(f"- {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
