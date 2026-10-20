#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterator, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bluesky_entities import BlueskyEntityResolver, load_espn_player_team_map  # noqa: E402
from core.conversation_mvp import (  # noqa: E402
    MVP_VERSION,
    associate_topics_to_games,
    build_hourly_rows,
    build_topic_report,
    isoformat_z,
    load_captured_posts,
    parse_timestamp,
)
from core.schedule_espn import fetch_games_for_date  # noqa: E402


DEFAULT_INPUT = ROOT / "data" / "conversation" / "bluesky.sqlite"
DEFAULT_OUTPUT = ROOT / "data" / "conversation" / "mvp"


@contextmanager
def materialized_database(input_path: Path) -> Iterator[Path]:
    source = input_path.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Capture backup not found: {source}")
    if source.suffix.casefold() != ".zip":
        yield source
        return

    with zipfile.ZipFile(source) as archive:
        candidates = [name for name in archive.namelist() if Path(name).name == "bluesky.sqlite"]
        if len(candidates) != 1:
            raise ValueError("Backup ZIP must contain exactly one bluesky.sqlite file")
        member = candidates[0]
        with tempfile.TemporaryDirectory(prefix="bluesky-mvp-") as temp_dir:
            database = Path(temp_dir) / "bluesky.sqlite"
            with archive.open(member) as incoming, database.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            yield database


def read_posts(database: Path):
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity check failed: {integrity}")
        rows = connection.execute(
            """
            SELECT uri, author_fingerprint, text, observed_at, is_reply, matched_terms_json
            FROM posts
            WHERE is_relevant = 1 AND deleted_at IS NULL AND text IS NOT NULL
            ORDER BY observed_at
            """
        ).fetchall()
        return load_captured_posts(rows)
    finally:
        connection.close()


def fetch_schedule(as_of, days: int = 4) -> tuple[list[dict[str, Any]], list[str]]:
    games: list[dict[str, Any]] = []
    errors: list[str] = []
    for offset in range(max(0, days)):
        day = as_of.date() + timedelta(days=offset)
        try:
            games.extend(fetch_games_for_date(day, ttl_seconds=60 * 60))
        except Exception as exc:  # network/cache failures should not destroy the local report
            errors.append(f"{day.isoformat()}: {type(exc).__name__}: {exc}")
    return games, errors


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def metric_cell(value: Any, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value}{suffix}"


