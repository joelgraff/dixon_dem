"""Load the lighthouse scene card's small, deliberately constrained Markdown format."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SceneObject:
    name: str
    aliases: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class Exit:
    direction: str
    description: str


@dataclass(frozen=True)
class SceneCard:
    title: str
    location: str
    background_description: str
    sensory_details: tuple[str, ...]
    objects: tuple[SceneObject, ...]
    exits: tuple[Exit, ...]
    planted_hook: str

    @property
    def object_by_name(self) -> dict[str, SceneObject]:
        return {item.name: item for item in self.objects}


def _section(document: str, title: str) -> str:
    match = re.search(
        rf"^## {re.escape(title)}\s*$\n(.*?)(?=^## |\Z)",
        document,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise ValueError(f"Scene card is missing the '{title}' section.")
    return match.group(1).strip()


def _bullets(section: str) -> list[str]:
    return [
        match.group(1).strip()
        for line in section.splitlines()
        if (match := re.match(r"^\s*-\s+(.+?)\s*$", line))
    ]


def load_scene_card(path: str | Path) -> SceneCard:
    """Load fields and alias-backed nouns from a scene-card Markdown file."""
    document = Path(path).read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+?)\s*$", document, re.MULTILINE)
    if not title_match:
        raise ValueError("Scene card must begin with a level-one title.")

    location = _section(document, "Location")
    sensory_details = tuple(_bullets(_section(document, "Sensory Details")))
    interactive_objects = _bullets(_section(document, "Interactive Objects"))
    aliases: dict[str, tuple[str, ...]] = {}
    for line in _bullets(_section(document, "Object Aliases")):
        name, separator, alias_text = line.partition(":")
        if not separator or not name.strip():
            raise ValueError(f"Invalid object alias entry: {line!r}")
        canonical = name.strip().lower()
        values = tuple(
            alias.strip().lower()
            for alias in alias_text.split(",")
            if alias.strip()
        )
        aliases[canonical] = tuple(dict.fromkeys((canonical, *values)))

    contextual_descriptions: dict[str, str] = {}
    contextual_section = re.search(
        r"^## Contextual Objects\s*$\n(.*?)(?=^## |\Z)",
        document,
        flags=re.MULTILINE | re.DOTALL,
    )
    if contextual_section:
        for line in _bullets(contextual_section.group(1)):
            name, separator, description = line.partition(":")
            if separator and name.strip() and description.strip():
                contextual_descriptions[name.strip().lower()] = description.strip()

    objects: list[SceneObject] = []
    for name, object_aliases in aliases.items():
        description = next(
            (
                item
                for item in interactive_objects
                if re.search(rf"\b{re.escape(name)}\b", item, re.IGNORECASE)
            ),
            "",
        )
        objects.append(
            SceneObject(
                name=name,
                aliases=object_aliases,
                description=(
                    description
                    or contextual_descriptions.get(name, name.capitalize())
                ),
            )
        )

    exits: list[Exit] = []
    for line in _bullets(_section(document, "Entry and Exit Points")):
        match = re.search(
            r"\bto the (north|south|east|west)\b.*?\bleads (?:up )?to the (.+)$",
            line,
            re.IGNORECASE,
        )
        if match:
            exits.append(
                Exit(match.group(1).lower(), match.group(2).rstrip("."))
            )

    if not exits:
        raise ValueError("Scene card must define at least one directional exit.")

    return SceneCard(
        title=title_match.group(1).strip(),
        location=location,
        background_description=_section(document, "Background Composition"),
        sensory_details=sensory_details,
        objects=tuple(objects),
        exits=tuple(exits),
        planted_hook=_section(document, "Planted Hook"),
    )
