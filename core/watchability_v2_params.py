from __future__ import annotations

# Raw player impact = PTS + AST + REB (per game).

# Show "key injuries" only for high share-of-impact players.
KEY_INJURY_IMPACT_SHARE_THRESHOLD = 0.1

# Scales how much injuries affect adjusted quality (health score).
# health = 1 - INJURY_OVERALL_IMPORTANCE_WEIGHT * sum(injury_weight * impact_share)
INJURY_OVERALL_IMPORTANCE_WEIGHT = 0.6

# --- Injury availability weights ---

INJURY_WEIGHT_AVAILABLE = 0.0
INJURY_WEIGHT_QUESTIONABLE = 0.4
INJURY_WEIGHT_DOUBTFUL = 0.7
INJURY_WEIGHT_OUT = 1.0

# --- Star player bump (small additive win% boost) ---

# star_raw = ((PPG + STAR_REB_WEIGHT*REB + STAR_AST_WEIGHT*AST + STL + BLK) / STAR_DENOM)**2
# star_factor = STAR_WINPCT_BUMP * star_raw * (1 - injury_weight(status))
STAR_DENOM = 50.0
STAR_REB_WEIGHT = 0.7
STAR_AST_WEIGHT = 0.7
STAR_WINPCT_BUMP = 0.075

# --- Importance ---

IMPORTANCE_FLOOR = 0.1
IMPORTANCE_CEILING = 1.0

# --- CES aggregation ---

SIGMA = 0.4  # ρ = (σ - 1) / σ
