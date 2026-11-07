from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lighthouse_parser.dispatcher import Dispatcher
from lighthouse_parser.matcher import (
    load_verbs,
    parse_command,
    resolve_clarification,
)
from lighthouse_parser.resource import write_resource
from lighthouse_parser.scene_card import load_scene_card

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCENE = load_scene_card(PROJECT_DIR / "scene-card.md")
VERBS = load_verbs(PROJECT_DIR / "lighthouse_parser" / "verbs.json")
DISPATCHER = Dispatcher(SCENE, tuple(verb.name for verb in VERBS))


def run(command: str) -> str:
    return DISPATCHER.dispatch(parse_command(command, VERBS, SCENE))


class ParserTests(unittest.TestCase):
    def test_room_description_includes_location_and_two_sensory_details(self) -> None:
        response = run("look around")
        self.assertIn(SCENE.location, response)
        self.assertIn("salt-crusted window glass", response.lower())
        self.assertIn("wick hissing", response.lower())

    def test_examine_aliases_resolve_to_scene_objects(self) -> None:
        self.assertIn("Storm lantern", run("examine lantern"))
        self.assertIn("Brass telescope", run("examine spyglass"))

    def test_light_alias_collision_asks_for_clarification(self) -> None:
        response = run("look at the light")
        self.assertIn("Which do you mean", response)
        self.assertIn("lantern", response)
        self.assertIn("lighthouse", response)

    def test_clarification_answer_resolves_only_a_listed_candidate(self) -> None:
        pending = parse_command("look at the light", VERBS, SCENE)
        resolved = resolve_clarification(pending, "the lantern")
        if resolved is None:
            self.fail("Expected the lantern to resolve the pending ambiguity.")
        self.assertEqual(
            DISPATCHER.dispatch(resolved),
            "Storm lantern on its shelf",
        )
        self.assertIsNone(resolve_clarification(pending, "light"))

    def test_unknown_verb_and_unknown_noun_have_specific_failures(self) -> None:
        self.assertIn("do not know how to", run("teleport"))
        self.assertIn("teleport", run("teleport"))
        self.assertIn("don't see", run("examine anchor"))
        self.assertIn("anchor", run("examine anchor"))

    def test_near_match_resolves_a_typo(self) -> None:
        self.assertIn("Storm lantern", run("examine lantrn"))

    def test_logbook_handler_surfaces_the_planted_hook(self) -> None:
        response = run("read journal")
        self.assertIn("three days ago", response)
        self.assertIn("I heard", response)

    def test_movement_explains_unimplemented_destination(self) -> None:
        self.assertIn("lantern room is beyond this prototype", run("go north"))

    def test_sci_input_limit_and_missing_noun_are_tolerated(self) -> None:
        response = run("examine the" + " " * 50 + "lantern")
        self.assertIn("What do you want to examine", response)

    def test_generated_resource_is_loadable_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = write_resource(
                Path(directory) / "vocabulary.tsv",
                SCENE,
                VERBS,
            )
            rows = [line.split("\t") for line in output.read_text().splitlines()]

        noun_aliases = {
            row[1]: row[2] for row in rows if row[0] == "N"
        }
        self.assertEqual(noun_aliases["spyglass"], "telescope")

        query = "lantrn"
        query_signatures = {
            query,
            *(query[:index] + query[index + 1 :] for index in range(len(query))),
        }
        indexed_candidates = {
            (row[3], row[4])
            for row in rows
            if row[0] == "D" and row[1] == "N" and row[2] in query_signatures
        }
        self.assertIn(("lantern", "lantern"), indexed_candidates)
        self.assertTrue(any(row[:3] == ["V", "examine", "examine"] for row in rows))
        self.assertTrue(any(row == ["META", "max_input_length", "40"] for row in rows))
        self.assertTrue(all(len(row) in {3, 4, 5} for row in rows))


if __name__ == "__main__":
    unittest.main()
