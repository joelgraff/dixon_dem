# Interaction Design

How the demo should feel. These rules come from playtest feedback and are meant to be applied to every new scene.

## Pacing and Presentation
- No screen clearing. Every scene and response appends to a scrollable log; a scene heading marks each arrival.
- Rooms are described in prose. There is no "You see:" or "Exits:" list. Examinable nouns are highlighted inline and exits are woven into the description.
- No explicit instructions to the player ("Type look around", "Try haul"). Next steps are exposed through curiosity, never stated.
- Transitions are gradual. The museum to 1830 shift takes four scenes (museum, street, river walk, water's edge) and the fog builds over turns spent at the water's edge. No scene jumps, no dropdown. `?scene=<id>` in the URL starts in any scene for testing.

## Progressive Discovery
- The top-level room description lists only what a visitor would notice first. Further detail is found by examining things.
- Objects carry `reveals`: examining one makes new nouns visible. Revealed nouns are added to the room description (`extras`) and become valid targets. Until then they are "not here" to the parser.
- Every prose cue must have a target or a natural reading. Do not tell the player something "looks wrong in a way you can't place". If a thing is not examinable, describe it plainly and let an NPC explain it (the empty photo frames are described by Margaret, not examined).
- Accessories are folded into their parent description rather than made separate nouns. The pen is described at the end of the guestbook entry, cueing `sign guestbook`; it is not an object.
- Do not invent views that real places would not give. The museum window shows a parking lot and wires, not the river. Place-appropriate dullness is fine; the hint to go outside comes from people.
- When something is intriguing, end the description on the intriguing detail (the exhibit panel that ends one line short). Do not explain it.

## Natural Verbs
- Objects respond to the verbs a real person would try: sign, read, sit, touch, push, open, climb, smell, search, board, call. Each object may supply its own reply; unhandled verbs get a mild default.
- `look out/through/in/under/behind <thing>` examines the thing.
- Any verb that obviously suits a described object (a guestbook can be signed) should be supported. When adding an object, ask what a curious person would do to it.

## Conversation
- `talk to <npc>` opens; `ask <npc> about <topic>` and `ask about <topic>` (when one person is present) answer from a topic list.
- Topics are keyword lists. Answers can change with state (before and after 1830).
- Every spoken line is attributed ("Margaret says, “…”") so the player always knows who is talking, even when using `ask about` without greeting first.
- Pleasantries work with whoever is present or a named NPC: thanks, hello, goodbye and well-wishes, how are you, sorry. Each NPC has its own in-character reply. Free-form small talk beyond these is optional, not required.
- NPCs should answer questions a person would actually ask. Do not add topics for things nobody would ask about (the window); an NPC fallback should sound like that person, not a parser.
- Tone must match content. An NPC lowers her voice only for something conspiratorial; otherwise let her be dry or humorous.
- NPCs are the primary source of nudges. Margaret mentions the river walk when asked about the exhibit or the river; the fog is an in-world reason to go out.

## Repeatable Reading
- Things a player reads more than once (the guestbook) give a different small selection of entries each time and gain entries after the player has visited 1830.

## Reusable Elements and Future Hooks
Ideas for later scenes, and details already planted in the demo, are kept in `future-hooks.md`. Whenever the user suggests something for later, or a scene plants a detail, add it there with where it lives now and what it could become.
