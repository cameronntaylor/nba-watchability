#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.build_watchability_forecast_df import build_watchability_forecast_df
from core.forecast_config import load_forecast_config


def main() -> int:
    cfg = load_forecast_config()
    df = build_watchability_forecast_df(days_ahead=cfg.days_ahead)

    out_dir = os.path.join(PROJECT_ROOT, "data", "forecast")
    os.makedirs(out_dir, exist_ok=True)

    parquet_path = os.path.join(out_dir, "latest.parquet")
    csv_path = os.path.join(out_dir, "latest.csv")
    json_path = os.path.join(out_dir, "latest.json")

    if df.empty:
        # still write empty files to keep app flow deterministic
        pd.DataFrame().to_csv(csv_path, index=False)
        pd.DataFrame().to_json(json_path, orient="records")
        try:
            pd.DataFrame().to_parquet(parquet_path, index=False)
        except Exception:
            pass
        print("Forecast build produced 0 rows.")
        return 0

    df.to_csv(csv_path, index=False)
    df.to_json(json_path, orient="records")
    try:
        df.to_parquet(parquet_path, index=False)
    except Exception:
        print("Warning: parquet write failed; csv/json written.")

    print(f"Wrote forecast rows: {len(df)}")
    print(f"- {csv_path}")
    print(f"- {parquet_path}")
    print(f"- {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
