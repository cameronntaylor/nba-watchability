from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
from zoneinfo import ZoneInfo


ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
ESPN_TEAM_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"


def _current_nba_season_year(today: dt.date) -> int:
    return today.year + 1 if today.month >= 7 else today.year


def _cache_dir() -> str:
    return os.getenv("NBA_WATCH_CACHE_DIR", os.path.join(os.getcwd(), ".cache"))


def _cache_path(key: str) -> str:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    d = os.path.join(_cache_dir(), "script_http")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{h}.json")


def _fetch_json_via_curl(url: str, *, ttl_seconds: int = 6 * 60 * 60) -> dict:
    key = url
    path = _cache_path(key)
    now = time.time()
    try:
        cached = json.loads(open(path, "r", encoding="utf-8").read())
        ts = float(cached.get("_ts", 0))
        if now - ts <= float(ttl_seconds):
            return cached.get("data") or {}
    except Exception:
        pass

    proc = subprocess.run(
        ["curl", "-sS", url],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    data = json.loads(proc.stdout)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"_ts": now, "data": data}, f)
    except Exception:
        pass
    return data


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _find_first_number(stats_json, key: str) -> float | None:
    for d in _walk(stats_json):
        if key in d:
            try:
                return float(d[key])
            except Exception:
                pass
        name = d.get("name") if isinstance(d, dict) else None
        if name == key and "value" in d:
            try:
                return float(d["value"])
            except Exception:
                pass
    return None


def _athlete_id_from_espn_athlete(athlete: dict) -> str | None:
    athlete_id = athlete.get("id")
    if athlete_id is not None and str(athlete_id).strip():
        return str(athlete_id).strip()
    links = athlete.get("links")
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, dict):
            continue
        href = str(link.get("href") or "")
        import re
        m = re.search(r"/id/(\d+)", href)
        if not m:
            m = re.search(r"/id/(\d+)(?:/|$)", href)
        if m:
            return str(m.group(1))
    return None


def _fetch_athlete_raw_impact(athlete_id: str, season_year: int) -> float | None:
    base = (
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
        f"seasons/{season_year}/types/2/athletes/{athlete_id}/statistics/0"
    )
    url = base + "?" + urllib.parse.urlencode({"lang": "en", "region": "us"})
    try:
        data = _fetch_json_via_curl(url, ttl_seconds=24 * 60 * 60)
    except Exception:
        return None
    pts = _find_first_number(data, "avgPoints") or 0.0
    ast = _find_first_number(data, "avgAssists") or 0.0
    reb = _find_first_number(data, "avgRebounds") or 0.0
    raw = float(pts) + float(ast) + float(reb)
    return raw if raw > 0 else 0.0


def _infer_from_short_comment(abbr: str, short_comment: str, target_dow: str) -> str | None:
    a = (abbr or "").strip().upper()
    if a != "GTD":
        return None
    sc = (short_comment or "")
    sc_l = sc.lower()
    dow_l = (target_dow or "").strip().lower()
    if not dow_l or dow_l not in sc_l:
        return None
    if "probable" in sc_l:
        return "Probable"
    if "doubtful" in sc_l:
        return "Doubtful"
    if "questionable" in sc_l:
        return "Questionable"
    return None


