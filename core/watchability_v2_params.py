from __future__ import annotations

# --- Player tiering (impact) ---

TIER1_RELATIVE_IMPACT_THRESHOLD = 0.90
TIER2_RELATIVE_IMPACT_THRESHOLD = 0.75

TIER1_WEIGHT = 0.10
TIER2_WEIGHT = 0.05

# Raw player impact = PTS + AST + REB (per game).

# --- Injury availability weights ---

INJURY_WEIGHT_AVAILABLE = 0.0
INJURY_WEIGHT_QUESTIONABLE = 0.4
INJURY_WEIGHT_DOUBTFUL = 0.7
INJURY_WEIGHT_OUT = 1.0

# --- Importance ---

IMPORTANCE_FLOOR = 0.1
IMPORTANCE_CEILING = 1.0

# --- CES aggregation ---

SIGMA = 0.8  # ρ = (σ - 1) / σ

