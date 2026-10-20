from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from core.bluesky_entities import BlueskyEntityResolver, ResolvedEntities, normalize_entity_name
from core.team_meta import TEAM_ABBR, normalize_team_name


MVP_VERSION = "conversation-mvp-v1"
WINDOW_HOURS = (1, 6, 24)
MIN_BASELINE_WINDOWS = 7
SMOOTHING_CONSTANT = 5.0

RANK_INELIGIBLE_CATEGORIES = {"off_court_controversy", "generic_debate", "other"}

_CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "off_court_controversy",
        (
            "arrest",
            "lawsuit",
            "legal case",
            "sports betting",
            "gambling investigation",
            "indicted",
            "suspended for betting",
        ),
    ),
    (
        "generic_debate",
        (
            "who is better",
            "better player",
            "goat debate",
            "all time ranking",
            "overrated",
            "underrated",
        ),
    ),
    (
        "record_or_milestone_achieved",
        (
            "broke the record",
            "breaks the record",
            "new record",
            "passed the record",
            "passes the record",
            "reached the milestone",
            "sets the record",
        ),
    ),
    (
        "return_or_debut",
        (
            "return tonight",
            "returns tonight",
            "expected to return",
            "set to return",
            "return",
            "returns",
            "returning",
            "season debut",
            "team debut",
            "nba debut",
            "debut",
            "make his debut",
            "make her debut",
            "comeback",
        ),
    ),
    (
        "record_or_milestone_chase",
        (
            "record chase",
            "milestone chase",
            "on the verge",
            "away from the record",
            "away from a record",
            "close to the record",
            "career record",
            "scoring record",
            "three point record",
            "3 point record",
            "record",
            "milestone",
        ),
    ),
    (
        "injury_or_availability",
        (
            "injury",
            "injured",
            "questionable",
            "probable",
            "game time decision",
            "game-time decision",
            "ruled out",
            "available tonight",
            "minutes restriction",
        ),
    ),
    (
        "role_or_roster_change",
        (
            "traded",
            "trade debut",
            "new team",
            "new starter",
            "starting lineup",
            "coming off the bench",
            "signed with",
        ),
    ),
    (
        "streak_or_historic_performance",
        (
            "winning streak",
            "win streak",
            "scoring streak",
            "historic performance",
            "career high",
            "career-high",
            "franchise record",
        ),
    ),
    (
        "matchup_or_rivalry",
        ("rivalry", "rivals", "rematch", "matchup", " versus ", " vs "),
    ),
)

_CATEGORY_LABELS = {
    "return_or_debut": "return or debut",
    "record_or_milestone_chase": "record or milestone chase",
    "record_or_milestone_achieved": "record or milestone",
    "matchup_or_rivalry": "matchup",
    "streak_or_historic_performance": "streak or historic performance",
    "role_or_roster_change": "role or roster change",
    "injury_or_availability": "availability",
    "off_court_controversy": "off-court discussion",
    "generic_debate": "debate",
    "other": "conversation",
}


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class CapturedPost:
    uri: str
    author_fingerprint: str
    text: str
    observed_at: datetime
    is_reply: bool
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class TopicMatch:
    topic_key: str
    topic_id: str
    title: str
    category: str
    teams: tuple[str, ...]
    players: tuple[str, ...]


def _contains_phrase(text: str, phrase: str) -> bool:
    needle = phrase.strip()
    if " " not in needle:
        return needle in text.split()
    return f" {needle} " in f" {text.strip()} "


def classify_category(text: str, resolved: ResolvedEntities) -> str:
    normalized = normalize_entity_name(text)
    for category, phrases in _CATEGORY_PATTERNS:
        if any(_contains_phrase(normalized, phrase) for phrase in phrases):
            return category
    if len(resolved.teams) >= 2:
        return "matchup_or_rivalry"
    return "other"


