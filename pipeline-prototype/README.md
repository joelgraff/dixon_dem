# Pipeline Prototype

Goal: prove the art-generation and scene-card pipeline works end to end, using skills an engineer (not an artist) can execute. Four phases, each with a clear done state. Stop after any phase and you still have something working.

## Design constraints this prototype must honor

- **Scene cards** are the single source of truth for each screen: location, era, palette, background description, buildings, interactive objects, entry/exit points, and one planted hook per room.
- **Terse-but-rich descriptions**: flavor is fine, but every room plants one odd detail that nags without shouting. A rushed player misses it; a curious one catches it.
- **Informational feedback**: failed commands say *why* they failed ("rope's too short") not just "you can't."
- **Threads**: lines of interaction that run to a decisive end. Exhaustion should feel earned, not arbitrary, and should hand off to the next priority.
- **Abandoned threads resurface as consequences** — a scar, not a dead end. The player feels the missed opportunity without a quest marker pointing at it.
- **One live thread at a time**; others sit as background until a trigger pulls them forward.
- **SCI target**: 16-color palette, bitmap backgrounds, priority and control screens. Art must be generatable, not hand-painted.

## Phase 1 — Text-only parser loop

**Done state:** one room, one object, working parser. You can type commands and get coherent responses with no visuals at all.

Steps:

1. Write one scene card for a single room (cabin interior recommended). Include: location, era, two or three sensory details, the interactive objects, entry/exit points, and exactly one planted hook.
2. Implement a minimal text parser: verb-noun dispatch. Support at least `look`, `look at <object>`, `examine <object>`, and directional movement (`go north`, etc.).
3. Write room descriptions that are rich but pointed — flavor plus the hook. Test that a failed command returns a reason, not a dead end.
4. Verify the thread structure: the room's one hook should open a mini-track that reaches a decisive stopping point, at which the game tells you clearly there's nothing more here for now.
5. Playtest alone. If you get stuck for more than a few commands without knowing why, the feedback is too thin — fix it.

**Exit criteria:** a second person (or your future self) can play the room cold and understand where they are, what they can do, and when a thread is done.

## Phase 2 — Visuals for the same room

**Done state:** the Phase 1 room rendered as an SCI-compatible background with priority and control screens, playable in SCICompanion or ScummVM.

Steps:

1. Freeze the Phase 1 scene card. Do not change the text during this phase — the art must serve the card, not reshape it.
2. Create a fixed prompt template: era, location, palette (16-color frontier Midwest), lighting, composition. Every generation uses this template so plates stay consistent.
3. Generate the background plate with an image model (Stable Diffusion or Midjourney). Feed it 2-3 reference images of period frontier interiors if available.
4. Downscale to SCI resolution. Posterize to a 16-color palette. This is where most AI artifacts die.
5. Clean up in Aseprite: fix edges, remove blotches, enforce the palette strictly. This is curation, not illustration — you are selecting and repairing, not drawing from scratch.
6. Derive the priority screen from depth information (even a simple height-map pass works) so layering is generated, not hand-painted.
7. Build the control screen: walkability mask from the ground geometry, hotspot rectangles for each interactive object placed from the scene card's coordinates.
8. Import into SCICompanion as a room. Wire the existing Phase 1 parser responses to the visual room.
9. Build the style-reference library: save the approved plate tagged by era and location. Future plates get compared against it.

**Exit criteria:** you can load the room in ScummVM or SCICompanion, see the background, walk (or at least see) the space, and click or type at an object and get the Phase 1 response.

## Phase 3 — Second room and transitions

**Done state:** two interconnected rooms. Exiting one enters the other. Both plates are stylistically consistent via the reference library.

Steps:

1. Write a second scene card for an adjacent room (the lean-to, the dock, or the mill — anything connected by a single exit).
2. Run it through the Phase 2 pipeline. The style-reference library from Phase 2 is now mandatory input to the generator.
3. Implement the exit transition: leaving room A enters room B at a defined entry point. Test that the player's position and inventory carry across.
4. Verify palette and tone consistency between the two plates. If they look like different games, the reference library isn't being used or the prompt template drifted.
5. Plant one hook in room B that connects back to room A — a thread that spans both screens. This tests whether threads can cross scene boundaries.
6. Confirm the informational-feedback rule holds in both rooms.

**Exit criteria:** a full loop — room A to room B and back — with at least one thread that touches both rooms and reaches a decisive end in one of them.

## Phase 4 — Character sprite and dialogue

**Done state:** one character sprite in one room, one line of dialogue triggered by an object or location.

Steps:

1. Generate or source a single character sprite (frontier settler, 16-color, consistent with the established palette). Heavy editing in Aseprite is expected.
2. Place the sprite in room A or B at a defined position.
3. Implement one dialogue line: approaching or examining the character triggers a short exchange. Keep it to 2-4 lines max.
4. Verify the sprite doesn't break the priority screen or walkability.
5. Log what was hardest — this becomes the input for deciding whether Phase 5 (full Dixon scene) is worth attempting.

**Exit criteria:** the prototype now contains every SCI ingredient: background, priority, control, object, character, dialogue. If it all holds together, the pipeline is proven and Dixon scene cards can start flowing through it.

## What this prototype deliberately excludes

- No time travel, no Akron-style rewrite wave, no canon-layer date gating. Those are Dixon-specific and belong in dixon_dem proper.
- No multiplayer, no web deployment, no ScummVM Emscripten build. Local SCICompanion/ScummVM only.
- No community editing tools. Single author.
- No 3D rendering. 2D bitmaps only.

## Open questions to resolve during the prototype

- Which image generator produces the most consistent 16-color-friendly output with the fewest artifacts after posterization?
- How much Aseprite cleanup is typical per plate — is it minutes or hours?
- Does the priority-screen derivation from depth data produce usable walkability, or does it need manual correction?
- What is the minimum scene-card content that still produces a good generation prompt?
- Can the style-reference library actually steer the generator, or does prompt wording dominate?
