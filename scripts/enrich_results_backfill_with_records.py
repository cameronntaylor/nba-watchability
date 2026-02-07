#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import sys
from typing import Any

import pandas as pd
from dateutil import tz

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.schedule_espn import fetch_games_for_date


def _parse_date(s: Any) -> dt.date | None:
    if s is None:
        return None
    try:
        return dt.date.fromisoformat(str(s))
    except Exception:
        return None


def _scoreboard_game_records_for_pt_date(pt_date: dt.date) -> dict[str, dict[str, str]]:
    """
    Returns map espn_game_id -> {away_record, home_record, away_team, home_team}.

    ESPN scoreboard "dates=" can include games that belong to the adjacent PT date,
    but this enrichment only needs records, so we fetch pt_date and pt_date+1 and accept all.
    We then match by espn_game_id.
    """
    games = []
    for d in (pt_date, pt_date + dt.timedelta(days=1)):
        games.extend(
            fetch_games_for_date(
                d,
                ttl_seconds=365 * 24 * 60 * 60,
                cache_key_prefix="scoreboard_final",
            )
        )
    out: dict[str, dict[str, str]] = {}
    for g in games:
        gid = str(g.get("game_id") or "").strip()
        if not gid:
            continue
        out[gid] = {
            "away_record": str(g.get("away_record") or ""),
            "home_record": str(g.get("home_record") or ""),
            "away_team": str(g.get("away_team") or ""),
            "home_team": str(g.get("home_team") or ""),
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Enrich existing output/logs/results_backfill/*.csv with `away_record`/`home_record` "
            "using ESPN scoreboard records, writing updated files to a new directory."
        )
    )
    p.add_argument("--in-dir", type=str, default=os.path.join("output", "logs", "results_backfill"))
    p.add_argument(
        "--out-dir",
        type=str,
        default=os.path.join("output", "logs", "results_backfill_enriched"),
    )
    p.add_argument("--start", type=str, default="", help="Only process game_date >= start (YYYY-MM-DD).")
    p.add_argument("--end", type=str, default="", help="Only process game_date <= end (YYYY-MM-DD).")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing enriched files.")
    args = p.parse_args()

    in_dir = os.path.join(PROJECT_ROOT, str(args.in_dir))
    out_dir = os.path.join(PROJECT_ROOT, str(args.out_dir))
    os.makedirs(out_dir, exist_ok=True)

    paths = sorted(glob.glob(os.path.join(in_dir, "*.csv")))
    if not paths:
        print(f"No CSV files found in {in_dir}")
        return 1

    start_d = _parse_date(args.start) if args.start else None
    end_d = _parse_date(args.end) if args.end else None

    cache: dict[str, dict[str, dict[str, str]]] = {}
    processed = 0
    for path in paths:
        df = pd.read_csv(path)
        if df.empty:
            continue
        game_date_str = str(df["game_date"].iloc[0])
        game_date = _parse_date(game_date_str)
        if game_date is None:
            continue
        if start_d and game_date < start_d:
            continue
        if end_d and game_date > end_d:
            continue

        out_path = os.path.join(out_dir, os.path.basename(path))
        if os.path.exists(out_path) and not args.overwrite:
            continue

        if game_date_str not in cache:
            cache[game_date_str] = _scoreboard_game_records_for_pt_date(game_date)
        rec_map = cache[game_date_str]

        if "away_record" not in df.columns:
            df["away_record"] = ""
        if "home_record" not in df.columns:
            df["home_record"] = ""

        def _lookup(row, key: str) -> str:
            gid = str(row.get("espn_game_id") or "").strip()
            if gid and gid in rec_map:
                return str(rec_map[gid].get(key) or "")
            return ""

        df["away_record"] = df.apply(lambda r: _lookup(r, "away_record"), axis=1)
        df["home_record"] = df.apply(lambda r: _lookup(r, "home_record"), axis=1)

        df.to_csv(out_path, index=False)
        processed += 1
        print(f"{game_date_str}: wrote {os.path.relpath(out_path, PROJECT_ROOT)}")

    print(f"Done. Files written: {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

