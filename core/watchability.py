from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.watchability_v2_params import SIGMA

# Best and worst possible spreads bunched
SPREAD_CAP = 15
SPREAD_MIN = 0.5

# Best and worst possible win percentages bunched
WIN_MAX = 0.7
WIN_MIN = 0.2

# Extra multiplier for quality and closeness
RELATIVE_QUALITY_MULTIPLIER = 0.7

# Curvature of closeness score (to allow spreads to matter more as they get larger)
CLOSENESS_CURVATURE = 0.9

# Floors for each input into utility
QUALITY_FLOOR = 0.1
CLOSENESS_FLOOR = 0.1

# Cap component inputs to CES utility (prevents extremes dominating).
COMPONENT_CAP = 1.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def _clamp01_floor(x: float, floor: float) -> float:
    return max(float(floor), min(1.0, float(x)))


def team_quality(
    w1: float,
    w2: float,
    floor: float = QUALITY_FLOOR,
    win_max: float = WIN_MAX,
    win_min: float = WIN_MIN,
) -> float:
    """
    Team quality for a matchup, normalized to ~[0,1].
    Defined as: (avg(win%) - min(win%)) / (max(win%) - min(win%))
    """
    avg_wp = 0.5 * (float(w1) + float(w2))
    return _clamp01_floor((avg_wp - win_min) / (win_max - win_min), floor=floor)


def closeness(
    abs_spread: Optional[float],
    cap: float = SPREAD_CAP,
    spread_min: float = SPREAD_MIN,
    floor: float = CLOSENESS_FLOOR,
    closeness_curvature: float = CLOSENESS_CURVATURE,
) -> float:
    """
    Closeness score for a matchup, normalized to [0,1].
    Defined as: (SPREAD_CAP - |spread|) / SPREAD_CAP, clipped to [floor, 1].
    """
    if cap <= 0:
        return float(floor)
    if abs_spread is None:
        return float(floor)
    x = min(float(abs_spread), float(cap))
    return _clamp01_floor(((float(cap) - x) / (float(cap) - spread_min))**closeness_curvature, floor=floor)


def uavg(
    team_quality_: float,
    closeness_: float,
    sigma: float = SIGMA,
    relative_quality_multiplier: float = RELATIVE_QUALITY_MULTIPLIER,
) -> float:
    """
    CES utility (Watchability v2) over: Quality, Competitiveness.

    WI_utility = ( q^ρ + c^ρ  )^(1/ρ), where ρ = (σ - 1) / σ.
    Returns a value in ~[0.1, 1].
    """
    q = min(_clamp01_floor(team_quality_, floor=QUALITY_FLOOR), COMPONENT_CAP)
    c = min(_clamp01_floor(closeness_, floor=CLOSENESS_FLOOR), COMPONENT_CAP)

    sigma_f = float(sigma)
    if sigma_f == 0:
        return float(min(q, c))
    rho = (sigma_f - 1.0) / sigma_f
    if rho == 0:
        # Limit case: geometric mean.
        return float((q * c) ** (1.0 / 2.0))

    return float(((relative_quality_multiplier * q**rho + (1.0 - relative_quality_multiplier) * c**rho)) ** (1.0 / rho))


def awi(team_quality_: float, closeness_: float) -> float:
    """
    Watchability Index (WI), scaled to [0,100].
    """
    return 100.0 * uavg(team_quality_, closeness_)


def awi_label(awi_: float) -> str:
    x = float(awi_)
    if x >= 90:
        return "Must Watch"
    if x >= 75:
        return "Strong Watch"
    if x >= 50:
        return "Watchable"
    if x >= 25:
        return "Skippable"
    return "Hard Skip"


@dataclass(frozen=True)
class Watchability:
    team_quality: float
    closeness: float
    uavg: float
    awi: float
    label: str


def compute_watchability(
    w1: float,
    w2: float,
    abs_spread: Optional[float],
    *,
    sigma: float = SIGMA,
) -> Watchability:
    q = team_quality(w1, w2)
    c = closeness(abs_spread)
    u = uavg(q, c, sigma=sigma)
    a = 100.0 * u
    return Watchability(
        team_quality=q,
        closeness=c,
        uavg=u,
        awi=a,
        label=awi_label(a),
    )