def _topic_subjects(resolved: ResolvedEntities, category: str) -> tuple[str, ...]:
    if category == "matchup_or_rivalry" and len(resolved.teams) >= 2:
        return tuple(f"team:{team}" for team in resolved.teams[:2])
    if resolved.players:
        return tuple(f"player:{player}" for player in resolved.players[:2])
    if resolved.teams:
        return tuple(f"team:{team}" for team in resolved.teams[:2])
    return ("league:nba",)


def _display_name(value: str) -> str:
    display = " ".join(part.capitalize() for part in value.split())
    return display.replace("Lebron", "LeBron")


def _topic_title(category: str, resolved: ResolvedEntities) -> str:
    label = _CATEGORY_LABELS[category]
    if category == "matchup_or_rivalry" and len(resolved.teams) >= 2:
        teams = [_display_name(team) for team in resolved.teams[:2]]
        return f"{teams[0]} vs. {teams[1]} {label}"
    if resolved.players:
        subject = " & ".join(_display_name(player) for player in resolved.players[:2])
    elif resolved.teams:
        subject = " & ".join(_display_name(team) for team in resolved.teams[:2])
    else:
        subject = "NBA"
    return f"{subject}: {label}"


def match_post_to_topic(post: CapturedPost, resolver: BlueskyEntityResolver) -> TopicMatch:
    resolved = resolver.resolve(post.matched_terms, text=post.text)
    category = classify_category(post.text, resolved)
    subjects = _topic_subjects(resolved, category)
    topic_key = "|".join((category, *subjects))
    topic_id = "bsky-" + hashlib.sha256(topic_key.encode("utf-8")).hexdigest()[:16]
    return TopicMatch(
        topic_key=topic_key,
        topic_id=topic_id,
        title=_topic_title(category, resolved),
        category=category,
        teams=resolved.teams,
        players=resolved.players,
    )


def _count_in_window(posts: Sequence[CapturedPost], start: datetime, end: datetime) -> int:
    return sum(start <= post.observed_at < end for post in posts)


def _metric_for_window(
    posts: Sequence[CapturedPost],
    *,
    as_of: datetime,
    capture_start: datetime,
    window_hours: int,
) -> dict[str, Any]:
    duration = timedelta(hours=window_hours)
    window_start = as_of - duration
    current = [post for post in posts if window_start <= post.observed_at <= as_of]

    prior_counts: list[int] = []
    prior_end = window_start
    while prior_end - duration >= capture_start:
        prior_start = prior_end - duration
        prior_counts.append(_count_in_window(posts, prior_start, prior_end))
        prior_end = prior_start

    baseline_eligible = len(prior_counts) >= MIN_BASELINE_WINDOWS
    expected = statistics.median(prior_counts) if baseline_eligible else None
    relative_lift = (
        (len(current) + SMOOTHING_CONSTANT) / (expected + SMOOTHING_CONSTANT)
        if expected is not None
        else None
    )
    authors = Counter(post.author_fingerprint for post in current)
    top_author_share = max(authors.values()) / len(current) if current else 0.0
    return {
        "window_hours": window_hours,
        "window_start": isoformat_z(window_start),
        "window_end": isoformat_z(as_of),
        "absolute_count": len(current),
        "original_post_count": sum(not post.is_reply for post in current),
        "reply_count": sum(post.is_reply for post in current),
        "unique_author_count": len(authors),
        "top_author_share": round(top_author_share, 4),
        "baseline_type": "exploratory_topic_history" if baseline_eligible else None,
        "baseline_sample_count": len(prior_counts),
        "expected_count": round(float(expected), 3) if expected is not None else None,
        "relative_lift": round(relative_lift, 3) if relative_lift is not None else None,
        "log2_lift": round(math.log2(relative_lift), 3) if relative_lift else None,
        "production_baseline_eligible": False,
    }


def _percentile(value: float, cohort: Sequence[float]) -> float:
    if not cohort:
        return 0.0
    at_or_below = sum(candidate <= value for candidate in cohort)
    return round(100.0 * at_or_below / len(cohort), 1)


