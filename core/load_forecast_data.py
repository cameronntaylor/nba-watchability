from __future__ import annotations

import os
import pandas as pd


def load_forecast_data(path_parquet: str = os.path.join("data", "forecast", "latest.parquet"), path_csv: str = os.path.join("data", "forecast", "latest.csv")) -> pd.DataFrame:
    try:
        if os.path.exists(path_parquet):
            return pd.read_parquet(path_parquet)
    except Exception:
        pass
    try:
        if os.path.exists(path_csv):
            return pd.read_csv(path_csv)
    except Exception:
        pass
    return pd.DataFrame()
