from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from zoneinfo import ZoneInfo


ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"


def _fetch_json_via_curl(url: str) -> dict:
    proc = subprocess.run(
        ["curl", "-sS", url],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return json.loads(proc.stdout)


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

    try:
        data = _fetch_json_via_curl(ESPN_INJURIES_URL)
    except Exception as e:
        print(f"Failed to fetch injuries: {e}", file=sys.stderr)
        return 2

    blocks = data.get("injuries") if isinstance(data, dict) else None
    if not isinstance(blocks, list):
        print("No injuries list found.", file=sys.stderr)
        return 2

    rows: list[tuple[str, str, str, str, str]] = []
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
            if inferred not in {"Probable", "Doubtful"}:
                continue

            rows.append((inferred, player, team_name, abbr, short_comment))

    rows.sort(key=lambda r: (r[0], r[2], r[1]))

    print(f"{dow} (PT) — inferred from ESPN shortComment when fantasyStatus=GTD")
    if not rows:
        print("No Probable/Doubtful players found by this rule.")
        return 0

    for inferred, player, team_name, abbr, short_comment in rows:
        print(f"- {inferred}: {player} ({team_name}) [{abbr}] — {short_comment}")

    print()
    print(f"Total: {len(rows)} (Probable: {sum(1 for r in rows if r[0]=='Probable')}, Doubtful: {sum(1 for r in rows if r[0]=='Doubtful')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