def build_topic_report(
    posts: Sequence[CapturedPost],
    resolver: BlueskyEntityResolver,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    if not posts:
        return []
    as_of = parse_timestamp(as_of or max(post.observed_at for post in posts))
    capture_start = min(post.observed_at for post in posts)
    grouped: dict[str, list[CapturedPost]] = defaultdict(list)
    definitions: dict[str, TopicMatch] = {}
    for post in posts:
        match = match_post_to_topic(post, resolver)
        grouped[match.topic_id].append(post)
        definitions[match.topic_id] = match

    topics: list[dict[str, Any]] = []
    for topic_id, topic_posts in grouped.items():
        definition = definitions[topic_id]
        metrics = {
            str(hours): _metric_for_window(
                topic_posts,
                as_of=as_of,
                capture_start=capture_start,
                window_hours=hours,
            )
            for hours in WINDOW_HOURS
        }
        latest_examples = sorted(topic_posts, key=lambda post: post.observed_at, reverse=True)[:3]
        topics.append(
            {
                "topic_id": topic_id,
                "topic_key": definition.topic_key,
                "title": definition.title,
                "category": definition.category,
                "teams": list(definition.teams),
                "players": list(definition.players),
                "total_captured_count": len(topic_posts),
                "metrics": metrics,
                "rank_category_eligible": definition.category not in RANK_INELIGIBLE_CATEGORIES,
                "representative_posts": [
                    {
                        "observed_at": isoformat_z(post.observed_at),
                        "text": post.text,
                        "uri": post.uri,
                    }
                    for post in latest_examples
                ],
            }
        )

    for hours in WINDOW_HOURS:
        absolute_cohort = [topic["metrics"][str(hours)]["absolute_count"] for topic in topics]
        relative_cohort = [
            topic["metrics"][str(hours)]["relative_lift"]
            for topic in topics
            if topic["metrics"][str(hours)]["relative_lift"] is not None
        ]
        for topic in topics:
            metric = topic["metrics"][str(hours)]
            metric["absolute_percentile"] = _percentile(
                metric["absolute_count"], absolute_cohort
            )
            lift = metric["relative_lift"]
            metric["relative_percentile"] = (
                _percentile(lift, relative_cohort) if lift is not None else None
            )
            if lift is None:
                metric["exploratory_storyline_heat"] = None
            else:
                author_quality = 1.0 - metric["top_author_share"]
                heat = 100.0 * (
                    (metric["absolute_percentile"] / 100.0) ** 0.60
                    * (metric["relative_percentile"] / 100.0) ** 0.40
                    * max(0.25, author_quality)
                )
                metric["exploratory_storyline_heat"] = round(heat, 1)
            metric["production_storyline_heat"] = None

    return sorted(
        topics,
        key=lambda topic: (
            -topic["metrics"]["24"]["absolute_count"],
            -topic["metrics"]["6"]["absolute_count"],
            topic["title"],
        ),
    )


def build_hourly_rows(
    posts: Sequence[CapturedPost], resolver: BlueskyEntityResolver
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    topic_counts: Counter[tuple[str, str]] = Counter()
    team_counts: Counter[tuple[str, str]] = Counter()
    topic_titles: dict[str, str] = {}
    for post in posts:
        match = match_post_to_topic(post, resolver)
        hour = post.observed_at.replace(minute=0, second=0, microsecond=0)
        hour_label = isoformat_z(hour)
        topic_counts[(hour_label, match.topic_id)] += 1
        topic_titles[match.topic_id] = match.title
        for team in match.teams:
            team_counts[(hour_label, team)] += 1
    topic_rows = [
        {"hour_utc": hour, "topic_id": topic_id, "title": topic_titles[topic_id], "count": count}
        for (hour, topic_id), count in sorted(topic_counts.items())
    ]
    team_rows = [
        {
            "hour_utc": hour,
            "team": team,
            "team_abbreviation": TEAM_ABBR.get(team, ""),
            "count": count,
        }
        for (hour, team), count in sorted(team_counts.items())
    ]
    return topic_rows, team_rows


def associate_topics_to_games(
    topics: Sequence[Mapping[str, Any]],
    games: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime,
) -> list[dict[str, Any]]:
    as_of = parse_timestamp(as_of)
    normalized_games: list[dict[str, Any]] = []
    for raw_game in games:
        try:
            start_time = parse_timestamp(str(raw_game["start_time_utc"]))
        except (KeyError, TypeError, ValueError):
            continue
        if start_time < as_of - timedelta(hours=6) or start_time > as_of + timedelta(hours=72):
            continue
        game = dict(raw_game)
        game["start_time"] = start_time
        game["home_team_normalized"] = normalize_team_name(str(raw_game.get("home_team", "")))
        game["away_team_normalized"] = normalize_team_name(str(raw_game.get("away_team", "")))
        normalized_games.append(game)
    normalized_games.sort(key=lambda game: game["start_time"])

    associations: list[dict[str, Any]] = []
    for topic in topics:
        category = str(topic["category"])
        topic_teams = {normalize_team_name(team) for team in topic.get("teams", [])}
        if category in RANK_INELIGIBLE_CATEGORIES:
            associations.append(
                {
                    "topic_id": topic["topic_id"],
                    "game_id": None,
                    "decision": "ineligible" if category == "off_court_controversy" else "not_game_specific",
                    "association_confidence": 1.0,
                    "display_candidate": False,
                    "production_display_eligible": False,
                    "suppression_reason": "category_not_game_specific",
                    "why_this_game": None,
                }
            )
            continue

        exact_match = None
        if len(topic_teams) >= 2:
            for game in normalized_games:
                participants = {game["home_team_normalized"], game["away_team_normalized"]}
                if topic_teams.issubset(participants):
                    exact_match = game
                    break
        if exact_match is not None:
            candidate = exact_match
            decision = "direct"
            confidence = 0.90
            explanation = f"The discussion names both teams in this scheduled matchup."
        elif len(topic_teams) == 1:
            team = next(iter(topic_teams))
            candidate = next(
                (
                    game
                    for game in normalized_games
                    if team in {game["home_team_normalized"], game["away_team_normalized"]}
                ),
                None,
            )
            if category == "record_or_milestone_chase":
                decision, confidence = "milestone_chase", 0.82
                explanation = "The named player or team can continue the milestone chase in its next game."
            elif category == "return_or_debut":
                decision, confidence = "next_game_resolution", 0.78
                explanation = "The named player's return or debut could occur in the team's next game."
            elif category == "injury_or_availability":
                decision, confidence = "next_game_resolution", 0.65
                explanation = "The availability discussion may affect the team's next game, but status needs verification."
            else:
                decision, confidence = "team_story", 0.72
                explanation = "The on-court team story could continue in the team's next game."
        else:
            candidate = None
            decision, confidence = "not_game_specific", 0.95
            explanation = None

        display_candidate = candidate is not None and confidence >= 0.80
        associations.append(
            {
                "topic_id": topic["topic_id"],
                "game_id": str(candidate.get("game_id")) if candidate else None,
                "start_time_utc": isoformat_z(candidate["start_time"]) if candidate else None,
                "home_team": candidate.get("home_team") if candidate else None,
                "away_team": candidate.get("away_team") if candidate else None,
                "decision": decision,
                "association_confidence": confidence,
                "display_candidate": display_candidate,
                "production_display_eligible": False,
                "suppression_reason": (
                    "operator_review_and_production_baseline_required"
                    if display_candidate
                    else "association_confidence_below_display_threshold"
                    if candidate is not None
                    else "no_game_candidate"
                ),
                "why_this_game": explanation,
            }
        )
    return associations


def load_captured_posts(rows: Iterable[Mapping[str, Any]]) -> list[CapturedPost]:
    posts: list[CapturedPost] = []
    for row in rows:
        try:
            matched = json.loads(row["matched_terms_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            matched = []
        posts.append(
            CapturedPost(
                uri=str(row["uri"]),
                author_fingerprint=str(row["author_fingerprint"]),
                text=str(row["text"] or ""),
                observed_at=parse_timestamp(str(row["observed_at"])),
                is_reply=bool(row["is_reply"]),
                matched_terms=tuple(str(term) for term in matched if isinstance(term, str)),
            )
        )
    return posts
