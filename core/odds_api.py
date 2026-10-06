from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import datetime as dt
import requests
from dateutil import parser as dtparser

from core.config import (
    DEFAULT_MARKETS,
    DEFAULT_REGIONS,
    ODDS_API_KEY,
    ODDS_BASE_URL,
    SPORT_KEY_NBA,
    SPORT_KEY_NBA_PRESEASON,
)
from core.http_cache import get_json_cached
from core.season_strategy import is_preseason_date


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


def _sport_key_for_date(value: dt.date) -> str:
    return SPORT_KEY_NBA_PRESEASON if is_preseason_date(value) else SPORT_KEY_NBA


def _sport_keys_for_window(start_utc: dt.datetime, end_utc: dt.datetime) -> list[str]:
    """Return every Odds API competition key touched by the requested window."""
    keys: list[str] = []
    value = start_utc.date()
    while value <= end_utc.date():
        key = _sport_key_for_date(value)
        if key not in keys:
            keys.append(key)
        value += dt.timedelta(days=1)
    return keys


def _parse_games(data: List[Dict[str, Any]], sport_key: str) -> List[GameOdds]:
    games: List[GameOdds] = []
    for ev in data:
        game_id = ev.get("id", "")
        home = ev.get("home_team")
        away = ev.get("away_team")
        commence = ev.get("commence_time")

        home_spreads = []
        for book in ev.get("bookmakers", []) or []:
            for mkt in book.get("markets", []) or []:
                if mkt.get("key") != "spreads":
                    continue
                for outcome in mkt.get("outcomes", []) or []:
                    if outcome.get("name") == home:
                        point = _safe_float(outcome.get("point"))
                        if point is not None:
                            home_spreads.append(point)

        if home_spreads:
            ordered = sorted(home_spreads)
            mid = len(ordered) // 2
            consensus = ordered[mid] if len(ordered) % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])
            source = f"median_across_books:{sport_key}"
        else:
            consensus = None
            source = f"no_spread_found:{sport_key}"

        games.append(
            GameOdds(
                game_id=game_id,
                commence_time_utc=commence,
                home_team=home,
                away_team=away,
                home_spread=consensus,
                spread_source=source,
            )
        )
    return games


def fetch_nba_spreads_today() -> List[GameOdds]:
    """
    Pulls NBA odds/spreads from The Odds API.
    Uses the first available bookmaker market by default and computes a
    simple 'consensus' as the median across books when available.
    """
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY env var is not set.")

    sport_key = _sport_key_for_date(dt.date.today())
    url = f"{ODDS_BASE_URL}/sports/{sport_key}/odds"
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

    games = _parse_games(data, sport_key)

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

    games: List[GameOdds] = []
    errors: list[Exception] = []
    successful_requests = 0
    for sport_key in _sport_keys_for_window(start_utc, end_utc):
        url = f"{ODDS_BASE_URL}/sports/{sport_key}/odds"
        try:
            resp = get_json_cached(
                url,
                params=params_with_window,
                namespace="odds_api",
                cache_key=(
                    f"nba_odds_window:{sport_key}:{days_ahead}:"
                    f"{start_utc.isoformat()}:{end_utc.isoformat()}"
                ),
                ttl_seconds=5 * 60,
                timeout_seconds=20,
            )
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) != 422:
                errors.append(exc)
                continue
            try:
                resp = get_json_cached(
                    url,
                    params=base_params,
                    namespace="odds_api",
                    cache_key=f"nba_odds_unfiltered:{sport_key}",
                    ttl_seconds=5 * 60,
                    timeout_seconds=20,
                )
            except Exception as retry_exc:
                errors.append(retry_exc)
                continue
        except Exception as exc:
            errors.append(exc)
            continue
        successful_requests += 1
        games.extend(_parse_games(resp.data, sport_key))

    if successful_requests == 0 and errors:
        raise errors[0]

    # If we had to fallback (or API returned extra), filter client-side to desired window.
    filtered_by_id: dict[str, GameOdds] = {}
    for g in games:
        if not g.commence_time_utc:
            continue
        try:
            t = dtparser.isoparse(g.commence_time_utc)
        except Exception:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        if start_utc <= t <= end_utc:
            dedupe_key = g.game_id or f"{g.commence_time_utc}|{g.away_team}|{g.home_team}"
            filtered_by_id[dedupe_key] = g

    filtered = list(filtered_by_id.values())
    filtered.sort(key=lambda g: dtparser.isoparse(g.commence_time_utc) if g.commence_time_utc else 0)
    return filtered
