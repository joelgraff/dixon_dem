# Pipeline Prototype

A self-contained sample project that exercises the full art-and-parser pipeline for the Dixon DEM Sierra renderer, using a non-Dixon scene so the Dixon canon stays clean.

## Goal
Prove the end-to-end loop: scene card to prompt to generated plate to SCI-compatible resources to a playable parser room — before committing any of it to Dixon.

## Palette Target
**32 colors.** SCI0-era aesthetic with SCI1-legal headroom. Enough range for water gradients and sky transitions that 16 colors choke on, without losing the hand-picked constraint that makes SCI0 art feel deliberate. The snap-and-enforce tool's default, the prompt template's palette line, and the Aseprite indexed-color target are all locked at 32.

## Phase One — Text Only
**Goal:** One room, one object, a working verb-noun parser. No art.

**Steps:**
1. Write the lighthouse scene card (done — see scene-card.md)
2. Implement the four Python modules: scene card loader, matcher, dispatcher, main loop
3. Build the verb table (15 core verbs) and noun entries with aliases
4. Implement fuzzy matching with Levenshtein scoring and the three failure categories
5. Write handlers for lantern, logbook, telescope, movement, and generic failures
6. Run the Python prototype as the lookup-table generator — emit the SCI-ready resource file

**Tools:** Python 3, text editor, terminal.

**Pass-fail checks:**
- [ ] A cold player can type "look around" and understand where they are [PASS: response names location and at least two sensory details]
- [ ] "Examine lantern" returns the lantern description; "examine spyglass" resolves to telescope via alias [PASS: both return correct object text]
- [ ] A failed command explains why — not just "you can't" [PASS: failure message names the missing verb or object]
- [ ] Ambiguous input ("look at the light") triggers clarification rather than a guess [PASS: output offers candidates]
- [ ] The Python run emits a valid lookup table consumable by LSCI [PASS: table loads without error in a stub SCI script]

**If a check fails:** revisit the matcher scoring threshold or the alias list before moving on.

## Phase Two — Visuals
**Goal:** Same lighthouse room with a generated, cleaned, SCI-ready background plate.

**Steps:**
1. Feed the scene card's background description through the fixed prompt template (era, location, palette, lighting) into Stable Diffusion
2. Downscale to SCI resolution with Python and Pillow
3. Posterize to 32 colors
4. Clean up in GIMP or Aseprite — fix edges, remove artifacts, enforce palette
5. Run the snap-and-enforce custom tool: hard-pixel edges, palette snap, auto-file to style-reference library if it passes checks
6. Generate priority screen from depth data; generate control screen for triggers
7. Verify the plate reads at SCI resolution

**Tools:** Stable Diffusion, Python with Pillow, GIMP or Aseprite, custom snap tool (to be built).

**Pass-fail checks:**
- [ ] Plate matches the style-reference library in palette and mood [PASS: no visible hue drift vs. approved samples]
- [ ] Posterized plate still reads at SCI resolution [PASS: all interactive objects identifiable at native size]
- [ ] Priority screen layers the lantern shelf in front of the desk [PASS: depth ordering matches scene card layout]
- [ ] Snap tool output passes palette enforcement with zero off-palette pixels [PASS: indexed-color conversion reports clean]

**If a check fails:** regenerate with a tighter prompt template before manual cleanup.

## Phase Three — Second Room
**Goal:** The lantern room up the spiral stair, connected by an exit.

**Steps:**
1. Write a scene card for the lantern room
2. Generate its background plate using the style-reference library from phase two
3. Wire the exit so "go north" or "go up" transitions between rooms
4. Test parser state persistence across the transition
5. Test carrying an object from one room to the other

**Tools:** Same as phase two, plus SCICompanion for room wiring.

**Pass-fail checks:**
- [ ] Second plate matches the first in palette and mood [PASS: side-by-side comparison shows no style break]
- [ ] Transition does not break parser state [PASS: inventory and flags survive the move]
- [ ] An object picked up in room one is usable in room two [PASS: "take lantern" in room one, "use lantern" in room two works]
- [ ] Scene-card format scales past a single screen without modification [PASS: lantern room card uses the same six fields]

**If a check fails:** the scene-card format needs a revision before phase four.

## Phase Four — Character and Dialogue
**Goal:** A character sprite and one line of talk.

**Steps:**
1. Generate or hand-tweak a 16x16 or 20x20 keeper sprite
2. Wire a talk verb so "talk to keeper" returns one spoken line
3. Verify the sprite layers correctly against the priority screen

**Tools:** Stable Diffusion or hand-tweaked pixel art, Aseprite, SCICompanion.

**Pass-fail checks:**
- [ ] Sprite is legible at SCI resolution [PASS: silhouette and key features readable]
- [ ] "Talk to keeper" returns exactly one line of dialogue [PASS: no parser error, no extra output]
- [ ] Sprite respects priority layering [PASS: renders behind or in front of objects per the priority screen]

**If a check fails:** this is the last mile — decide whether the pipeline is worth pointing at Dixon before investing further.

## Open Questions
- How much Aseprite or GIMP cleanup does a typical AI-generated plate actually need?
- Does 32 colors feel like SCI0 nostalgia or does it read as something else?
- Is the snap-and-enforce tool worth building as a first custom project, or does GIMP suffice?
