# Landmarks workstream notes — PAUSED mid-iteration (handoff)

**Status: paused by coordinator request** (a serious rendering bug — most
buildings and road surfaces not drawing in the composed world — takes
priority). This is a snapshot of an in-progress first pass, not a finished
iter1. Nothing here has been visually tuned against reference photos yet
beyond one rough sanity-check capture; expect another pass of fixes before
this is ready for the critic.

## What exists right now

All six landmarks are **generated and instanced**, in this state:

- `game/landmarks/tools/mesh_builder.gd` — shared low/mid-poly primitive
  builder (`LandmarkMeshBuilder`, RefCounted): boxes, cylinders/cones, domes,
  gable/mansard roofs, an arch-tube (torus segment), and a generic flat
  `add_panel` (safe outward-normal-from-cross-product helper, use this over
  hand-deriving quad winding — see header comments; several of the other
  primitives shipped with **backwards (inward-facing) winding on the first
  pass** and were fixed by direct cross-product verification, documented
  inline above each fix).
- `game/landmarks/tools/landmark_materials.gd` — duplicates
  `materials/lib/*.tres` in memory per landmark instance (so each gets its
  own `ground_level` shader param), plus a `signage()` helper for baked
  texture quads and a `foam()` helper for the dam's white-water shader.
  **Known bug found just before pausing, NOT yet fixed**: `signage()`
  hardcodes `cull_mode = CULL_DISABLED` on every sign material. Where a sign
  is mounted as two back-to-back panels facing opposite directions (Dixon
  Arch crown sign, theatre marquee), double-sided rendering lets each
  panel's *backside* (unflipped, so mirrored) bleed through the other's
  transparent margins — visible as a faint mirrored "DIXON" ghost in
  `captures/landmarks/sanity/arch.png`. Fix: make `cull_mode` a parameter,
  default `CULL_BACK` (single-sided), since `add_panel`'s winding already
  guarantees the correct face points the right way.
- `pipeline/landmarks/gen_signage.py` — Pillow-generated signage textures
  (DIXON arch crown sign, theatre marquee, Lincoln pedestal text, courthouse
  entablature text, Lincoln Highway sidewalk stamp) → `game/landmarks/textures/*.png`.
  Re-run: `cd pipeline/landmarks && ../../.venv/bin/python gen_signage.py`,
  then `game/tools/import.sh` (Godot won't load a new PNG without an import
  pass first — cost me one failed build).
- `game/landmarks/tools/build_landmarks.gd` — the main headless build
  script, one `_build_*()` function per landmark + the Dixon Arch/bridge
  dressing/dam complex, run with:
  ```
  ~/AppImage/Godot_v4.6-stable_linux.x86_64 --headless --path game \
    --script res://landmarks/tools/build_landmarks.gd
  ```
  Writes `game/landmarks/{lee_county_courthouse,dixon_arch_complex,
  lincoln_statue,dixon_theatre,reagan_boyhood_home,nachusa_house}.tscn`
  (each in **local space**, front wall/span facing local -Z or +X — see the
  big header comment in that file) plus the composed
  `game/landmarks/landmarks.tscn` (instances all six at their real
  positions with a Y-rotation baked in, computed from real OSM footprint
  bearings — documented in the header, not guessed).
- `game/landmarks/test_landmarks.tscn` — standalone test scene
  (Atmosphere + Terrain + Landmarks), no Roads/Buildings.
