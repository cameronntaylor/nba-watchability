from __future__ import annotations


def predict_home_spread(
    *,
    home_wp: float,
    away_wp: float,
    home_avg_spread_7d: float,
    away_avg_spread_7d: float,
    a1: float,
    a2: float,
    home_intercept: float,
) -> float:
    """
    Predicted home spread:
      home_intercept
      - a1 * (home_wp - away_wp)
      + a2 * (home_avg_spread_7d - away_avg_spread_7d)

    Convention: negative home spread means home team is favored.
    """
    return (
        float(home_intercept)
        - float(a1) * (float(home_wp) - float(away_wp))
        + float(a2) * (float(home_avg_spread_7d) - float(away_avg_spread_7d))
    )
