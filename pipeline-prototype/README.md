# Pipeline Prototype

A self-contained sample project that exercises the full art-and-parser pipeline for the Dixon DEM Sierra renderer, using a non-Dixon scene so the Dixon canon stays clean.

## Goal
Prove the end-to-end loop: scene card to prompt to generated plate to SCI-compatible resources to a playable parser room — before committing any of it to Dixon.

## Palette Target
**16-color IBM EGA palette.** The visual target is original 1980s-era PC adventure-game pixel art: deliberate pixel clusters, strong silhouettes, and restrained dithering. The generated image is resized to 320x200 and palette-enforced locally; the image model's color accuracy is only a suggestion, not a dependency.

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

### Phase One prototype commands

From this directory, generate the tab-separated vocabulary resource with:

```sh
python -m lighthouse_parser.main --build-resource
```

Start the text adventure with:

```sh
python -m lighthouse_parser.main
```

The generated `resources/lighthouse-vocabulary.tsv` contains verb and noun
aliases plus deletion-signature indexes for one-character fuzzy lookups. Its
record format and thresholds are documented in `lighthouse_parser/resource.py`.
Run the standard-library test suite from this directory with:

```sh
python -m unittest discover -s tests -v
```

## Phase Two — Visuals
**Goal:** Same lighthouse room with an original, cleaned, 320x200 background plate in the 16-color EGA palette.

**Steps:**
1. Generate a scene-specific positive and negative prompt from the scene card
2. Use those prompts with an image-generation tool and save its output locally
3. Crop/resize to 320x200, apply Floyd-Steinberg dithering, and enforce the exact EGA palette
4. Review and hand-clean the plate in GIMP or Aseprite
5. Verify the PNG's indexed palette and inspect it at native resolution
6. Generate priority/control screens in a later pass after the background plate is approved

**Tools:** Any image-generation tool that accepts a prompt, Python 3 with Pillow, GIMP or Aseprite.

### Phase Two prototype commands

Pillow 10 or newer is the only additional runtime dependency. Check whether
the selected Python already has it:

```sh
python -c "import PIL; print(PIL.__version__)"
```

If that import fails, install the dependency listed in `requirements.txt` with
your Python environment's package manager. This checkout's `/usr/bin/python3`
already has Pillow 10.2.0; its system Python does not include `pip`.

Generate the prompt to paste into your image-generation tool:

```sh
python -m lighthouse_art.main prompt
```

The prompt is written to `prompts/lighthouse-cottage.txt`. It includes the
positive scene/style constraints and a negative prompt. The wording describes
technical traits (EGA colors, pixel clusters, dithering, resolution, and
composition) rather than asking a model to reproduce a specific game's screen.

After generating an image, process it into an indexed plate:

```sh
python -m lighthouse_art.main process --input path/to/generated-image.png
```

The default output is `artifacts/lighthouse-cottage-ega.png`; a neighboring
`*-palette-report.json` records the used EGA colors and confirms that no
off-palette pixels remain. Supply `--output path/to/plate.png` to choose a
different output path. Non-16:10 source images are center-cropped to 16:10.

**Dithering is off by default.** If your generator already produces pixel art
with a limited palette, dithering again just adds noise: the downscale blends
neighboring colors, and error diffusion scatters those blends into speckle.
The default (`--resample box --dither none`) averages each block of source
pixels and snaps it to the nearest palette color. Options:

- `--resample nearest` is crispest and keeps the source's own dither pattern,
  but can alias on fine detail; `lanczos` is sharper but ringing can make stray
  pixels.
- `--dither floyd-steinberg` is for smooth, photo-like sources (for example a
  non-pixel-art render) that need dithering to fake in-between colors.

### 32-color variant

A separate prompt and processing path uses a 32-color extended EGA palette (the
16 standard colors plus 16 more from EGA's 64-color master palette, such as
navy, dark teal, steel blue, orange, and peach). It is not a standard EGA mode,
but every color is a valid EGA master-palette value:

```sh
python -m lighthouse_art.main prompt --palette ega32
python -m lighthouse_art.main process --palette ega32 --input path/to/generated-image.png
```

These write `prompts/lighthouse-cottage-ega32.txt` and
`artifacts/lighthouse-cottage-ega32.png`, leaving the 16-color files untouched.

Run the parser and art-pipeline tests with:

```sh
python -m unittest discover -s tests -v
```

