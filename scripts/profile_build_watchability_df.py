#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.build_watchability_df import build_watchability_df


def main() -> int:
    print("Profiling build_watchability_df(days_ahead=2) ...")
    t0 = time.perf_counter()
    df1 = build_watchability_df(days_ahead=2)
    t1 = time.perf_counter()
    df2 = build_watchability_df(days_ahead=2)
    t2 = time.perf_counter()

    print(f"Cold-ish run: {t1 - t0:.2f}s ({len(df1)} games)")
    print(f"Warm run:    {t2 - t1:.2f}s ({len(df2)} games)")
    print("")
    print("Notes:")
    print("- Warm run should be fast if `.cache/http/*` is populated and Streamlit isn't restarting.")
    print("- Control ESPN summary parallelism via NBA_WATCH_SUMMARY_WORKERS (default 8).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

