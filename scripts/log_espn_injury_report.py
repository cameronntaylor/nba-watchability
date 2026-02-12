#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dateutil import tz

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


ESPN_LEAGUE_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _pt_now(tz_name: str) -> dt.datetime:
    return _utc_now().astimezone(tz.gettz(tz_name))


def _should_run_now_pt(now_pt: dt.datetime, hours: set[int]) -> bool:
    return now_pt.minute == 0 and now_pt.hour in hours


def _get_json_with_retry(url: str, *, retries: int = 3, timeout_seconds: int = 30) -> dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout_seconds)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object at top-level.")
            return data
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(2.0 * attempt)
                continue
            raise
    raise RuntimeError("Unreachable") from last_err


def _athlete_id_from_links(athlete: dict[str, Any]) -> str:
    athlete_id = athlete.get("id")
    if athlete_id is not None and str(athlete_id).strip():
        return str(athlete_id).strip()
    links = athlete.get("links")
    if not isinstance(links, list):
        return ""
    for link in links:
        if not isinstance(link, dict):
            continue
        href = str(link.get("href") or "")
        if "/id/" not in href:
            continue
        import re

        m = re.search(r"/id/(\d+)", href)
        if m:
            return str(m.group(1))
    return ""


def _fantasy_abbr(inj: dict[str, Any]) -> str:
    details = inj.get("details")
    if isinstance(details, dict):
        fantasy = details.get("fantasyStatus")
        if isinstance(fantasy, dict):
            abbr = fantasy.get("abbreviation")
            if isinstance(abbr, str) and abbr.strip():
                return abbr.strip()
    return ""


def main() -> int:
    p = argparse.ArgumentParser(description="Snapshot ESPN's full NBA league injury report.")
    p.add_argument("--tz", type=str, default="America/Los_Angeles")
    p.add_argument("--hours-pt", type=str, default="10,16,19", help="Comma-separated PT hours to run at.")
    p.add_argument("--force", action="store_true", help="Run regardless of current PT time.")
    p.add_argument("--out-dir", type=str, default=os.path.join(PROJECT_ROOT, "output", "logs", "injury_reports"))
    args = p.parse_args()

    hours = {int(x) for x in str(args.hours_pt).split(",") if str(x).strip()}
    now_pt = _pt_now(str(args.tz))
    if not args.force and not _should_run_now_pt(now_pt, hours):
        print(f"Skipping: now PT is {now_pt.strftime('%Y-%m-%d %H:%M')} (hours={sorted(hours)}).")
        return 0

    data = _get_json_with_retry(ESPN_LEAGUE_INJURIES_URL, retries=3, timeout_seconds=30)

    out_dir = Path(str(args.out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    now_utc = _utc_now()
    date_str = now_utc.strftime("%Y-%m-%d")
    ts_str = now_utc.strftime("%H%M%SZ")
    base = f"injuries_{date_str}_{ts_str}"
    json_path = out_dir / f"{base}.json"
    csv_path = out_dir / f"{base}.csv"

    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # Also emit a flat CSV for quick inspection/diffs.
    blocks = data.get("injuries")
    rows: list[dict[str, str]] = []
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            team = str(block.get("displayName") or block.get("name") or "")
            injuries = block.get("injuries")
            if not isinstance(injuries, list):
                continue
            for inj in injuries:
                if not isinstance(inj, dict):
                    continue
                athlete = inj.get("athlete")
                if not isinstance(athlete, dict):
                    continue
                rows.append(
                    {
                        "time_log_utc": now_utc.isoformat().replace("+00:00", "Z"),
                        "team": team,
                        "athlete_id": _athlete_id_from_links(athlete),
                        "player": str(
                            athlete.get("displayName")
                            or athlete.get("fullName")
                            or athlete.get("shortName")
                            or ""
                        ),
                        "fantasy_abbr": _fantasy_abbr(inj),
                        "status": str(inj.get("status") or ""),
                        "shortComment": str(inj.get("shortComment") or ""),
                        "longComment": str(inj.get("longComment") or ""),
                    }
                )

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "time_log_utc",
                "team",
                "athlete_id",
                "player",
                "fantasy_abbr",
                "status",
                "shortComment",
                "longComment",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote injury report snapshot ({len(rows)} rows):")
    print(f"- {json_path}")
    print(f"- {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

