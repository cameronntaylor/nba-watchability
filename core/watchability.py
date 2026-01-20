from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.watchability_v2_params import SIGMA


QUALITY_MULTIPLIER = 1
CLOSENESS_MULTIPLIER = 0.75
MAX_EXPECTED_WIN_PCT = (1.0)**QUALITY_MULTIPLIER
SPREAD_CAP = 15
WIN_MAX = 0.8
WIN_MIN = 0.2

QUALITY_FLOOR = 0.1
CLOSENESS_FLOOR = 0.1


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def _clamp01_floor(x: float, floor: float) -> float:
    return max(float(floor), min(1.0, float(x)))


def team_quality(
    w1: float,
    w2: float,
    max_expected: float = MAX_EXPECTED_WIN_PCT,
    floor: float = QUALITY_FLOOR,
    quality_multiplier: float = QUALITY_MULTIPLIER,
    win_max: float = WIN_MAX,
    win_min: float = WIN_MIN,
) -> float:
    """
    Team quality for a matchup, normalized to ~[0,1].
    Defined as: avg(win%) / MAX_EXPECTED_WIN_PCT
    """
    if max_expected <= 0:
        return float(floor)
    avg_wp = 0.5 * (float(w1) + float(w2))
    return _clamp01_floor((avg_wp - win_min) / (win_max - win_min), floor=floor)


def closeness(
    abs_spread: Optional[float],
    cap: float = SPREAD_CAP,
    floor: float = CLOSENESS_FLOOR,
    closeness_multiplier: float = CLOSENESS_MULTIPLIER,
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
    return _clamp01_floor(((float(cap) - x) / float(cap))**closeness_multiplier, floor=floor)


def uavg(
    team_quality_: float,
    closeness_: float,
    sigma: float = SIGMA,
) -> float:
    """
    CES utility (Watchability v2) over: Quality, Competitiveness.

    WI_utility = ( (q^ρ + c^ρ) / 2 )^(1/ρ), where ρ = (σ - 1) / σ.
    Returns a value in ~[0.1, 1].
    """
    q = _clamp01_floor(team_quality_, floor=QUALITY_FLOOR)
    c = _clamp01_floor(closeness_, floor=CLOSENESS_FLOOR)

    sigma_f = float(sigma)
    if sigma_f == 0:
        return float(min(q, c))
    rho = (sigma_f - 1.0) / sigma_f
    if rho == 0:
        # Limit case: geometric mean.
        return float((q * c) ** (1.0 / 2.0))

    return float(((q**rho + c**rho) / 2.0) ** (1.0 / rho))


def awi(team_quality_: float, closeness_: float) -> float:
    """
    Watchability Index (WI), scaled to [0,100].
    """
    return 100.0 * uavg(team_quality_, closeness_)


def awi_label(awi_: float) -> str:
    x = float(awi_)
    if x >= 90:
        return "Amazing game"
    if x >= 75:
        return "Great game"
    if x >= 50:
        return "Good game"
    if x >= 25:
        return "Ok game"
    return "Bad game"


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
