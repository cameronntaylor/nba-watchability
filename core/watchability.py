from __future__ import annotations

from dataclasses import dataclass
from typing import Optional



QUALITY_MULTIPLIER = 1
CLOSENESS_MULTIPLIER = 1
MAX_EXPECTED_WIN_PCT = (1.0)**QUALITY_MULTIPLIER
SPREAD_CAP = 12.0
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
    closeness_: float
    ) -> float:
    """
    Average Cobb-Douglas utility over three preference mixes.
    Uavg = 1/3 * q^0.5 * c^0.5 + 1/3 * q^0.25 * c^0.75 + 1/3 * q^0.75 * c^0.25
    """
    q = _clamp01_floor(team_quality_, floor=QUALITY_FLOOR)
    c = _clamp01_floor(closeness_, floor=CLOSENESS_FLOOR)
    return (q**0.5 * c**0.5 + q**0.25 * c**0.75 + q**0.75 * c**0.25) / 3.0


def awi(team_quality_: float, closeness_: float) -> float:
    """
    Average Watchability Index (aWI), scaled to [0,100].
    aWI = 100 * (Uavg - 0) / (1 - 0) = 100 * Uavg
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
    return "Crap game"


@dataclass(frozen=True)
class Watchability:
    team_quality: float
    closeness: float
    uavg: float
    awi: float
    label: str


def compute_watchability(w1: float, w2: float, abs_spread: Optional[float]) -> Watchability:
    q = team_quality(w1, w2)
    c = closeness(abs_spread)
    u = uavg(q, c)
    a = 100.0 * u
    return Watchability(team_quality=q, closeness=c, uavg=u, awi=a, label=awi_label(a))