def render_html(report: dict[str, Any]) -> str:
    associations_by_topic = {row["topic_id"]: row for row in report["game_associations"]}
    topic_rows = []
    for topic in report["topics"][:100]:
        metric_24 = topic["metrics"]["24"]
        metric_6 = topic["metrics"]["6"]
        association = associations_by_topic.get(topic["topic_id"], {})
        game = "—"
        if association.get("game_id"):
            game = f"{association['away_team']} at {association['home_team']}"
        topic_rows.append(
            "<tr>"
            f"<td><strong>{html.escape(topic['title'])}</strong><br><small>{html.escape(topic['category'])}</small></td>"
            f"<td>{metric_cell(metric_24['absolute_count'])}</td>"
            f"<td>{metric_cell(metric_6['absolute_count'])}</td>"
            f"<td>{metric_cell(metric_6['relative_lift'], '×')}</td>"
            f"<td>{metric_cell(metric_24['unique_author_count'])}</td>"
            f"<td>{html.escape(game)}<br><small>{html.escape(str(association.get('decision', '—')))}</small></td>"
            f"<td>{'Review' if association.get('display_candidate') else html.escape(str(association.get('suppression_reason', '—')))}</td>"
            "</tr>"
        )

    top_team_counts = Counter()
    for row in report["team_hourly"]:
        top_team_counts[row["team"]] += row["count"]
    team_rows = "".join(
        f"<tr><td>{html.escape(team.title())}</td><td>{count}</td></tr>"
        for team, count in top_team_counts.most_common(30)
    )
    warning = "This is an exploratory operator report. Production Storyline Heat and ranking are disabled."
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conversation MVP report</title>
<style>
body{{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;margin:0;background:#f5f7fb;color:#18202b}}
main{{max-width:1200px;margin:auto;padding:32px}} h1{{margin-bottom:4px}} .muted,small{{color:#657080}}
.warning{{background:#fff4cf;border:1px solid #ead17b;padding:12px 16px;border-radius:10px;margin:20px 0}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}}
.card,section{{background:white;border:1px solid #e1e5ec;border-radius:12px;padding:18px}} .card strong{{font-size:28px;display:block}}
section{{margin-top:18px;overflow:auto}} table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{text-align:left;border-bottom:1px solid #edf0f4;padding:10px;vertical-align:top}} th{{color:#566273}}
</style></head><body><main>
<h1>Conversation MVP</h1><div class="muted">As of {html.escape(report['as_of'])} · Bluesky capture · {html.escape(report['version'])}</div>
<div class="warning">{warning}</div>
<div class="cards">
  <div class="card"><strong>{report['capture']['active_posts']}</strong><span class="muted">retained posts</span></div>
  <div class="card"><strong>{report['capture']['unique_authors']}</strong><span class="muted">unique pseudonymous authors</span></div>
  <div class="card"><strong>{len(report['topics'])}</strong><span class="muted">rule-consolidated topics</span></div>
  <div class="card"><strong>{sum(bool(row.get('display_candidate')) for row in report['game_associations'])}</strong><span class="muted">game candidates to review</span></div>
</div>
<section><h2>Topic candidates</h2><table><thead><tr><th>Topic</th><th>24h</th><th>6h</th><th>6h lift</th><th>24h authors</th><th>Candidate game</th><th>Status</th></tr></thead><tbody>{''.join(topic_rows)}</tbody></table></section>
<section><h2>Team conversation in full capture</h2><table><thead><tr><th>Team</th><th>Attributed posts</th></tr></thead><tbody>{team_rows}</tbody></table></section>
<p class="muted">Open the CSV files beside this report for hourly detail. Representative public post text is retained only in the local JSON report.</p>
</main></body></html>"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only conversation MVP report from a Bluesky SQLite database or backup ZIP."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="bluesky.sqlite or backup ZIP")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--as-of",
        help="ISO timestamp; defaults to the newest retained post so a stopped capture remains inspectable.",
    )
    parser.add_argument("--offline", action="store_true", help="Skip live ESPN rosters and schedules")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with materialized_database(input_path) as database:
        posts = read_posts(database)
    if not posts:
        raise SystemExit("The backup is valid but contains no active relevant posts.")
    as_of = parse_timestamp(args.as_of) if args.as_of else max(post.observed_at for post in posts)

    roster_errors: list[str] = []
    player_teams: dict[str, str] = {}
    teams_loaded: Sequence[str] = ()
    if not args.offline:
        try:
            roster = load_espn_player_team_map(roster_ttl_seconds=24 * 60 * 60)
            player_teams = roster.player_teams
            teams_loaded = roster.teams_loaded
            roster_errors.extend(roster.teams_failed)
        except Exception as exc:
            roster_errors.append(f"{type(exc).__name__}: {exc}")
    resolver = BlueskyEntityResolver(player_teams)
    topics = build_topic_report(posts, resolver, as_of=as_of)
    topic_hourly, team_hourly = build_hourly_rows(posts, resolver)
    games, schedule_errors = ([], []) if args.offline else fetch_schedule(as_of)
    associations = associate_topics_to_games(topics, games, as_of=as_of)

    report = {
        "version": MVP_VERSION,
        "as_of": isoformat_z(as_of),
        "coverage_state": "partial",
        "production_scoring_enabled": False,
        "source_backup": str(input_path.resolve()),
        "capture": {
            "first_retained_post_at": isoformat_z(min(post.observed_at for post in posts)),
            "last_retained_post_at": isoformat_z(max(post.observed_at for post in posts)),
            "active_posts": len(posts),
            "unique_authors": len({post.author_fingerprint for post in posts}),
            "replies": sum(post.is_reply for post in posts),
        },
        "roster": {
            "player_count": len(player_teams),
            "teams_loaded": len(teams_loaded),
            "errors": roster_errors,
        },
        "schedule": {"game_count": len(games), "errors": schedule_errors},
        "topics": topics,
        "game_associations": associations,
        "topic_hourly": topic_hourly,
        "team_hourly": team_hourly,
    }
    (output_dir / "conversation_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / "conversation_report.html").write_text(render_html(report), encoding="utf-8")

    topic_csv_rows = []
    for topic in topics:
        row = {
            "topic_id": topic["topic_id"],
            "title": topic["title"],
            "category": topic["category"],
            "teams": " | ".join(topic["teams"]),
            "players": " | ".join(topic["players"]),
            "total_captured_count": topic["total_captured_count"],
        }
        for hours in (1, 6, 24):
            metric = topic["metrics"][str(hours)]
            row[f"count_{hours}h"] = metric["absolute_count"]
            row[f"lift_{hours}h"] = metric["relative_lift"]
            row[f"unique_authors_{hours}h"] = metric["unique_author_count"]
        topic_csv_rows.append(row)
    topic_fields = [
        "topic_id", "title", "category", "teams", "players", "total_captured_count",
        "count_1h", "lift_1h", "unique_authors_1h",
        "count_6h", "lift_6h", "unique_authors_6h",
        "count_24h", "lift_24h", "unique_authors_24h",
    ]
    write_csv(output_dir / "topics.csv", topic_csv_rows, topic_fields)
    write_csv(output_dir / "topic_counts_by_hour.csv", topic_hourly, ("hour_utc", "topic_id", "title", "count"))
    write_csv(output_dir / "team_counts_by_hour.csv", team_hourly, ("hour_utc", "team", "team_abbreviation", "count"))
    write_csv(
        output_dir / "game_associations.csv",
        associations,
        (
            "topic_id", "game_id", "start_time_utc", "away_team", "home_team", "decision",
            "association_confidence", "display_candidate", "production_display_eligible",
            "suppression_reason", "why_this_game",
        ),
    )

    print(f"Analyzed {len(posts)} retained posts into {len(topics)} topic candidates.")
    print(f"HTML report: {output_dir / 'conversation_report.html'}")
    print(f"Machine-readable report: {output_dir / 'conversation_report.json'}")


if __name__ == "__main__":
    main()
