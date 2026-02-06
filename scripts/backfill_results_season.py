#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import os
import random
import sys
import time
from typing import Any

import pandas as pd
import requests
from dateutil import parser as dtparser
from dateutil import tz

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.results_espn import (
    compute_game_checkpoints,
    extract_closing_spreads,
    extract_leading_scorers,
    fetch_game_summary,
)
from core.schedule_espn import fetch_games_for_date


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _sleep_with_jitter(base_seconds: float, jitter_seconds: float) -> None:
    s = float(base_seconds)
    j = float(jitter_seconds)
    if j > 0:
        s = max(0.0, s + random.uniform(-j, j))
    if s > 0:
        time.sleep(s)


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


def _coerce_int(x: Any):
    try:
        if x is None:
            return None
        return int(float(x))
    except Exception:
        return None


def _daterange(start: dt.date, end_inclusive: dt.date):
    d = start
    while d <= end_inclusive:
        yield d
        d += dt.timedelta(days=1)


def _fetch_scoreboard_with_retry(date: dt.date, *, ttl_seconds: int, max_attempts: int = 5) -> list[dict]:
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch_games_for_date(date, ttl_seconds=ttl_seconds)
        except requests.exceptions.HTTPError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                backoff = min(120.0, 2.0 ** attempt)
                print(f"Scoreboard {date.isoformat()} HTTP {code}; backing off {backoff:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(backoff)
                continue
            raise
        except Exception:
            if attempt < max_attempts:
                backoff = min(60.0, 2.0 ** attempt)
                print(f"Scoreboard {date.isoformat()} failed; backing off {backoff:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(backoff)
                continue
            raise
    return []


def _fetch_summary_with_retry(game_id: str, *, ttl_seconds: int, max_attempts: int = 5) -> dict:
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch_game_summary(game_id, ttl_seconds=ttl_seconds)
        except requests.exceptions.HTTPError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                backoff = min(300.0, 2.5 ** attempt)
                print(f"Summary {game_id} HTTP {code}; backing off {backoff:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(backoff)
                continue
            raise
        except Exception:
            if attempt < max_attempts:
                backoff = min(120.0, 2.5 ** attempt)
                print(f"Summary {game_id} failed; backing off {backoff:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(backoff)
                continue
            raise
    return {}


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Backfill completed-game results for a PT date range (final score + win-probability checkpoints), "
            "writing per-day CSV/parquet files. Uses disk HTTP cache and rate limiting to reduce ESPN blocking."
        )
    )
    p.add_argument("--start", type=str, required=True, help="Start PT date (YYYY-MM-DD), inclusive.")
    p.add_argument("--end", type=str, required=True, help="End PT date (YYYY-MM-DD), inclusive.")
    p.add_argument("--tz", type=str, default="America/Los_Angeles")
    p.add_argument("--sleep", type=float, default=2.0, help="Base seconds to sleep between ESPN summary calls.")
    p.add_argument("--jitter", type=float, default=1.0, help="Random jitter (+/- seconds) added to --sleep.")
    p.add_argument("--skip-existing", action="store_true", help="Skip a day if an output file already exists.")
    p.add_argument("--verbose", action="store_true", help="Print per-day ESPN state counts for debugging.")
    p.add_argument("--out-dir", type=str, default=os.path.join("output", "logs", "results_backfill"))
    p.add_argument("--data-version", type=str, default=os.getenv("WATCHABILITY_DATA_VERSION", "v2"))
    args = p.parse_args()

    pt_tz = tz.gettz(str(args.tz))
    start = dt.date.fromisoformat(str(args.start))
    end = dt.date.fromisoformat(str(args.end))
    if end < start:
        raise SystemExit("--end must be >= --start")

    out_dir = os.path.join(PROJECT_ROOT, str(args.out_dir))
    os.makedirs(out_dir, exist_ok=True)

    # Use separate cache keys for backfill so we don't accidentally reuse an old "pre/in" cached response
    # from when the app was first opened.
    scoreboard_ttl = 365 * 24 * 60 * 60
    summary_ttl = 365 * 24 * 60 * 60

    total_rows = 0
    for target_date in _daterange(start, end):
        out_base = f"results_{target_date.isoformat()}"
        out_csv = os.path.join(out_dir, f"{out_base}.csv")
        out_parquet = os.path.join(out_dir, f"{out_base}.parquet")

        if args.skip_existing and (os.path.exists(out_csv) or os.path.exists(out_parquet)):
            print(f"Skipping {target_date.isoformat()} (exists).")
            continue

        # Fetch two adjacent scoreboard days and re-bucket games by PT tip date.
        games = []
        for d in (target_date, target_date + dt.timedelta(days=1)):
            games.extend(fetch_games_for_date(d, ttl_seconds=scoreboard_ttl, cache_key_prefix="scoreboard_final"))

        if args.verbose and games:
            counts = {}
            for g in games:
                st = str(g.get("state") or "")
                counts[st] = counts.get(st, 0) + 1
            print(f"{target_date.isoformat()}: scoreboard states {counts}")

        post_games = []
        for g in games:
            pt_date = _pt_game_date(g.get("start_time_utc"), pt_tz)
            if pt_date != target_date:
                continue
            if str(g.get("state")) != "post":
                continue
            post_games.append(g)

        if not post_games:
            print(f"{target_date.isoformat()}: no completed games found.")
            continue

        now_utc = _utc_now()
        time_log_utc = now_utc.isoformat().replace("+00:00", "Z")

        rows: list[dict] = []
        for idx, g in enumerate(post_games, start=1):
            game_id = str(g.get("game_id") or "")
            away_team = str(g.get("away_team") or "")
            home_team = str(g.get("home_team") or "")
            away_final = _coerce_int(g.get("away_score"))
            home_final = _coerce_int(g.get("home_score"))

            summary = (
                fetch_game_summary(game_id, ttl_seconds=summary_ttl, cache_key_prefix="summary_final")
                if game_id
                else {}
            )
            checkpoints = compute_game_checkpoints(summary) if summary else {}
            spreads = extract_closing_spreads(summary) if summary else {}
            scorers = extract_leading_scorers(summary) if summary else {}

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

            if idx < len(post_games):
                _sleep_with_jitter(float(args.sleep), float(args.jitter))

        out = pd.DataFrame(rows)
        try:
            out.to_parquet(out_parquet, index=False)
        except Exception as e:
            raise RuntimeError("Failed to write parquet. Install `pyarrow` (recommended) or `fastparquet`.") from e
        out.to_csv(out_csv, index=False)

        total_rows += len(out)
        print(f"{target_date.isoformat()}: wrote {len(out)} games -> {os.path.relpath(out_csv, PROJECT_ROOT)}")

        # Small pause between days to be extra gentle.
        _sleep_with_jitter(float(args.sleep), float(args.jitter))

    print(f"Done. Total rows written: {total_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
