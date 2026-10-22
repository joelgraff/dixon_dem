# Pipeline Prototype

Goal: prove the art-generation and scene-card pipeline works end to end, using skills an engineer (not an artist) can execute. Four phases, each with machine-gradable pass-fail checks, a tool list, and remediation guidance when a check fails.

## How grading works

Each phase has **checks** — binary pass/fail statements an AI reviewer can evaluate from the repo contents, playtest transcripts, or generated artifacts. After each phase, paste the phase's deliverables (scene card, code, images, SCICompanion project files) to the AI along with this README and ask it to grade every check. Failed checks include a **remediation** — a concrete next action, not a vague suggestion.

## Design constraints this prototype must honor

- **Scene cards** are the single source of truth for each screen: location, era, palette, background description, buildings, interactive objects, entry/exit points, and one planted hook per room.
- **Terse-but-rich descriptions**: flavor is fine, but every room plants one odd detail that nags without shouting. A rushed player misses it; a curious one catches it.
- **Informational feedback**: failed commands say *why* they failed ("rope's too short") not just "you can't."
- **Threads**: lines of interaction that run to a decisive end. Exhaustion should feel earned, not arbitrary, and should hand off to the next priority.
- **Abandoned threads resurface as consequences** — a scar, not a dead end.
- **One live thread at a time**; others sit as background until a trigger pulls them forward.
- **SCI target**: 16-color palette, bitmap backgrounds, priority and control screens. Art must be generatable, not hand-painted.

---

## Phase 1 — Text-only parser loop

**Done state:** one room, one object, working parser. You can type commands and get coherent responses with no visuals at all.

**Tools:** any text editor; Python (or your preferred language) for the parser; a terminal. No art tools required.

**Steps:**

1. Write one scene card for a single room (cabin interior recommended). Include: location, era, two or three sensory details, the interactive objects, entry/exit points, and exactly one planted hook.
2. Implement a minimal text parser: verb-noun dispatch. Support at least `look`, `look at <object>`, `examine <object>`, and directional movement (`go north`, etc.).
3. Write room descriptions that are rich but pointed — flavor plus the hook. Test that a failed command returns a reason, not a dead end.
4. Verify the thread structure: the room's one hook should open a mini-track that reaches a decisive stopping point, at which the game tells you clearly there's nothing more here for now.
5. Playtest alone. If you get stuck for more than a few commands without knowing why, the feedback is too thin — fix it.

**Checks (pass/fail):**

| # | Check | Pass condition | Fail remediation |
|---|-------|---------------|-----------------|
| 1.1 | Scene card exists and contains all required fields | Card lists location, era, 2-3 sensory details, objects, entry/exit points, exactly one hook | Add the missing field(s); if the hook is absent, write one sentence of odd detail that doesn't serve any other purpose |
| 1.2 | Parser supports look, look at, examine, and movement | Each command type returns a non-empty, coherent response | Implement the missing verb handler; if responses are empty strings, add fallback text |
| 1.3 | Failed commands explain why | At least three distinct failed commands each return a reason specific to that failure | Rewrite failure messages to name the specific obstacle (object missing, verb unsupported, direction blocked) |
| 1.4 | One thread reaches a decisive end | Playing the hook's thread produces a terminal state where the game states nothing further is available | Add an explicit closing line at the thread's end; do not leave it open-ended |
| 1.5 | A cold player can orient themselves | Someone reading only the opening description can state where they are and what they can do | Expand the opening description with location and available actions |

**Exit criteria:** all five checks pass.

---

## Phase 2 — Visuals for the same room

**Done state:** the Phase 1 room rendered as an SCI-compatible background with priority and control screens, playable in SCICompanion or ScummVM.

**Tools:** Stable Diffusion or Midjourney (image generation); Aseprite (free, pixel cleanup); SCICompanion (SCI authoring IDE); ScummVM (testing); Python with PIL/Pillow for downscale and posterize.

**Steps:**

1. Freeze the Phase 1 scene card. Do not change the text during this phase — the art must serve the card, not reshape it.
2. Create a fixed prompt template: era, location, palette (16-color frontier Midwest), lighting, composition. Every generation uses this template so plates stay consistent.
3. Generate the background plate with an image model. Feed it 2-3 reference images of period frontier interiors if available.
4. Downscale to SCI resolution. Posterize to a 16-color palette.
5. Clean up in Aseprite: fix edges, remove blotches, enforce the palette strictly.
6. Derive the priority screen from depth information (even a simple height-map pass works).
7. Build the control screen: walkability mask from ground geometry, hotspot rectangles for each interactive object from the scene card's coordinates.
8. Import into SCICompanion as a room. Wire the Phase 1 parser responses to the visual room.
9. Build the style-reference library: save the approved plate tagged by era and location.

**Checks (pass/fail):**

| # | Check | Pass condition | Fail remediation |
|---|-------|---------------|-----------------|
| 2.1 | Scene card unchanged from Phase 1 | Diff between Phase 1 and Phase 2 card shows no text edits | Revert any card edits; art adapts to text, never the reverse |
| 2.2 | Prompt template is fixed and reused | Template file exists; generation log shows identical template text across attempts | Extract template to its own file; log every generation with the template version used |
| 2.3 | Output is 16-color SCI-resolution | Final plate is at SCI resolution with a palette of 16 or fewer colors | Re-run posterize step; if artifacts persist, regenerate with a stricter palette constraint in the prompt |
| 2.4 | Aseprite cleanup applied | Before/after files exist showing edge fixes and blotch removal | Spend at least one focused cleanup pass; if blotches remain, regenerate the source plate rather than patching endlessly |
| 2.5 | Priority screen derived, not hand-painted | Priority screen file exists and was produced from depth/height data | Build a simple height-map pass in Python; manual painting is out of scope |
| 2.6 | Control screen has walkability and hotspots | Control screen encodes blocked/walkable areas and hotspot rectangles matching scene-card object coordinates | Generate walk mask from ground geometry; place hotspots from card coordinates |
| 2.7 | Room loads in SCICompanion/ScummVM | Project opens without errors; background displays | Fix import settings (palette format, resolution); re-export from Aseprite as indexed PNG |
| 2.8 | Typing at an object returns the Phase 1 response | In-game examine of each object yields the Phase 1 text verbatim | Re-wire the parser's object responses to the visual room's object IDs |
| 2.9 | Style-reference library started | Approved plate saved with era/location tags | Create the folder and tagging convention now; it pays off in Phase 3 |

