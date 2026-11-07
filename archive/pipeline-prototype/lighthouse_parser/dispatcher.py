"""Room handlers for the text-only lighthouse prototype."""

from __future__ import annotations

from .matcher import ParsedCommand, normalize
from .scene_card import SceneCard, SceneObject


class Dispatcher:
    def __init__(self, scene: SceneCard, available_verbs: tuple[str, ...]) -> None:
        self.scene = scene
        self.available_verbs = available_verbs
        self._exits = {exit_.direction: exit_ for exit_ in scene.exits}

    def dispatch(self, command: ParsedCommand) -> str:
        if command.verb is None:
            if not command.verb_text:
                return "Please enter a verb, such as look, examine, or go."
            return (
                f'You do not know how to "{command.verb_text}". '
                f"Try: {', '.join(self.available_verbs)}."
            )

        if command.verb.name == "look" and not command.noun_text:
            details = "; ".join(self.scene.sensory_details[:2])
            return f"You are in the {self.scene.location} {details}."

        if command.verb.name == "inventory":
            return "You are not carrying anything."

        if command.verb.name == "go":
            return self._move(command.noun_text)

        if command.noun_match is None or command.noun_match.status == "missing":
            return f"What do you want to {command.verb.name}?"
        if command.noun_match.status == "unknown":
            return f'You don\'t see "{command.noun_text}" here.'
        if command.noun_match.status == "ambiguous":
            names = [item.name for item in command.noun_match.candidates]
            if not names:
                return f'Which "{command.noun_text}" do you mean?'
            choices = " or ".join(names)
            return f"Which do you mean: {choices}?"

        item = command.noun_match.candidates[0]
        return self._handle_object(command.verb.name, item)

    def _move(self, destination: str) -> str:
        target = normalize(destination)
        direction_aliases = {
            "up": "north",
            "upstairs": "north",
            "down": "south",
            "left": "west",
            "right": "east",
        }
        direction = direction_aliases.get(target, target)
        if direction not in self._exits:
            for exit_direction, exit_ in self._exits.items():
                if normalize(exit_.description).find(target) >= 0 and target:
                    direction = exit_direction
                    break
        exit_ = self._exits.get(direction)
        if exit_ is None:
            available = ", ".join(self._exits)
            return f"You don't see a way to go {target or 'that way'}. Exits: {available}."
        if direction == "west":
            return f"The door opens toward {exit_.description}, but the dock is beyond this prototype."
        return (
            f"The spiral stair leads toward {exit_.description}, "
            "but the lantern room is beyond this prototype."
        )

    def _handle_object(self, verb: str, item: SceneObject) -> str:
        if verb in {"look", "examine"}:
            return item.description
        if verb in {"read", "open"} and item.name == "logbook":
            return (
                'The last entry is dated three days ago: "the light went out at '
                'midnight and I heard—" The sentence ends there.'
            )
        if verb == "listen" and item.name == "lantern":
            return "The lantern's wick hisses softly inside its metal housing."
        if verb == "smell":
            return "Lamp oil and wet wool linger in the salt air."
        if verb == "take":
            return f"The {item.name} is part of the room; you leave it where it is."
        if verb == "talk":
            return f"The {item.name} offers no reply."
        return f"You don't know how to {verb} the {item.name} yet."
