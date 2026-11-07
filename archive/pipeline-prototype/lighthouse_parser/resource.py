"""Generate the tab-separated alias resource for an LSCI lookup stub.

Records are:
  META <key> <value>                      matcher limits and score thresholds
  V    <alias> <verb> <handler>            exact verb aliases
  N    <alias> <noun> <scene>              exact noun aliases
  D    <kind> <signature> <canonical> <alias>

D records index each alias and its one-character deletions. An LSCI reader can
index a query's corresponding signatures, then score the reduced candidate set.
All fields are tab-separated and aliases are normalized lowercase text.
"""

from __future__ import annotations

from pathlib import Path

from .matcher import (
    AUTO_RESOLVE_THRESHOLD,
    CLARIFICATION_FLOOR,
    MAX_INPUT_LENGTH,
    Verb,
    normalize,
)
from .scene_card import SceneCard


def _signatures(text: str) -> set[str]:
    return {text, *(text[:index] + text[index + 1 :] for index in range(len(text)))}


def resource_rows(scene: SceneCard, verbs: tuple[Verb, ...]) -> list[tuple[str, ...]]:
    rows: set[tuple[str, ...]] = {
        ("META", "max_input_length", str(MAX_INPUT_LENGTH)),
        ("META", "auto_resolve_threshold", f"{AUTO_RESOLVE_THRESHOLD:.2f}"),
        ("META", "clarification_floor", f"{CLARIFICATION_FLOOR:.2f}"),
    }
    for verb in verbs:
        for alias in verb.aliases:
            normalized = normalize(alias)
            rows.add(("V", normalized, verb.name, verb.handler))
            rows.update(
                ("D", "V", signature, verb.name, normalized)
                for signature in _signatures(normalized)
            )
    for item in scene.objects:
        for alias in item.aliases:
            normalized = normalize(alias)
            rows.add(("N", normalized, item.name, "lighthouse_cottage"))
            rows.update(
                ("D", "N", signature, item.name, normalized)
                for signature in _signatures(normalized)
            )
    return sorted(rows)


def write_resource(path: str | Path, scene: SceneCard, verbs: tuple[Verb, ...]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as resource_file:
        for row in resource_rows(scene, verbs):
            resource_file.write("\t".join(row) + "\n")
    return output
