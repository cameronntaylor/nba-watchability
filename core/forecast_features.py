from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict

import pandas as pd
from dateutil import tz

from core.standings import _normalize_team_name


def _to_date(x) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(x))
    except Exception:
        return None


def _read_watchability_logs(logs_dir: Path) -> pd.DataFrame:
    files = sorted(logs_dir.glob("watchability_*.csv"))
    if not files:
        return pd.DataFrame()
    chunks = []
    for f in files[-90:]:
        try:
            chunks.append(pd.read_csv(f))
        except Exception:
            continue
    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


def build_team_recent_feature_map(
    *,
    lookback_days: int,
    default_health: float,
    default_star_factor: float,
    min_games_for_team_spread_avg: int,
    logs_dir: str = "output/logs",
    now_pt: dt.datetime | None = None,
) -> Dict[str, dict]:
    """
    Returns normalized_team_name -> {
      avg_health_7d, avg_star_factor_7d, avg_team_spread_7d, n_games
    }

    - star factor is converted from logged Team Quality bump points to win% units.
    - team spread is team-perspective spread: home spread if team home else -home spread if team away.
    """
    now_pt = now_pt or dt.datetime.now(tz=tz.gettz("America/Los_Angeles"))
    as_of = now_pt.date()
    start = as_of - dt.timedelta(days=max(1, int(lookback_days)))

    df = _read_watchability_logs(Path(logs_dir))
    if df.empty:
        return {}

    df["_game_date"] = df.get("game_date").apply(_to_date)
    df = df[df["_game_date"].notna()].copy()
    df = df[(df["_game_date"] >= start) & (df["_game_date"] <= as_of)].copy()
    if df.empty:
        return {}

    # Coerce numerics.
    for col in [
        "home_spread",
        "health_score_away",
        "health_score_home",
        "away_star_tq_bump",
        "home_star_tq_bump",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    away = pd.DataFrame(
        {
            "team": df.get("away_team", "").astype(str),
            "health": df.get("health_score_away"),
            "star_factor": (df.get("away_star_tq_bump", 0.0).fillna(0.0) / 100.0),
            "team_spread": -pd.to_numeric(df.get("home_spread"), errors="coerce"),
        }
    )
    home = pd.DataFrame(
        {
            "team": df.get("home_team", "").astype(str),
            "health": df.get("health_score_home"),
            "star_factor": (df.get("home_star_tq_bump", 0.0).fillna(0.0) / 100.0),
            "team_spread": pd.to_numeric(df.get("home_spread"), errors="coerce"),
        }
    )

    teams = pd.concat([away, home], ignore_index=True)
    teams["team_key"] = teams["team"].apply(_normalize_team_name)

    agg = teams.groupby("team_key", dropna=False).agg(
        avg_health_7d=("health", "mean"),
        avg_star_factor_7d=("star_factor", "mean"),
        avg_team_spread_7d=("team_spread", "mean"),
        n_games=("team", "count"),
        n_spread=("team_spread", lambda s: int(s.notna().sum())),
    )

    out: Dict[str, dict] = {}
    for team_key, r in agg.iterrows():
        if not team_key:
            continue
        try:
            h = float(r["avg_health_7d"])
        except Exception:
            h = float(default_health)
        if pd.isna(h):
            h = float(default_health)

        try:
            sf = float(r["avg_star_factor_7d"])
        except Exception:
            sf = float(default_star_factor)
        if pd.isna(sf):
            sf = float(default_star_factor)

        try:
            n_spread = int(r.get("n_spread", 0))
        except Exception:
            n_spread = 0
        try:
            s = float(r["avg_team_spread_7d"])
        except Exception:
            s = 0.0
        if pd.isna(s) or n_spread < int(min_games_for_team_spread_avg):
            s = 0.0

        out[str(team_key)] = {
            "avg_health_7d": max(0.0, min(1.0, h)),
            "avg_star_factor_7d": max(0.0, sf),
            "avg_team_spread_7d": float(s),
            "n_games": int(r.get("n_games", 0) or 0),
        }

    return out
