# Plan v2 — user review items (2026-09-20)

Status: **all subagent work on the model is stopped** pending review of this plan.
Evidence below was gathered by the orchestrator directly (code reading + numeric checks on the data),
not by agents. Each item: symptom → root cause (or candidates, honestly labelled) → fix → verification.

A recurring theme: **three separate systems shipped geometry that was invisible or misplaced for
mechanical reasons** (a stray node transform, inverted triangle winding, single-sided ribbons). Each
looked fine in its own test scene. Lesson baked into the plan: every workstream must verify in
`res://world/world.tscn` at eye height, never only in its own test scene.

---

## 10. Player movement (DONE — protected)
User retuned `game/player/player.gd`: WALK 10.4, RUN 30.5, CROUCH 9.9, JUMP 4.0 (fast inspection flying).
Committed as-is and recorded in ARCHITECTURE.md under "User-owned settings (do not revert)". Any future
realistic profile must be added as a *separate* selectable profile, not by overwriting these.

## 5. Sidewalks are only outlined  → ROOT CAUSE FOUND (same class as the asphalt bug)
`pipeline/roads/build_road_plan.py`: at junctions, curb/sidewalk loops are built with
`double_sided=True` (lines ~454-475) — those render, and are exactly the "outlines" visible. But the
**along-the-street** sidewalk/path surfaces go through `_paint_ribbon()` (line ~487) and the path builder
(line ~708) which call `add_ribbon(...)` with the default `double_sided=False`. The roads agent fixed
only the main asphalt ribbon call (line ~390) when it found its winding bug; the same wrong winding
derivation still culls sidewalk, path and painted-ribbon surfaces at eye height.
**Fix:** correct the winding derivation once, centrally, so all ribbons are right-side-out; keep
`double_sided` only where genuinely needed (thin free-standing strips). Audit every `add_ribbon`/
`_paint_ribbon` call site. **Verify:** eye-level frame in world.tscn showing a continuous sidewalk slab
with control joints, plus `--hide=Terrain` control.

## 6. Road crossings elevated  → ROOT CAUSE FOUND (rail grade crossings)
`build_road_plan.py` lines 776-781: rails are built as a continuous prism the whole length of the line —
`BALLAST_TOP 0.20`, `TIE_TOP 0.35`, `RAIL_TOP 0.50` — with no special case where a rail crosses a road.
So at every grade crossing the track stands ~0.5 m proud of the pavement. Real crossings are flush:
pavement/rubber panels fill between and outside the rails, with only the railhead proud by ~2 cm.
**Fix:** detect rail×road intersections, and within the crossing footprint (plus a few metres of taper)
drop ballast/ties below the road surface and lay crossing panels flush, leaving only the railhead.
**Verify:** eye-level and low-angle frames at a crossing; player should walk over it without a step.
(If the user instead meant *pedestrian* crosswalks reading as raised, the candidate is the stacked
Y-biases at junctions — gutter `ROAD_Y_BIAS+0.005..0.01`, sidewalk loops `0.05`, crosswalk paint `0.045`
— which can read as a plateau; worth checking in the same pass.)

## 4. Bridge not continuous with roadway  → ROOT CAUSE FOUND
`build_road_plan.py` line 999 excludes bridge ways from the road-surface build
(`... and not w["tags"].get("bridge")`), and `build_bridges()` (line 717) builds decks from
`bridges.json` using **pre-computed deck Y, not the heightmap**. Nothing reconciles the deck ends with
the approach roads, which use heightmap Y — so the two meet at different heights/widths, leaving a step
or gap at each abutment.
**Fix:** make the bridge deck and its approaches one continuous surface: sample the approach road ends,
build a vertical transition (approach slab) into the deck elevation, and match deck width to the
carriageway. Keep markings running across the deck.
**Verify:** frames from the deck looking both ways, from the bank showing the abutment, and a player walk
across with no step.

## 1. Buildings look awful  → PART DIAGNOSED, PART DESIGN WORK
(a) **Near-black walls** (blocking): whole facades render near-black with a sharp horizontal boundary
partway up. Two candidates, both testable by outputting the term as albedo: (i) the shared
`surface.gdshader` ground-proximity **grime** term — `ground_level` defaults to **0** while downtown sits
at Y≈14-17, so with a small `grime_height` every wall is fully "grimed" from its base up to a fixed world
height, which matches the sharp band exactly; (ii) residual **inverted normals** on wall faces after the
winding fix, lighting them as if facing away from the sun. (Materials is frozen — if the fix belongs in
the shared shader, it gets routed, not edited in place.)
(b) **Design quality** (the real work): current buildings are extruded footprints with flat painted-on
openings. Needs: per-bay facade generation with real depth (window reveals ~10-15 cm, recessed
storefronts, transoms, bulkheads), cornice/parapet profiles with shadow lines, roof clutter (HVAC,
vents, stair bulkheads), party-wall variation so a block reads as separate buildings, and glass with
reflection + interior darkness rather than flat panels. Use the user's `references/` photos.

