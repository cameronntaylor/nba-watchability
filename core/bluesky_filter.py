from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(normalized.split())


def _term_pattern(term: str) -> re.Pattern[str]:
    normalized = normalize_text(term)
    escaped = re.escape(normalized).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class MatchResult:
    relevant: bool
    matched_terms: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    vocabulary_version: int = 1


class NbaTermMatcher:
    """High-recall first-pass filter for public Bluesky post records."""

    def __init__(
        self,
        *,
        direct_terms: Sequence[str],
        contextual_terms: Sequence[str],
        basketball_context_terms: Sequence[str],
        storyline_terms: Sequence[str],
        version: int = 1,
    ) -> None:
        self.version = int(version)
        self._direct = self._compile(direct_terms)
        self._contextual = self._compile(contextual_terms)
        self._basketball_context = self._compile(basketball_context_terms)
        self._storyline = self._compile(storyline_terms)

    @staticmethod
    def _compile(terms: Iterable[str]) -> tuple[tuple[str, re.Pattern[str]], ...]:
        unique = sorted({normalize_text(term) for term in terms if normalize_text(term)})
        return tuple((term, _term_pattern(term)) for term in unique)

    @classmethod
    def from_mapping(cls, config: Mapping[str, object]) -> "NbaTermMatcher":
        def terms(key: str) -> list[str]:
            value = config.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{key} must be a list of strings")
            return value

        return cls(
            direct_terms=terms("direct_terms"),
            contextual_terms=terms("contextual_terms"),
            basketball_context_terms=terms("basketball_context_terms"),
            storyline_terms=terms("storyline_terms"),
            version=int(config.get("version", 1)),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "NbaTermMatcher":
        with Path(path).open("r", encoding="utf-8") as stream:
            config = json.load(stream)
        if not isinstance(config, dict):
            raise ValueError("Bluesky term configuration must be a JSON object")
        return cls.from_mapping(config)

    @staticmethod
    def _matches(
        patterns: tuple[tuple[str, re.Pattern[str]], ...], text: str
    ) -> tuple[str, ...]:
        return tuple(term for term, pattern in patterns if pattern.search(text))

    def match(self, text: str) -> MatchResult:
        normalized = normalize_text(text)
        if not normalized:
            return MatchResult(False, vocabulary_version=self.version)

        direct = self._matches(self._direct, normalized)
        contextual = self._matches(self._contextual, normalized)
        basketball_context = self._matches(self._basketball_context, normalized)
        storyline = self._matches(self._storyline, normalized)

        matched_terms = tuple(dict.fromkeys(direct + contextual + basketball_context + storyline))
        reasons: list[str] = []
        if direct:
            reasons.append("direct_nba_entity")
        if contextual and basketball_context:
            reasons.append("contextual_entity_with_basketball_signal")

        return MatchResult(
            relevant=bool(reasons),
            matched_terms=matched_terms if reasons else (),
            reasons=tuple(reasons),
            vocabulary_version=self.version,
        )