**Pass-fail checks:**
- [ ] Plate matches the style-reference library in palette and mood [PASS: no visible hue drift vs. approved samples]
- [ ] Dithered plate still reads at SCI resolution [PASS: all interactive objects identifiable at native size]
- [ ] Priority screen layers the lantern shelf in front of the desk [PASS: depth ordering matches scene card layout]
- [ ] Processed plate uses only the 16 EGA colors [PASS: palette report lists zero off-palette pixels]

**If a check fails:** regenerate with a tighter prompt template before manual cleanup.

## Phase Three — Second Room
**Goal:** The lantern room up the spiral stair, connected by an exit.

**Steps:**
1. Write a scene card for the lantern room (done — see [scene-card-lantern-room.md](scene-card-lantern-room.md))
2. Generate its background plate using the style-reference library from phase two
3. Wire the exit so "go north" or "go up" transitions between rooms
4. Test parser state persistence across the transition
5. Test carrying an object from one room to the other

**Tools:** Same as phase two, plus SCICompanion for room wiring.

Generate the lantern-room art prompt without overwriting the cottage prompt:

```sh
python -m lighthouse_art.main prompt --scene-card scene-card-lantern-room.md --output prompts/lantern-room.txt
```

Add `--palette ega32` and use `--output prompts/lantern-room-ega32.txt` for
the extended-palette variant. The card defines the room and its return exit;
room transitions and the carried-lantern interaction still need implementation.

**Pass-fail checks:**
- [ ] Second plate matches the first in palette and mood [PASS: side-by-side comparison shows no style break]
- [ ] Transition does not break parser state [PASS: inventory and flags survive the move]
- [ ] An object picked up in room one is usable in room two [PASS: "take lantern" in room one, "use lantern" in room two works]
- [ ] Scene-card format scales past a single screen without modification [PASS: lantern room card uses the same six fields]

**If a check fails:** the scene-card format needs a revision before phase four.

## Phase Four — Character and Dialogue
**Goal:** A character sprite and one line of talk.

**Steps:**
1. Generate or hand-tweak a 32x52 keeper sprite (about 48 pixels tall, matching Sierra SCI0 player characters such as Rosella in King's Quest IV) using [the keeper sprite prompt](prompts/lighthouse-keeper.txt)
2. Wire a talk verb so "talk to keeper" returns one spoken line
3. Verify the sprite layers correctly against the priority screen

**Tools:** Stable Diffusion or hand-tweaked pixel art, Aseprite, SCICompanion.

The keeper prompt targets one transparent 32x52 idle sprite with a restrained
subset of the standard EGA palette, suitable for either background palette.
Use the positive prompt and, where supported, the separate negative prompt;
the final usage notes are for manual cleanup, not for the image model.
Do not run the background `process` command on character sprites: it crops
to 320x200 and discards transparency. Use the `sprites` command instead; it
slices a generated sheet into transparent 32x52 cells with the keeper scaled
to 48 pixels and every pixel snapped to EGA:

```sh
python -m lighthouse_art.main sprites --input images/sprite/seedream-2.png --grid 12 10 --output artifacts/keeper-seedream
```

It writes `frames/rRR_cCC.png` (one cell per frame, feet on row 50),
`sheet.png`, a 4x `preview.png` on EGA blue, and `report.json`. The whole sheet
shares one scale factor, so crouches stay proportional. `--grid COLUMNS ROWS`
is only needed when figures touch between rows; the command warns when it
suspects that. Treat the output as a clean base for hand touch-up in Aseprite
or LibreSprite, not finished art. Animation playback and SCI view export are
not yet implemented.

For a proposed full animation set, use [the keeper sprite-sheet prompt](prompts/lighthouse-keeper-spritesheet.txt).
It defines four directions for idle, walking, running, turning, reaching,
picking up, using/inspecting, talking, ascending/descending stairs, and
lantern-carrying idle/walk cycles. The six-column, 48-row layout uses 32x52
cells; production notes explain how to generate individual rows for better
consistency. This is an art specification, not implemented animation support.

**Pass-fail checks:**
- [ ] Sprite is legible at SCI resolution [PASS: silhouette and key features readable]
- [ ] "Talk to keeper" returns exactly one line of dialogue [PASS: no parser error, no extra output]
- [ ] Sprite respects priority layering [PASS: renders behind or in front of objects per the priority screen]

**If a check fails:** this is the last mile — decide whether the pipeline is worth pointing at Dixon before investing further.

## Open Questions
- How much Aseprite or GIMP cleanup does a typical AI-generated plate actually need?
- Does the constrained EGA palette and dithering read clearly at native resolution?
- Should later phase-two work generate priority and control screens from a depth map?