**Exit criteria:** all nine checks pass.

---

## Phase 3 — Second room and transitions

**Done state:** two interconnected rooms. Exiting one enters the other. Both plates are stylistically consistent via the reference library.

**Tools:** same as Phase 2, plus the style-reference library as mandatory generator input.

**Steps:**

1. Write a second scene card for an adjacent room (lean-to, dock, or mill — anything connected by a single exit).
2. Run it through the Phase 2 pipeline. The style-reference library is now mandatory input.
3. Implement the exit transition: leaving room A enters room B at a defined entry point. Player position and inventory carry across.
4. Verify palette and tone consistency between the two plates.
5. Plant one hook in room B that connects back to room A.
6. Confirm informational-feedback holds in both rooms.

**Checks (pass/fail):**

| # | Check | Pass condition | Fail remediation |
|---|-------|---------------|-----------------|
| 3.1 | Second scene card follows Phase 1 format | Card contains all required fields including exactly one hook | Mirror the Phase 1 card structure; copy the field list verbatim |
| 3.2 | Style-reference library used in generation | Generation log or prompt shows reference plate attached | Attach the Phase 2 approved plate as a reference image before generating |
| 3.3 | Exit from A enters B at a defined point | Moving through the exit places the player at B's entry coordinates | Define entry points in both cards; test the transition command |
| 3.4 | Position and inventory persist across rooms | After A-to-B transition, carried items remain and position is correct | Store player state in a global; verify on room change |
| 3.5 | Plates are stylistically consistent | Side-by-side comparison shows matching palette, tone, and line weight | Regenerate the drifting plate with the reference library enforced; adjust prompt template if drift is systematic |
| 3.6 | A thread spans both rooms | One hook's thread has steps in A and a conclusion in B (or vice versa) | Rewrite one hook so its mini-track crosses the exit |
| 3.7 | Informational feedback holds in both rooms | Failed commands in B return specific reasons | Apply Phase 1 check 1.3 to room B's parser handlers |
| 3.8 | Full loop playable | A to B to A completes without error or softlock | Trace the exit commands; fix any handler that doesn't return to A |

**Exit criteria:** all eight checks pass.

---

## Phase 4 — Character sprite and dialogue

**Done state:** one character sprite in one room, one line of dialogue triggered by an object or location.

**Tools:** Stable Diffusion or Midjourney for sprite generation; Aseprite for 16-color editing; SCICompanion for placement and scripting.

**Steps:**

1. Generate or source a single character sprite (frontier settler, 16-color, palette-consistent). Heavy Aseprite editing expected.
2. Place the sprite in room A or B at a defined position.
3. Implement one dialogue line: approaching or examining the character triggers a 2-4 line exchange.
4. Verify the sprite doesn't break the priority screen or walkability.
5. Log what was hardest — input for deciding whether a Phase 5 (full Dixon scene) is worth attempting.

**Checks (pass/fail):**

| # | Check | Pass condition | Fail remediation |
|---|-------|---------------|-----------------|
| 4.1 | Sprite is 16-color and palette-consistent | Sprite uses colors from the established 16-color palette | Re-palette in Aseprite against the phase-2 palette file; regenerate if too many unique colors remain |
| 4.2 | Sprite placed at a defined position | Sprite coordinates recorded in the room's script or scene card | Add position to the scene card; place via SCICompanion at those coordinates |
| 4.3 | Dialogue triggers on approach or examine | Command or proximity triggers a 2-4 line exchange | Wire a trigger in SCICompanion; keep dialogue to 4 lines max |
| 4.4 | Priority screen and walkability intact | Sprite does not block walkable paths or render under foreground objects incorrectly | Adjust sprite's priority band in SCICompanion; test walking behind/in front |
| 4.5 | Hardship log exists | A short written note of what was hardest is committed to the repo | Write 3-5 sentences on friction points; this feeds the Phase 5 decision |

**Exit criteria:** all five checks pass. At that point the prototype contains every SCI ingredient — background, priority, control, object, character, dialogue — and the pipeline is proven.

---

## What this prototype deliberately excludes

- No time travel, no Akron-style rewrite wave, no canon-layer date gating. Those are Dixon-specific and belong in dixon_dem proper.
- No multiplayer, no web deployment, no ScummVM Emscripten build. Local SCICompanion/ScummVM only.
- No community editing tools. Single author.
- No 3D rendering. 2D bitmaps only.

## Open questions to resolve during the prototype

- Which image generator produces the most consistent 16-color-friendly output with the fewest artifacts after posterization?
- How much Aseprite cleanup is typical per plate — minutes or hours?
- Does priority-screen derivation from depth data produce usable walkability, or does it need manual correction?
- What is the minimum scene-card content that still produces a good generation prompt?
- Can the style-reference library actually steer the generator, or does prompt wording dominate?
