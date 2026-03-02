from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

import yaml


@dataclass(frozen=True)
class ForecastConfig:
    days_ahead: int = 7
    lookback_days: int = 7
    a1: float = 30.0
    a2: float = 0.0
    home_intercept: float = -2.0
    default_health: float = 0.92
    default_star_tq_points: float = 2.0
    min_games_for_team_spread_avg: int = 3


DEFAULT_FORECAST_CONFIG_PATH = os.path.join("config", "forecast.yml")


def load_forecast_config(path: str | None = None) -> ForecastConfig:
    cfg_path = Path(path or DEFAULT_FORECAST_CONFIG_PATH)
    if not cfg_path.exists():
        return ForecastConfig()

    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return ForecastConfig()

    def _i(name: str, default: int) -> int:
        try:
            return int(raw.get(name, default))
        except Exception:
            return int(default)

    def _f(name: str, default: float) -> float:
        try:
            return float(raw.get(name, default))
        except Exception:
            return float(default)

    return ForecastConfig(
        days_ahead=max(1, _i("days_ahead", 7)),
        lookback_days=max(1, _i("lookback_days", 7)),
        a1=_f("a1", 30.0),
        a2=_f("a2", 0.0),
        home_intercept=_f("home_intercept", -2.0),
        default_health=max(0.0, min(1.0, _f("default_health", 0.92))),
        default_star_tq_points=max(0.0, _f("default_star_tq_points", 2.0)),
        min_games_for_team_spread_avg=max(1, _i("min_games_for_team_spread_avg", 3)),
    )