- **`game/world/world.tscn` (SHARED FILE) has one additive edit**: an
  `ext_resource id="8"` for `landmarks.tscn` and one
  `[node name="Landmarks" parent="." instance=ExtResource("8")]` line, no
  transform (matches Terrain/Vegetation's convention — positions are already
  baked in world coordinates). **This edit is complete and well-formed** (I
  verified the file reads back cleanly) — it is almost certainly unrelated
  to the buildings/roads rendering bug the coordinator flagged (that bug
  predates this session per `docs/roads_notes.md`'s "mid-block coverage
  gap" and `docs/terrain_notes.md`'s iter3 notes), but flagging in case
  anyone wants to isolate variables: reverting is just removing those two
  lines.

## Bearings used (derived, not guessed — see build_landmarks.gd header)

Computed this session from real OSM footprint polygons in
`game/data/buildings.json` via shapely `minimum_rotated_rectangle`: downtown
grid landmarks (courthouse, theatre, Nachusa House, Dixon Arch) all share
long-edge bearing ~254°/74°, short-edge ~344°/164° (Dixon's street grid is
rotated ~16° off true north). Reagan Boyhood Home (different block) matches
within 1°. Front-wall bearings used: courthouse 344.1°, theatre 73.9°,
reagan 73.1°, nachusa 72.3°, lincoln 74.0° (chosen, not footprint-derived —
statue is a POI point not a footprint), dixon_arch spans at 72.9°.
Godot rotation formula: local front = -Z convention → `rotation_y =
-bearing`; arch's local span = +X convention → `rotation_y = radians(90 -
bearing)`.

## First capture pass — rough, camera placement was bad (not a geometry verdict)

`captures/landmarks/sanity/*.png` (8 shots, `test_landmarks.tscn`, no
Roads/Buildings). **Do not read these as a quality verdict** — most camera
positions were naive axis-aligned offsets that didn't account for each
building's actual ~70-74°/344° rotation, so several shots ended up too
close to or clipped inside the geometry (courthouse, theatre, reagan,
nachusa all show extreme close-ups of wall/underside, not full elevations).
Two shots came out well-framed and are informative:
- `arch.png`: correct span/proportions, "DIXON" lettering with red
  neon-look outline reads well, piers + lamp posts present, courthouse dome
  and dam visible in the background (world coherence check passed) — **but
  see the cull_mode bug above**, faint mirrored ghost text visible.
- `lincoln.png`: pedestal/base reads fine; the simplified primitive
  bronze figure (cylinders + a tapered "coat" cone + dome head) is
  recognizable as "a standing figure on a plinth" at this distance but
  looks a bit thin/coneish — worth a closer look and possibly bulking up
  the coat radius before calling it done.
- `dam.png` / `bridge_dressing.png` (mislabeled by me — bridge_dressing.png
  actually shows the dam's haunch geometry near a bank, not the actual
  Galena Ave bridge deck, since that deck lives in `roads.tscn` which
  isn't in this Roads-less test scene): both shots were framed almost at
  water level (camera Y too close to the 5.92/3.54 local-Y river pool
  levels) — need higher/further-back cameras next pass, and the bridge
  dressing specifically needs re-checking against the *composed* world
  (with Roads) since its whole point is decorating roads' existing deck.

**Next steps queued for whoever resumes this**:
1. Fix `signage()` cull_mode (see above).
2. Set `face_size_m = Vector2(1,1)` on the Reagan/Nachusa shingle/slate
   material overrides in `build_landmarks.gd` — `add_gable_roof`/
   `add_mansard` already emit UV in real meters, but the shingle shader's
   default `face_size_m=(4,3)` multiplies that again, tripling/quadrupling
   the effective course frequency. Nachusa's slate currently uses
   `use_world_uv=true`, which ignores mesh UV entirely and reads a default
   `ridge_xy` calibrated for nothing in particular — switch it to
   `use_world_uv=false` + the same meter-UV convention as Reagan for
   consistency, per the shader's own header comment.
3. Recompute camera positions for a real capture pass using bearing-based
   math (`pos = landmark_xz + Vector2(sin(bearing), -cos(bearing)) *
   distance`) instead of naive axis offsets, at larger standoffs (30-50m
   establishing, 15-25m approach, checked to clear each footprint given its
   actual rotation), and raise dam/bridge camera heights well above the
   5.92/3.54 pool levels.
4. Only after the above: run the full required capture set (approach +
   establishing per landmark, summer clear + one other season, from
   `world.tscn` once the buildings/roads bug is fixed) and compare against
   `docs/references/img/<landmark>/` photos before writing a real per-
   landmark confidence report.
5. Performance was **not yet measured** for the composed world with
   landmarks — do this once the coordinator's priority bug is resolved and
   Roads/Buildings render normally again, since a measurement taken with
   that bug active would be meaningless.

## Known lower-confidence areas (carried from the reference docs)

- `dixon_dam` massing is explicitly lower-confidence per
  `docs/references/dixon_dam.md` (no close-up reference photo exists) —
  powerhouse fenestration/roof form is a plausible period estimate.
- `nachusa_house` position was flagged "interpolated" in the brief, but
  this session found a real OSM footprint (`buildings.json`) whose centroid
  matches the given coordinate almost exactly — treat the position as
  sanity-checked/confirmed, not still-uncertain.
