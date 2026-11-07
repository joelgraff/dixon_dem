"""Command parsing, alias resolution, and fuzzy noun matching."""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from .scene_card import SceneCard, SceneObject

MAX_INPUT_LENGTH = 40
AUTO_RESOLVE_THRESHOLD = 0.82
CLARIFICATION_FLOOR = 0.55
_LEADING_FILLER = {"a", "an", "at", "the", "to"}


@dataclass(frozen=True)
class Verb:
    name: str
    aliases: tuple[str, ...]
    handler: str


@dataclass(frozen=True)
class NounMatch:
    status: str
    candidates: tuple[SceneObject, ...] = ()


@dataclass(frozen=True)
class ParsedCommand:
    verb: Verb | None
    verb_text: str
    noun_text: str
    noun_match: NounMatch | None


def normalize(text: str) -> str:
    text = text.lower().translate(str.maketrans({char: " " for char in string.punctuation}))
    return " ".join(text.split())


def levenshtein(left: str, right: str) -> int:
    """Return the edit distance using O(min(len(left), len(right))) memory."""
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def load_verbs(path: str | Path) -> tuple[Verb, ...]:
    raw_verbs = json.loads(Path(path).read_text(encoding="utf-8"))
    verbs = tuple(
        Verb(
            name=item["name"].strip().lower(),
            aliases=tuple(
                dict.fromkeys(
                    normalize(alias)
                    for alias in (item["name"], *item["aliases"])
                    if normalize(alias)
                )
            ),
            handler=item["handler"],
        )
        for item in raw_verbs
    )
    if len({verb.name for verb in verbs}) != len(verbs):
        raise ValueError("Verb names must be unique.")
    return verbs


def _object_aliases(objects: Iterable[SceneObject]) -> dict[str, list[SceneObject]]:
    aliases: dict[str, list[SceneObject]] = {}
    for item in objects:
        for alias in item.aliases:
            aliases.setdefault(normalize(alias), []).append(item)
    return aliases


def match_noun(text: str, scene: SceneCard) -> NounMatch:
    query = normalize(text)
    while query and query.split()[0] in _LEADING_FILLER:
        query = " ".join(query.split()[1:])
    if not query:
        return NounMatch("missing")

    aliases = _object_aliases(scene.objects)
    exact = aliases.get(query, [])
    if exact:
        candidates = tuple(dict.fromkeys(exact))
        return NounMatch("ambiguous" if len(candidates) > 1 else "resolved", candidates)

    ranked: list[tuple[float, str, SceneObject]] = []
    for alias, objects in aliases.items():
        distance = levenshtein(query, alias)
        score = 1.0 - distance / max(len(query), len(alias), 1)
        if score >= CLARIFICATION_FLOOR:
            ranked.extend((score, alias, item) for item in objects)
    if not ranked:
        return NounMatch("unknown")

    ranked.sort(key=lambda candidate: (-candidate[0], candidate[1], candidate[2].name))
    best_score = ranked[0][0]
    tied = tuple(
        dict.fromkeys(
            item
            for score, _, item in ranked
            if best_score - score <= 0.06
        )
    )
    if best_score >= AUTO_RESOLVE_THRESHOLD and len(tied) == 1:
        return NounMatch("resolved", (ranked[0][2],))

    suggestions: list[SceneObject] = []
    for score, _, item in ranked:
        if best_score - score > 0.16:
            continue
        if item not in suggestions:
            suggestions.append(item)
        if len(suggestions) == 2:
            break
    return NounMatch("ambiguous", tuple(suggestions))


def _strip_noun_fillers(text: str) -> str:
    words = normalize(text).split()
    while words and words[0] in _LEADING_FILLER:
        words.pop(0)
    return " ".join(words)


def parse_command(text: str, verbs: tuple[Verb, ...], scene: SceneCard) -> ParsedCommand:
    """Parse one SCI-sized command and resolve its noun when the verb needs one."""
    text = text[:MAX_INPUT_LENGTH]
    normalized = normalize(text)
    if not normalized:
        return ParsedCommand(None, "", "", None)

    words = normalized.split()
    matches: list[tuple[int, Verb]] = []
    for verb in verbs:
        for alias in verb.aliases:
            alias_words = alias.split()
            if words[: len(alias_words)] == alias_words:
                matches.append((len(alias_words), verb))
    if matches:
        alias_length, verb = max(matches, key=lambda match: match[0])
        noun_text = _strip_noun_fillers(" ".join(words[alias_length:]))
        noun_match = None if verb.name == "go" or not noun_text else match_noun(noun_text, scene)
        return ParsedCommand(verb, verb.name, noun_text, noun_match)

    first_word = words[0]
    verb_aliases = [
        (alias, verb)
        for verb in verbs
        for alias in verb.aliases
        if " " not in alias
    ]
    ranked_verbs = sorted(
        (
            1.0 - levenshtein(first_word, alias) / max(len(first_word), len(alias), 1),
            alias,
            verb,
        )
        for alias, verb in verb_aliases
    )
    if ranked_verbs and ranked_verbs[-1][0] >= AUTO_RESOLVE_THRESHOLD:
        verb = ranked_verbs[-1][2]
        noun_text = _strip_noun_fillers(" ".join(words[1:]))
        noun_match = None if verb.name == "go" or not noun_text else match_noun(noun_text, scene)
        return ParsedCommand(verb, verb.name, noun_text, noun_match)

    return ParsedCommand(None, words[0], " ".join(words[1:]), None)


def resolve_clarification(
    command: ParsedCommand,
    answer: str,
) -> ParsedCommand | None:
    """Resolve a pending noun ambiguity only when the answer identifies one candidate."""
    if command.noun_match is None or command.noun_match.status != "ambiguous":
        return None

    query = normalize(answer)
    while query and query.split()[0] in _LEADING_FILLER:
        query = " ".join(query.split()[1:])
    if not query:
        return None

    matches = [
        item
        for item in command.noun_match.candidates
        if query == item.name or query in {normalize(alias) for alias in item.aliases}
    ]
    if len(matches) != 1:
        return None
    item = matches[0]
    return replace(
        command,
        noun_text=item.name,
        noun_match=NounMatch("resolved", (item,)),
    )
