from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import requests
from dateutil import parser as dtparser

from core.config import ODDS_API_KEY, ODDS_BASE_URL, SPORT_KEY_NBA, DEFAULT_MARKETS, DEFAULT_REGIONS


@dataclass
class GameOdds:
    game_id: str
    commence_time_utc: str
    home_team: str
    away_team: str
    # spread from home team perspective: negative means home favored
    home_spread: Optional[float]
    # Which book/market used (debug/trace)
    spread_source: str


def _safe_float(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def fetch_nba_spreads_today() -> List[GameOdds]:
    """
    Pulls NBA odds/spreads from The Odds API.
    Uses the first available bookmaker market by default and computes a
    simple 'consensus' as the median across books when available.
    """
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY env var is not set.")

    url = f"{ODDS_BASE_URL}/sports/{SPORT_KEY_NBA}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": DEFAULT_REGIONS,
        "markets": DEFAULT_MARKETS,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data: List[Dict[str, Any]] = r.json()

    games: List[GameOdds] = []
    for ev in data:
        game_id = ev.get("id", "")
        home = ev.get("home_team")
        away = ev.get("away_team")
        commence = ev.get("commence_time")  # ISO UTC

        # Collect all spreads for HOME across books
        home_spreads = []
        sources = []

        for book in ev.get("bookmakers", []) or []:
            book_key = book.get("key", "unknown_book")
            for mkt in book.get("markets", []) or []:
                if mkt.get("key") != "spreads":
                    continue
                for outcome in mkt.get("outcomes", []) or []:
                    if outcome.get("name") == home:
                        pt = _safe_float(outcome.get("point"))
                        if pt is not None:
                            home_spreads.append(pt)
                            sources.append(book_key)

        if home_spreads:
            home_spreads_sorted = sorted(home_spreads)
            mid = len(home_spreads_sorted) // 2
            if len(home_spreads_sorted) % 2 == 1:
                consensus = home_spreads_sorted[mid]
            else:
                consensus = 0.5 * (home_spreads_sorted[mid - 1] + home_spreads_sorted[mid])
            src = "median_across_books"
        else:
            consensus = None
            src = "no_spread_found"

        games.append(
            GameOdds(
                game_id=game_id,
                commence_time_utc=commence,
                home_team=home,
                away_team=away,
                home_spread=consensus,
                spread_source=src,
            )
        )

    # Sort by commence time
    games.sort(key=lambda g: dtparser.isoparse(g.commence_time_utc) if g.commence_time_utc else 0)
    return games