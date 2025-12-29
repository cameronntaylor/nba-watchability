from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
import numpy as np

FVariant = Literal["avg", "product", "max", "avg_minus_gap"]

@dataclass
class MetricParams:
    a: float  # spread term weight (typically positive if using (1 - norm(|spread|)))
    b: float  # quality/stakes term weight
    c: float = 0.0  # optional parity penalty weight for |w1-w2| when using avg_minus_gap
    spread_cap: float = 15.0  # cap for normalization

def norm_abs_spread(abs_spread: Optional[float], cap: float) -> float:
    if abs_spread is None:
        return 1.0  # treat unknown spread as "not close" (worst)
    x = min(float(abs_spread), cap)
    return x / cap  # 0 close -> 0, big -> 1

def f_quality(w1: float, w2: float, variant: FVariant, c: float = 0.0) -> float:
    w1 = float(w1); w2 = float(w2)
    if variant == "avg":
        return 0.5 * (w1 + w2)
    if variant == "product":
        return w1 * w2
    if variant == "max":
        return max(w1, w2)
    if variant == "avg_minus_gap":
        return 0.5 * (w1 + w2) - c * abs(w1 - w2)
    raise ValueError(f"Unknown variant: {variant}")

def compute_cis(home_spread: Optional[float], w_home: float, w_away: float, params: MetricParams, variant: FVariant):
    """
    CIS = a*(1 - norm(|spread|)) + b*f(w_home, w_away)
    """
    abs_spread = None if home_spread is None else abs(float(home_spread))
    spread_term = 1.0 - norm_abs_spread(abs_spread, params.spread_cap)
    fval = f_quality(w_home, w_away, variant, c=params.c)
    cis = params.a * spread_term + params.b * fval
    return cis, spread_term, fval, abs_spread