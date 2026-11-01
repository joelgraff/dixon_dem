"""Interactive text prototype and vocabulary-resource generator."""

from __future__ import annotations

import argparse
from pathlib import Path

from .dispatcher import Dispatcher
from .matcher import (
    ParsedCommand,
    load_verbs,
    normalize,
    parse_command,
    resolve_clarification,
)
from .resource import write_resource
from .scene_card import load_scene_card

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
SCENE_CARD = PROJECT_DIR / "scene-card.md"
VERB_TABLE = PACKAGE_DIR / "verbs.json"
DEFAULT_RESOURCE = PROJECT_DIR / "resources" / "lighthouse-vocabulary.tsv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the lighthouse parser prototype.")
    parser.add_argument(
        "--build-resource",
        nargs="?",
        const=str(DEFAULT_RESOURCE),
        metavar="PATH",
        help=f"write the SCI-ready vocabulary table (default: {DEFAULT_RESOURCE})",
    )
    args = parser.parse_args()

    scene = load_scene_card(SCENE_CARD)
    verbs = load_verbs(VERB_TABLE)
    if args.build_resource:
        output = write_resource(args.build_resource, scene, verbs)
        print(f"Wrote {output}")
        return

    dispatcher = Dispatcher(scene, tuple(verb.name for verb in verbs))
    print(f"{scene.title}\nType 'quit' to leave.")
    pending: ParsedCommand | None = None
    while True:
        try:
            text = input("> ")
        except EOFError:
            print()
            break
        if text.strip().lower() in {"quit", "exit"}:
            break
        if pending is not None:
            if pending.noun_match is None:
                raise RuntimeError("Pending clarification has no noun candidates.")
            if normalize(text) in {"cancel", "never mind"}:
                pending = None
                print("Clarification cancelled.")
                continue
            resolved = resolve_clarification(pending, text)
            if resolved is None:
                choices = " or ".join(
                    item.name for item in pending.noun_match.candidates
                )
                print(f"Please choose {choices}, or type 'cancel'.")
                continue
            print(dispatcher.dispatch(resolved))
            pending = None
            continue

        command = parse_command(text, verbs, scene)
        print(dispatcher.dispatch(command))
        if command.noun_match is not None and command.noun_match.status == "ambiguous":
            pending = command


if __name__ == "__main__":
    main()