## 2. Better tree shaders  → DESIGN WORK
Current foliage is untextured polygon clusters with a hole-punch noise mask; it reads as paper cutouts.
**Fix:** proper leaf-card atlas (CC0) with alpha-scissor + alpha-to-coverage for TAA stability;
**translucency/back-lighting** (leaves glow when lit from behind — the single biggest realism cue);
normals bent toward the canopy sphere so foliage shades as a volume rather than flat cards; AO darkening
into the canopy interior; per-instance hue/scale jitter; wind that moves branches and leaves at different
frequencies; and octahedral impostors for distance so silhouettes survive LOD.
**Verify:** same tree, four seasons, back-lit and front-lit, at 8 m / 25 m / 100 m.

## 3. Elevations look too flat  → DATA IS FINE, RENDERING IS THE CAUSE
Measured on the shipped heightmap: global relief **40.8 m**, downtown block **27.6 m**, slopes to **44°**,
19% of the map steeper than 5°. Road-conforming changed only 0.2% of cells (mean |delta| 0.01 m), so the
pipeline did not flatten anything.
**Candidates, in order:** (i) terrain LOD — `LOD0_STRIDE 2.0` / `LOD1_STRIDE 10.0` with the LOD1 switch
close enough that mid-ground bluffs are rendered from the 10 m mesh and round off; (ii) the 12.5 m horizon
ring flattening everything beyond the play area; (iii) shading — if terrain normals are computed from the
coarse mesh rather than the 1 m heightmap, slopes lose their shading cues even where geometry is correct;
(iv) atmosphere/haze plus absent mid-ground verticals removing depth cues.
**Fix:** push the LOD1 switch out, compute normals from the full-resolution heightmap into a normal map
regardless of mesh LOD, and re-check the horizon ring resolution. Only if it still reads flat should we
consider a modest global vertical exaggeration (1.15-1.25x) — and that must be applied **in the pipeline
heightmap** so terrain, roads, buildings and landmarks all shift together.
**Verify:** north bluff vista and a riverbank-to-bluff frame, before/after, same camera.

## 7. User reference photos  → INTEGRATED
16 photos now in `references/` (courthouse from several angles, Reagan home, arch, theatre, downtown
aerial). Committed. Landmarks work must be re-based on these (they supersede the agent-gathered
Wikimedia set where they conflict), especially the courthouse and Reagan home.

## 8. Location awareness — street names / minimap  → NEW FEATURE
Data is already there: `game/data/roads.json` carries street names per way, and `pois.json` has landmarks.
**Plan:** (a) a location readout — nearest street name, and "X & Y" when near an intersection, using the
junction-node data; (b) an optional minimap — render the road/water/building vectors to a top-down
texture at build time, with a player marker and north indicator; toggleable, off by default so it never
pollutes captures. Must respect `capture_mode` (hidden during screenshots).

## 9. Automatic screenshots  → NEW TOOLING
**Plan:** (a) a manual key (F12) in the player controller that saves a timestamped PNG to
`captures/manual/` with position/heading/season/weather in the filename; (b) a "tour" mode that walks a
named spawn list and captures each automatically, reusing the existing harness; (c) optional interval
capture while exploring. All must honour `capture_mode` and never capture debug UI.

---

## Sequencing (when work resumes)
1. **Blockers that make everything look wrong:** buildings near-black walls (1a), sidewalk winding (5),
   rail crossings (6), bridge continuity (4).
2. **Perceived flatness (3)** — LOD/normal-map work; cheap and lifts every frame.
3. **Tooling the user asked for:** screenshots (9), location/minimap (8) — small, independent, high daily value.
4. **Quality passes:** buildings facades (1b), tree shaders (2).
5. **Landmarks resume** — re-based on `references/`, plus the two known bugs (mirrored signage text,
   roof shingle UV scale 3-4x off).

## Process changes
- Every workstream verifies in `world.tscn` at 1.7 m eye height, with a `--hide=<own system>` control.
- Winding/orientation is now a known failure class: any new mesh generator must include a "does it render
  from eye height on both approaches" check before reporting done.
- No agent edits `world/world.tscn` transforms; the orchestrator owns that file's node transforms.
