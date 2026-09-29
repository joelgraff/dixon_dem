# Adventure plan — a Sierra-style 2 / 2.5D game from the Dixon world

Status: proposal (2026-09-28). Nothing built yet.

The question: can the 3D Dixon model be the basis of a point-and-click adventure in the style of Sierra's
1980s–90s quest games (King's Quest, Space Quest, Police Quest)? Yes. Those games were built from fixed
views ("rooms") at 320×200: a painted background, a hidden **priority** (depth) screen so the hero could
walk behind things, a hidden **control** screen marking where he could walk, and sprites scaled with
distance. Every one of those layers can be generated from our 3D world rather than drawn by hand.

This plan proves the look on one street first, then decides between two ways of building the game.

---

## What a Sierra room is made of

| Layer | Sierra (SCI0/SCI1) | From the Dixon world |
|---|---|---|
| Background | hand-painted, 16 colours (EGA, dithered) or 256 (VGA), 320×190 play area | a low-resolution render from a fixed camera, quantized to a palette with ordered dithering |
| Priority | 16 horizontal depth bands | the camera's depth buffer: per-pixel occlusion, better than bands |
| Control / walkable | colour-coded polygons drawn by the artist | the ground surfaces (streets, sidewalks, lawns) rendered as a mask from the same camera, traced to a polygon |
| Hero | sprite, scaled by a per-room depth table | a sprite scaled from the depth buffer, or a low-poly 3D character rendered at the same resolution |
| Hotspots | rectangles / polygons | picked from the 3D objects under the cursor (buildings by id, props), or authored per room |

## Two ways to build it

### A. Live 3D behind fixed cameras (2.5D)

The Godot world keeps running. The game draws it into a 320×200 `SubViewport`, scaled up with nearest-neighbour
filtering, through a palette-and-dither shader. Each room is a fixed `Camera3D`; walking out of the frame cuts to
the next room's camera. A click on the ground raycasts into the world and walks the hero there along a navigation
mesh.

- Reuses everything: buildings, roads, terrain, lighting, time of day, the building editor.
- Changes to the world show up immediately; no re-rendering step.
- Looks like stylised 3D rather than a painted screen, and costs a live render of the city each frame.

### B. Pre-rendered rooms (true 2D)

A bake step renders each room's camera once: background, depth, and walk mask. The game itself is 2D, built in
a Godot point-and-click framework such as Popochiu (Godot 4, Sierra/LucasArts-style rooms, walkable polygons,
props with baselines, inventory, dialogue) or Escoria. A room is the baked background plus its polygons.

- The most authentic look; backgrounds can be painted over where they need character.
- Cheap at runtime; no city in memory.
- Fixed views only, and a world change means re-baking (scripted, so cheap, but a step).

**Recommendation:** build the A prototype first. It answers the real question (does the world read at 320×200?)
in a few days, and everything it needs (fixed cameras, low-res pipeline, depth, walk mask) is what B's bake
step would reuse. Choose A or B after seeing it.

---

## The real limit: detail at close range

At adventure-game distance the eye goes to windows, doors, porches, signs, fences, and clutter. Most buildings
are still boxes with roofs; walls without windows will make any background look empty. The Building Composer
facade work (windows, doors, trim, railings) is the main dependency for good-looking rooms. Until then, the
prototype should pick a street where the landmarks (courthouse, theatre, arch) carry the frame. Interiors, if
wanted, are separate rooms, modelled or painted.

---

## Phase 1 — prototype one street (option A)

Goal: walk a hero along one Dixon street block through three or four fixed views, in 320×200 with a VGA palette.

1. **Low-resolution pipeline.** A `SubViewport` at 320×200 (or 320×190 plus a 10 px status line), displayed
   scaled up with nearest-neighbour filtering. A post shader quantizes to a 256-colour palette with ordered
   (Bayer) dithering; a switch for a 16-colour EGA palette to compare. Optional: posterized lighting and dark
   outlines on silhouettes (depth/normal edges) to push it toward painted art.
2. **Rooms.** A room is a `Camera3D` placed by hand (a JSON like the capture shots) plus the exits at its
   frame edges. A scene `game/adventure/adventure.tscn` loads the world (or the chunks around the street) and
   switches cameras when the hero crosses an exit.
3. **Walking.** A `NavigationRegion3D` baked over the street's walkable surfaces (there is no navigation mesh
   in the project yet). Click → raycast into the world → path to the point. The hero moves in 3D; the camera
   stays fixed.
4. **Hero.** Start with a billboard sprite (a placeholder walk cycle, eight directions) whose size comes from
   the perspective automatically; try a low-poly 3D figure rendered at the same resolution as the alternative.
5. **Interaction.** Sierra-style verb cursor (walk, look, use, talk) cycling on right-click. "Look" at a
   building prints its template/OSM name from the building index; that alone makes the town feel inhabited.

**Verify:** captures at 320×200 of each room with the hero at near, middle, and far depth (walking behind a
lamppost or porch post correctly occluded), and a frame-rate figure for the live city at that resolution. Per
PLAN_v2's rule, verify in the real world scene at eye height, not only in a test scene.

## Phase 2 — decide A or B

Look at the prototype rooms side by side with a few Sierra screenshots. If the live render reads well enough,
continue with A (Phase 3A). If it looks too much like 3D, bake the same rooms (Phase 3B).

## Phase 3A — continue live (if A)

- A room editor mode: fly the existing player camera to a spot, press a key to save it as a room camera.
- Exits, per-room hero scale limits, and blocking volumes where the navmesh should not go.
- Game layer: inventory, dialogue, scripted events. A small framework of our own on top of the 3D world, or
  Escoria's 3D support if it fits.

## Phase 3B — bake rooms (if B)

- A bake tool built on `tools/capture.sh`: for each room camera, render the background at 320×200, the depth
  buffer, and a walk mask (the ground surfaces in a flat colour, everything else black), and write them next
  to a room JSON.
- An importer that turns each baked room into a Popochiu (or Escoria) room: background image, walkable
  polygon traced from the mask, props with baselines from the depth buffer for anything the hero passes
  behind, and hotspots from building ids.
- Re-bake on demand when the world changes.

---

## Open decisions

- **Palette:** VGA (256, dithered) or EGA (16, heavy dithering)? Try both in Phase 1.
- **Hero:** sprite art (needs an artist or generated frames) or a low-poly 3D figure?
- **Scope of the world:** the whole town as rooms, or a small, dense area (downtown) done well?
- **Interiors:** modelled, painted, or none.
- **Story:** the game needs one; the town is the setting.

## Dependencies

- Building facades (windows, doors, trim) from Building Composer, and the round trip of composed buildings
  back into the world, for close-range rooms to look inhabited.
- A navigation mesh over the walkable ground (new).
- The capture tooling (`tools/capture.sh`, `tools/capture/`) for Phase 3B's bake.
