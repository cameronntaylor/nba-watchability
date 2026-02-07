#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import sys
from typing import Any, Dict, Optional, Tuple

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import core.watchability as watch


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_record(record: Any) -> Tuple[Optional[int], Optional[int]]:
    """
    Parses '31-18' -> (31, 18).
    """
    if record is None:
        return None, None
    s = str(record).strip()
    if not s or s == "nan":
        return None, None
    if "-" not in s:
        return None, None
    a, b = s.split("-", 1)
    try:
        w = int(a.strip())
        l = int(b.strip())
        if w < 0 or l < 0:
            return None, None
        return w, l
    except Exception:
        return None, None


def _win_pct_from_record(record: Any, default: float = 0.5) -> float:
    w, l = _parse_record(record)
    if w is None or l is None:
        return float(default)
    denom = w + l
    if denom <= 0:
        return float(default)
    return float(w) / float(denom)


def _coerce_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if not s or s == "nan":
            return None
        return float(s.replace("+", ""))
    except Exception:
        return None


def _build_row(
    r: pd.Series,
    *,
    assumed_health: float,
    assumed_star_tq_points: float,
) -> Dict[str, Any]:
    """
    Compute an estimated Watchability score using:
      - closing spread (abs(home_spread_close))
      - team win% from record
      - assumed health multiplier
      - assumed star bump (expressed as Team Quality points, e.g. 2 => +2 on 0..100 scale)
    """
    home_record = r.get("home_record")
    away_record = r.get("away_record")

    home_win = _win_pct_from_record(home_record, default=0.5)
    away_win = _win_pct_from_record(away_record, default=0.5)

    # Approximate injury-adjusted strength.
    h = max(0.0, min(1.0, float(assumed_health)))
    home_adj = max(0.0, min(1.0, home_win * h))
    away_adj = max(0.0, min(1.0, away_win * h))

    # Convert "Team Quality points" to an equivalent *win%* bump.
    # watch.team_quality(avg_wp) ≈ (avg_wp - WIN_MIN) / (WIN_MAX - WIN_MIN)
    # so Δq ≈ Δavg_wp / (WIN_MAX - WIN_MIN).  Therefore Δavg_wp ≈ Δq * (WIN_MAX - WIN_MIN).
    # Team Quality points are on 0..100 scale, so Δq = points / 100.
    dq = float(assumed_star_tq_points) / 100.0
    d_avg_wp = dq * (float(watch.WIN_MAX) - float(watch.WIN_MIN))

    # Apply per-team bump so the average bump contributes d_avg_wp to the matchup average.
    # If we add +d_avg_wp to BOTH teams, the matchup average increases by +d_avg_wp.
    home_adj = max(0.0, min(1.0, home_adj + d_avg_wp))
    away_adj = max(0.0, min(1.0, away_adj + d_avg_wp))

    home_spread_close = _coerce_float(r.get("home_spread_close"))
    abs_spread = abs(float(home_spread_close)) if home_spread_close is not None else None

    w_out = watch.compute_watchability(home_adj, away_adj, abs_spread)

    return {
        "game_date": str(r.get("game_date") or ""),
        "time_log_utc": str(r.get("time_log_utc") or ""),
        "espn_game_id": str(r.get("espn_game_id") or ""),
        "away_team": str(r.get("away_team") or ""),
        "home_team": str(r.get("home_team") or ""),
        "away_record": str(away_record or ""),
        "home_record": str(home_record or ""),
        "away_win_pct_est": float(away_win),
        "home_win_pct_est": float(home_win),
        "assumed_health": float(h),
        "assumed_star_tq_points": float(assumed_star_tq_points),
        "away_adj_win_pct_est": float(away_adj),
        "home_adj_win_pct_est": float(home_adj),
        "home_spread_close": home_spread_close,
        "abs_spread_close": abs_spread,
        "team_quality": float(w_out.team_quality),
        "competitiveness": float(w_out.closeness),
        "watchability": float(w_out.awi),
        "label": str(w_out.label),
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Backfill an *estimated* Watchability score for historical games using backfilled ESPN results logs "
            "(closing spread + team record). This intentionally avoids relying on historical injuries/stars."
        )
    )
    p.add_argument("--in-dir", type=str, default=os.path.join("output", "logs", "results_backfill"))
    p.add_argument("--out-dir", type=str, default=os.path.join("output", "logs"))
    p.add_argument("--start", type=str, default="", help="Filter PT game_date >= start (YYYY-MM-DD).")
    p.add_argument("--end", type=str, default="", help="Filter PT game_date <= end (YYYY-MM-DD).")
    p.add_argument("--assumed-health", type=float, default=0.9)
    p.add_argument("--assumed-star-tq", type=float, default=2.0, help="Per-team star bump in Team Quality points.")
    args = p.parse_args()

    pattern = os.path.join(PROJECT_ROOT, str(args.in_dir), "*.csv")
    paths = sorted(glob.glob(pattern))
    if not paths:
        print(f"No input files found at {pattern}")
        return 1

    df = pd.concat((pd.read_csv(pth) for pth in paths), ignore_index=True)
    if df.empty:
        print("No rows loaded from results_backfill.")
        return 0

    # Normalize expected columns (older backfills may not have record columns).
    if "home_record" not in df.columns:
        df["home_record"] = ""
    if "away_record" not in df.columns:
        df["away_record"] = ""
    if "home_spread_close" not in df.columns:
        df["home_spread_close"] = None

    # Warn if records are missing/empty (win% will default to 0.5).
    if df["home_record"].astype(str).str.strip().replace("nan", "").eq("").all() or df["away_record"].astype(str).str.strip().replace("nan", "").eq("").all():
        print(
            "Warning: `home_record`/`away_record` are missing or empty in the input results; "
            "win% will default to 0.5 for affected rows. "
            "If you want records, enrich results via `python scripts/enrich_results_backfill_with_records.py` "
            "and re-run this script with `--in-dir output/logs/results_backfill_enriched`."
        )

    if args.start:
        df = df[df["game_date"].astype(str) >= str(args.start)]
    if args.end:
        df = df[df["game_date"].astype(str) <= str(args.end)]
    if df.empty:
        print("No rows after date filtering.")
        return 0

    rows = [
        _build_row(
            r,
            assumed_health=float(args.assumed_health),
            assumed_star_tq_points=float(args.assumed_star_tq),
        )
        for _, r in df.iterrows()
    ]
    out = pd.DataFrame(rows)
    out = out.sort_values(["game_date", "watchability"], ascending=[True, False]).reset_index(drop=True)

    out_dir = os.path.join(PROJECT_ROOT, str(args.out_dir))
    os.makedirs(out_dir, exist_ok=True)

    now = _utc_now()
    ts = now.strftime("%Y%m%d_%H%M%SZ")
    base = f"watchability_backfill_est_{ts}"
    parquet_path = os.path.join(out_dir, f"{base}.parquet")
    csv_path = os.path.join(out_dir, f"{base}.csv")

    try:
        out.to_parquet(parquet_path, index=False)
    except Exception as e:
        raise RuntimeError("Failed to write parquet. Install `pyarrow` (recommended) or `fastparquet`.") from e
    out.to_csv(csv_path, index=False)

    print(f"Wrote {len(out)} rows:")
    print(f"- {parquet_path}")
    print(f"- {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
