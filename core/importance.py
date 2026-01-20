from __future__ import annotations

from typing import Dict, Optional

from core.watchability_v2_params import IMPORTANCE_CEILING, IMPORTANCE_FLOOR


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(x)))


def compute_importance_map(detail_map: Dict[str, dict]) -> Dict[str, float]:
    """
    Computes per-team importance from standings data.

    detail_map is expected to be keyed by normalized team name, with fields:
      - games_behind: float|None
      - playoff_seed: int|None   (conference seed)
      - conference: 'east'|'west'|None
    """
    by_conf: Dict[str, Dict[int, tuple[str, float]]] = {"east": {}, "west": {}}

    for team, d in detail_map.items():
        conf = d.get("conference")
        seed = d.get("playoff_seed")
        gb = d.get("games_behind")
        if conf not in by_conf:
            continue
        if seed is None or gb is None:
            continue
        try:
            by_conf[str(conf)][int(seed)] = (team, float(gb))
        except Exception:
            continue

    out: Dict[str, float] = {}
    for conf, seed_map in by_conf.items():
        if not seed_map:
            continue

        seed6 = seed_map.get(6)
        seed10 = seed_map.get(10)

        for seed, (team, gb) in seed_map.items():
            gb_prev = seed_map.get(seed - 1, (None, None))[1] if (seed - 1) in seed_map else None
            gb_next = seed_map.get(seed + 1, (None, None))[1] if (seed + 1) in seed_map else None

            seed_radius = _min_abs_delta(gb, gb_prev, gb_next)
            playoff_radius = _min_abs_delta(
                gb,
                seed6[1] if seed6 else None,
                seed10[1] if seed10 else None,
            )

            if seed_radius is None or playoff_radius is None:
                out[team] = float(IMPORTANCE_FLOOR)
                continue

            total_radius = max(0.0, float(seed_radius) + float(playoff_radius))
            importance = (10.0 - total_radius) / 10.0
            out[team] = _clamp(importance, IMPORTANCE_FLOOR, IMPORTANCE_CEILING)

    # Anything missing defaults to the floor.
    for team in detail_map.keys():
        out.setdefault(team, float(IMPORTANCE_FLOOR))

    return out


def _min_abs_delta(gb: float, a: Optional[float], b: Optional[float]) -> Optional[float]:
    deltas = []
    if a is not None:
        deltas.append(abs(float(a) - float(gb)))
    if b is not None:
        deltas.append(abs(float(b) - float(gb)))
    if not deltas:
        return None
    return min(deltas)


def compute_importance_detail_map(detail_map: Dict[str, dict]) -> Dict[str, dict]:
    """
    Returns per-team detail:
      { team: { 'importance': float, 'seed_radius': float|None, 'playoff_radius': float|None } }
    """
    by_conf: Dict[str, Dict[int, tuple[str, float]]] = {"east": {}, "west": {}}

    for team, d in detail_map.items():
        conf = d.get("conference")
        seed = d.get("playoff_seed")
        gb = d.get("games_behind")
        if conf not in by_conf:
            continue
        if seed is None or gb is None:
            continue
        try:
            by_conf[str(conf)][int(seed)] = (team, float(gb))
        except Exception:
            continue

    out: Dict[str, dict] = {}
    for conf, seed_map in by_conf.items():
        if not seed_map:
            continue

        seed6 = seed_map.get(6)
        seed10 = seed_map.get(10)

        for seed, (team, gb) in seed_map.items():
            gb_prev = seed_map.get(seed - 1, (None, None))[1] if (seed - 1) in seed_map else None
            gb_next = seed_map.get(seed + 1, (None, None))[1] if (seed + 1) in seed_map else None

            seed_radius = _min_abs_delta(gb, gb_prev, gb_next)
            playoff_radius = _min_abs_delta(
                gb,
                seed6[1] if seed6 else None,
                seed10[1] if seed10 else None,
            )

            if seed_radius is None or playoff_radius is None:
                importance = float(IMPORTANCE_FLOOR)
            else:
                total_radius = max(0.0, float(seed_radius) + float(playoff_radius))
                importance = _clamp((10.0 - total_radius) / 10.0, IMPORTANCE_FLOOR, IMPORTANCE_CEILING)

            out[team] = {
                "importance": float(importance),
                "seed_radius": None if seed_radius is None else float(seed_radius),
                "playoff_radius": None if playoff_radius is None else float(playoff_radius),
            }

    for team in detail_map.keys():
        out.setdefault(
            team,
            {"importance": float(IMPORTANCE_FLOOR), "seed_radius": None, "playoff_radius": None},
        )

    return out