def main() -> int:
    pt_now = dt.datetime.now(ZoneInfo("America/Los_Angeles"))
    dow = pt_now.strftime("%A")
    season_year = _current_nba_season_year(pt_now.date())

    try:
        data = _fetch_json_via_curl(ESPN_INJURIES_URL, ttl_seconds=10 * 60)
    except Exception as e:
        print(f"Failed to fetch injuries: {e}", file=sys.stderr)
        return 2

    blocks = data.get("injuries") if isinstance(data, dict) else None
    if not isinstance(blocks, list):
        print("No injuries list found.", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for team in blocks:
        if not isinstance(team, dict):
            continue
        team_name = str(team.get("displayName") or "").strip()
        for inj in team.get("injuries") or []:
            if not isinstance(inj, dict):
                continue
            athlete = inj.get("athlete") or {}
            player = str(athlete.get("displayName") or athlete.get("fullName") or "").strip()
            if not player:
                continue

            details = inj.get("details") or {}
            fantasy = details.get("fantasyStatus") if isinstance(details, dict) else None
            abbr = ""
            if isinstance(fantasy, dict):
                abbr = str(fantasy.get("abbreviation") or "").strip().upper()
            if not abbr:
                status = inj.get("status")
                if isinstance(status, str) and status.strip():
                    abbr = status.strip().upper()
            if not abbr:
                continue

            short_comment = str(inj.get("shortComment") or "")
            inferred = _infer_from_short_comment(abbr, short_comment, dow)
            if inferred not in {"Probable", "Doubtful", "Questionable"}:
                continue

            athlete = inj.get("athlete") or {}
            athlete_id = _athlete_id_from_espn_athlete(athlete) or ""
            team_id = str((athlete.get("team") or {}).get("id") or "").strip()
            rows.append(
                {
                    "inferred": inferred,
                    "player": player,
                    "team": team_name,
                    "team_id": team_id,
                    "athlete_id": athlete_id,
                    "abbr": abbr,
                    "shortComment": short_comment,
                }
            )

    # Compute team impact shares for teams involved.
    by_team_id: dict[str, dict[str, float]] = {}
    by_team_sum: dict[str, float] = {}
    team_ids = sorted({r["team_id"] for r in rows if r.get("team_id")})
    for tid in team_ids:
        roster_url = ESPN_TEAM_ROSTER_URL.format(team_id=tid)
        try:
            roster = _fetch_json_via_curl(roster_url, ttl_seconds=24 * 60 * 60)
        except Exception:
            continue
        athletes = roster.get("athletes") if isinstance(roster, dict) else None
        if not isinstance(athletes, list):
            continue
        raw_by_id: dict[str, float] = {}
        for a in athletes:
            if not isinstance(a, dict):
                continue
            aid = str(a.get("id") or "").strip()
            if not aid:
                continue
            raw = _fetch_athlete_raw_impact(aid, season_year)
            if raw is None:
                continue
            raw_by_id[aid] = float(raw)
        total = sum(raw_by_id.values()) or 0.0
        if total <= 0:
            continue
        by_team_id[tid] = raw_by_id
        by_team_sum[tid] = float(total)

    def _weight_for_inferred(s: str) -> float:
        if s == "Probable":
            return 0.1
        if s == "Doubtful":
            return 0.7
        if s == "Questionable":
            return 0.4
        return 0.0

    for r in rows:
        tid = r.get("team_id") or ""
        aid = r.get("athlete_id") or ""
        raw = (by_team_id.get(tid) or {}).get(aid)
        total = by_team_sum.get(tid)
        share = None
        if raw is not None and total:
            share = float(raw) / float(total) if float(total) else None
        r["raw_impact"] = raw
        r["impact_share"] = share
        r["weight"] = _weight_for_inferred(str(r.get("inferred") or ""))

    # Sort: most impactful first (impact_share desc, then raw impact desc).
    rows.sort(
        key=lambda r: (
            r.get("inferred") != "Probable",  # keep probable/questionable/doubtful grouped but still impact-sorted
            -(float(r.get("impact_share") or 0.0)),
            -(float(r.get("raw_impact") or 0.0)),
            str(r.get("team") or ""),
            str(r.get("player") or ""),
        )
    )

    print(f"{dow} (PT) — inferred from ESPN shortComment when fantasyStatus=GTD")
    if not rows:
        print("No Probable/Doubtful players found by this rule.")
        return 0

    for r in rows:
        inferred = r["inferred"]
        player = r["player"]
        team_name = r["team"]
        abbr = r["abbr"]
        short_comment = r["shortComment"]
        w = float(r.get("weight") or 0.0)
        raw = r.get("raw_impact")
        share = r.get("impact_share")
        raw_s = "?" if raw is None else f"{float(raw):.1f}"
        share_s = "?" if share is None else f"{100.0*float(share):.1f}%"
        print(f"- {inferred}: {player} ({team_name}) [{abbr}] weight={w:.1f} impact={raw_s} share={share_s} — {short_comment}")

    print()
    print(
        f"Total: {len(rows)} (Probable: {sum(1 for r in rows if r['inferred']=='Probable')}, "
        f"Questionable: {sum(1 for r in rows if r['inferred']=='Questionable')}, "
        f"Doubtful: {sum(1 for r in rows if r['inferred']=='Doubtful')})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
