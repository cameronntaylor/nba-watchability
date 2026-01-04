from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import datetime as dt
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


def fetch_nba_spreads_window(days_ahead: int = 2) -> List[GameOdds]:
    """
    Pull NBA odds/spreads from The Odds API for a window starting now and extending
    `days_ahead` days into the future. This is useful for weekend slates where games
    span multiple dates.
    """
    days_ahead = max(0, int(days_ahead))
    now_utc = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    # Include recently-started games so in-progress matchups remain visible.
    start_utc = (now_utc - dt.timedelta(hours=6)).replace(microsecond=0)
    end_utc = (now_utc + dt.timedelta(days=days_ahead, hours=23, minutes=59)).replace(microsecond=0)

    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY env var is not set.")

    url = f"{ODDS_BASE_URL}/sports/{SPORT_KEY_NBA}/odds"
    base_params = {
        "apiKey": ODDS_API_KEY,
        "regions": DEFAULT_REGIONS,
        "markets": DEFAULT_MARKETS,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }

    # The Odds API has occasionally rejected commenceTimeFrom/To with 422 depending on plan/API version.
    # Try with the time window first; if rejected, retry without and filter client-side.
    params_with_window = dict(base_params)
    params_with_window["commenceTimeFrom"] = start_utc.isoformat().replace("+00:00", "Z")
    params_with_window["commenceTimeTo"] = end_utc.isoformat().replace("+00:00", "Z")

    r = requests.get(url, params=params_with_window, timeout=20)
    if r.status_code == 422:
        r = requests.get(url, params=base_params, timeout=20)
    r.raise_for_status()
    data: List[Dict[str, Any]] = r.json()

    games: List[GameOdds] = []
    for ev in data:
        game_id = ev.get("id", "")
        home = ev.get("home_team")
        away = ev.get("away_team")
        commence = ev.get("commence_time")  # ISO UTC

        home_spreads = []
        for book in ev.get("bookmakers", []) or []:
            for mkt in book.get("markets", []) or []:
                if mkt.get("key") != "spreads":
                    continue
                for outcome in mkt.get("outcomes", []) or []:
                    if outcome.get("name") == home:
                        pt = _safe_float(outcome.get("point"))
                        if pt is not None:
                            home_spreads.append(pt)

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

        game = (
            GameOdds(
                game_id=game_id,
                commence_time_utc=commence,
                home_team=home,
                away_team=away,
                home_spread=consensus,
                spread_source=src,
            )
        )
        games.append(game)

    # If we had to fallback (or API returned extra), filter client-side to desired window.
    filtered: List[GameOdds] = []
    for g in games:
        if not g.commence_time_utc:
            continue
        try:
            t = dtparser.isoparse(g.commence_time_utc)
        except Exception:
            continue
        if start_utc <= t <= end_utc:
            filtered.append(g)

    filtered.sort(key=lambda g: dtparser.isoparse(g.commence_time_utc) if g.commence_time_utc else 0)
    return filtered
