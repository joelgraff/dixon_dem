#!/usr/bin/env python3
"""Builds the Dixon buildings "build-plan": chunked JSON of triangle soups +
collision hulls, consumed by game/buildings/tools/build_buildings.gd to bake
game/buildings/buildings.tscn. Mirrors the pipeline/roads/build_road_plan.py
convention. See docs/buildings_notes.md.

Run: cd pipeline/buildings && ../../.venv/bin/python build_building_plan.py
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common_buildings import (
    polygon_area_2d, polygon_centroid_2d, chunk_key, rng_for, PolyIndex, SegmentIndex,
)
from common_buildings import MeshBuild
import classify
import archetypes
import composed
import composer
import infill
import palette
import facade
import templates as building_templates
import footprints

from shapely.geometry import Polygon, LineString

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GAME_DATA = os.path.join(ROOT, "game", "data")
OUT_DIR = os.path.join(ROOT, "game", "buildings", "_build")
CHUNK_SIZE = 200.0


def load(name):
    with open(os.path.join(GAME_DATA, name)) as f:
        return json.load(f)


def footprint_coords(b):
    pts = [(p["x"], p["z"]) for p in b["footprint"]]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def convex_hull(coords):
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    hull = poly.convex_hull
    if hull.is_empty or hull.geom_type != "Polygon":
        return coords
    return list(hull.exterior.coords)[:-1]


# OSM building ids that game/landmarks/tools/build_landmarks.gd models itself. Keep in sync.
LANDMARK_OWNED_IDS = {
    897622746,    # Lee County Courthouse           -> lee_county_courthouse
    738208757,    # The Dixon: Historic Theatre     -> dixon_theatre
    554473285,    # Nachusa House                   -> nachusa_house
    1010774113,   # Dixon Memorial Arch             -> dixon_arch_complex
    554468528,    # Reagan Boyhood Home (visitor ctr footprint at the landmark position)
    554469190,    # Ronald Reagan Boyhood Home
}


def load_curated(osm_buildings):
    """Hand-traced footprints from the user's aerial (game/data/buildings_curated.json).
    Each record: {"id", "footprint": [{"x","z"}...], "height_m", "tags": {...}, optional
    "replaces": [osm ids]}. Records that list `replaces` remove those OSM footprints (merged or
    wrongly shaped ones) from the generic set -- handled here by filtering the caller's list
    in place is avoided; instead we return only the new records and mark replaced ids."""
    path = os.path.join(GAME_DATA, "buildings_curated.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    recs = data.get("buildings", [])
    replaced = set()
    for r in recs:
        replaced.update(r.get("replaces", []))
    if replaced:
        osm_buildings[:] = [b for b in osm_buildings if b.get("id") not in replaced]
    out = []
    for r in recs:
        if "footprint" not in r:
            continue
        fp = r["footprint"]
        pts = [{"x": p["x"], "z": p["z"]} if isinstance(p, dict) else {"x": p[0], "z": p[1]} for p in fp]
        if pts[0] != pts[-1]:
            pts.append(dict(pts[0]))
        out.append({"id": r["id"], "footprint": pts, "height_m": r.get("height_m"),
                    "tags": r.get("tags", {"building": "yes"}), "curated": True})
    return out



HOUSE_FORMS = {
    "side_gable", "front_gable", "gabled_ell", "foursquare",
    "bungalow", "cross_gable", "ranch",
}


def _build_one(arche, form, area, mb, mb_far, coords, ground_y, height_m, tags, rng, bid, road_idx, tmpl):
    """The template chooses the mesh. The old archetype is only a fallback."""
    tmpl = tmpl or {}
    from_composer = composed.load(bid) if composed.wanted(tmpl) else None
    if from_composer:
        return composed.build(mb, mb_far, coords, ground_y, from_composer)
    in_game = tmpl.get("compose")
    if isinstance(in_game, dict) and in_game.get("volumes"):
        return composer.build(mb, mb_far, coords, ground_y, in_game)
    form = form or tmpl.get("form")
    storeys = float(tmpl.get("storeys") or 1)
    measured_tall = bool(tmpl.get("height_reason")) and storeys >= 2
    giant = area > 1400 and not measured_tall

    if form in HOUSE_FORMS:
        return archetypes.build_residential_house(
            mb, mb_far, coords, ground_y, height_m, tags, rng, bid, road_idx, template=tmpl)
    if form == "garage" or (not form and arche == "garage"):
        return archetypes.build_garage(mb, mb_far, coords, ground_y, rng, bid)
    if form == "church_nave" or (not form and arche == "church"):
        return archetypes.build_church(mb, mb_far, coords, ground_y, rng, road_idx, template=tmpl)
    if form == "industrial" or (not form and arche == "industrial"):
        return archetypes.build_industrial(mb, mb_far, coords, ground_y, rng, road_idx, template=tmpl)
    if form == "civic_block" or (not form and arche == "institutional"):
        if giant:
            return archetypes.build_boxy_building(
                mb, mb_far, coords, ground_y, height_m, tags, rng, bid, is_bigbox=True)
        return archetypes.build_civic(mb, mb_far, coords, ground_y, rng, road_idx, template=tmpl)
    if form in ("party_wall_commercial", "one_story_store") or arche in (
        "downtown_commercial", "strip_commercial", "bigbox_retail",
    ):
        if giant or arche == "bigbox_retail" and not measured_tall:
            return archetypes.build_boxy_building(
                mb, mb_far, coords, ground_y, height_m, tags, rng, bid, is_bigbox=True)
        return archetypes.build_downtown_commercial(
            mb, mb_far, coords, ground_y, height_m, tags, rng, bid, template=tmpl)
    return archetypes.build_residential_house(
        mb, mb_far, coords, ground_y, height_m, tags, rng, bid, road_idx, template=tmpl)


def load_ms_footprints():
    """Microsoft ML building footprints, already clipped and de-duplicated against
    OSM/curated by pipeline/buildings/ms_footprints.py. OSM covers 707 footprints in the
    play area; this adds ~4,200 more, which is every residential block OSM never mapped."""
    path = os.path.join(ROOT, "game", "data", "buildings_ms.json")
    if not os.path.exists(path):
        return []
    recs = json.load(open(path)).get("buildings", [])
    print(f"microsoft footprints: {len(recs)}")
    return recs


def main(only_chunk=None):
    t0 = time.time()
    buildings_data = load("buildings.json")["buildings"]
    curated = load_curated(buildings_data)       # may drop OSM footprints listed in "replaces"
    ms_records = load_ms_footprints()            # ML footprints for everything OSM never mapped
    # outlines corrected in Building Composer's footprint editor (game/data/footprint_overrides/)
    footprint_overrides = footprints.load_overrides()
    for records, source in ((buildings_data, "osm"), (curated, "curated"), (ms_records, "ms")):
        footprints.override_records(records, source, footprint_overrides)
    print(f"footprint overrides: {len(footprint_overrides)}")
    roads_data = load("roads.json")
    water_data = load("water.json")
    landuse_data = load("landuse.json")
    rails_data = load("rails.json")
    origin_json = load("world_origin.json")

    print(f"loaded data in {time.time()-t0:.1f}s")

    # -- exclusion index for infill (existing footprints, water, rails, non-residential landuse)
    excl = PolyIndex(cell=80.0)
    for b in buildings_data + curated + ms_records:
        coords = footprint_coords(b)
        if len(coords) >= 3:
            excl.add(coords)
    for area in landuse_data["areas"]:
        tags = area.get("tags", {})
        if tags.get("landuse") == "residential":
            continue  # residential-zoned land is fair game for infill
        coords = [(p["x"], p["z"]) for p in area["polygon"]]
        if len(coords) >= 3:
            excl.add(coords)
    for reach in water_data["reaches"]:
        coords = [(p["x"], p["z"]) for p in reach["polygon"]]
        if len(coords) >= 3:
            excl.add(coords)
    for stream in water_data["streams"]:
        verts = stream["vertices"]
        if len(verts) < 2:
            continue
        line = LineString([(v["x"], v["z"]) for v in verts])
        buf = line.buffer(5.0)
        if not buf.is_empty:
            excl.add(list(buf.exterior.coords)[:-1])
    for way in rails_data["ways"]:
        verts = way["vertices"]
        if len(verts) < 2:
            continue
        line = LineString([(v["x"], v["z"]) for v in verts])
        buf = line.buffer(7.0)
        if not buf.is_empty:
            excl.add(list(buf.exterior.coords)[:-1])
    print(f"exclusion index built ({len(excl.polys)} polys) in {time.time()-t0:.1f}s")

    # -- road segment index (all roads) for house front-orientation
    road_idx = SegmentIndex(cell=100.0)
    for way in roads_data["ways"]:
        verts = way["vertices"]
        for i in range(len(verts) - 1):
            a, b = verts[i], verts[i + 1]
            road_idx.add(a["x"], a["z"], b["x"], b["z"])

    # -- ground height sampler for infill placement
    r32_path = os.path.join(GAME_DATA, origin_json["heightmaps"]["play"]["road_conformed_file"])
    sampler = infill.Sampler(origin_json, r32_path)

    infill_records = infill.generate_infill(roads_data, excl, sampler)
    print(f"infill: {len(infill_records)} records in {time.time()-t0:.1f}s")

    # Only footprints that a landmark scene actually models are skipped. buildings.json tags
    # EVERY footprint near a landmark with landmark_id (e.g. First Baptist Church and an
    # unnamed 439 m2 building were tagged "dixon_theatre"), but landmarks/build_landmarks.gd
    # builds just one building per landmark -- so the rest were silently dropped and left
    # empty lots (user report 2026-09-20: empty lot north of the theatre).
    owned = [b for b in buildings_data if b.get("id") in LANDMARK_OWNED_IDS]
    generic = [b for b in buildings_data if b.get("id") not in LANDMARK_OWNED_IDS]
    all_records = generic + curated + ms_records + infill_records
    print(f"total to build: {len(all_records)} (landmark-owned skipped: {len(owned)}; "
          f"curated {len(curated)}; microsoft {len(ms_records)}; infill {len(infill_records)})")
    overrides = building_templates.load_overrides(os.path.join(GAME_DATA, "building_overrides.json"))
    template_of = building_templates.resolve_batch(all_records, road_idx, overrides)
    footprints.apply_override_porches(all_records, template_of, overrides)
    print(f"templates resolved: {len(template_of)}")

    chunks = {}  # (cx,cz) -> {"near": MeshBuild, "far": MeshBuild, "collisions": []}
    counts = {}

    def chunk_for(x, z):
        key = chunk_key(x, z, CHUNK_SIZE)
        c = chunks.get(key)
        if c is None:
            c = {"near": MeshBuild(), "far": MeshBuild(), "collisions": []}
            chunks[key] = c
        return c

    for b in all_records:
        coords = footprint_coords(b)
        if len(coords) < 3:
            continue
        area = abs(polygon_area_2d(coords))
        if area < 4.0:
            continue
        cx, cz = polygon_centroid_2d(coords)
        if only_chunk and chunk_key(cx, cz, CHUNK_SIZE) != only_chunk:
            continue
        tags = b.get("tags", {}) or {}
        arche = classify.classify(tags, cx, cz, area)
        counts[arche] = counts.get(arche, 0) + 1
        # Resample ground level from the same road-conformed heightmap terrain.gd
        # renders from (rather than trusting buildings.json's own ground_y_min,
        # which may have been sampled from a slightly different pass) so
        # buildings sit flush with the now-live terrain mesh.
        ground_y = facade.pick_ground(coords, sampler, (cx, cz))
        height_m = b.get("height_m")
        bid = b.get("id")
        rng = rng_for("bld", bid)
        c = chunk_for(cx, cz)
        # Tell the mesh builders which point counts as "inside" this building, so
        # vertical faces can be oriented outward by geometry rather than by the
        # caller's ring-winding convention (see common_buildings._orient).
        c["near"].set_outward_ref(cx, cz)
        c["far"].set_outward_ref(cx, cz)
        flip = bool((template_of.get(bid) or {}).get("flip_normals"))
        c["near"].set_flip_outward(flip)
        c["far"].set_flip_outward(flip)
        mb, mb_far = c["near"], c["far"]

        try:
            tmpl = template_of.get(bid) or {}
            form = tmpl.get("form")
            res = _build_one(arche, form, area, mb, mb_far, coords, ground_y, height_m,
                             tags, rng, bid, road_idx, tmpl)
        except Exception as e:
            print(f"  ! building {bid} ({arche}) failed: {e}")
            res = None

        if res:
            # Close the gap under the building where terrain falls away (see facade.terrain_skirt).
            low = facade.terrain_skirt(c["near"], res["hull"], res["y0"], sampler)
            hull = convex_hull(res["hull"])
            collision = {
                "id": bid,
                "hull": [[round(p[0], 2), round(p[1], 2)] for p in hull],
                "y0": round(min(res["y0"], low) - 0.05, 2),
                "y1": round(res["y1"], 2),
            }
            if res.get("faces"):
                # a walk-in composed building collides with its surfaces, not its hull
                collision["faces"] = [round(v, 3) for v in res["faces"]]
            c["collisions"].append(collision)

    print("archetype counts:", counts)

    os.makedirs(OUT_DIR, exist_ok=True)
    _write_template_index(all_records, template_of)
    if only_chunk is None:
        for f in os.listdir(OUT_DIR):
            if f.startswith("chunk_") and f.endswith(".json"):
                os.remove(os.path.join(OUT_DIR, f))

    palette.write_manifest()  # Building Composer's copy of the palette
    manifest = {
        "chunk_size": CHUNK_SIZE,
        "materials": palette.MATERIALS,
        "far_material": "res://buildings/materials/building_far.tres",
        "chunks": [],
    }
    total_tris_near = 0
    total_tris_far = 0
    for (cx, cz), c in chunks.items():
        near_json = c["near"].to_json()
        far_json = c["far"].to_json()
        if not near_json and not far_json and not c["collisions"]:
            continue
        # Re-express every vertex/hull position relative to the chunk's own
        # world-space center, so the baked MeshInstance3D/StaticBody3D gets a
        # REAL transform (position = chunk center) instead of sitting at the
        # scene origin with raw world-space vertices baked in. A node at
        # identity transform with geometry thousands of meters away breaks
        # Godot's visibility_range (measured from the node's transform
        # origin, not the mesh AABB) and risks broad-phase culling structures
        # that key off the instance's registered position -- see
        # docs/buildings_notes.md "Chunk-local origin fix" (2026-09-19 bug).
        origin_x = (cx + 0.5) * CHUNK_SIZE
        origin_z = (cz + 0.5) * CHUNK_SIZE
        for g in near_json.values():
            g["verts"] = [(v[0] - origin_x, v[1], v[2] - origin_z, v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11])
                          for v in g["verts"]]
            total_tris_near += len(g["indices"]) // 3
        for g in far_json.values():
            g["verts"] = [(v[0] - origin_x, v[1], v[2] - origin_z, v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11])
                          for v in g["verts"]]
            total_tris_far += len(g["indices"]) // 3
        for col in c["collisions"]:
            col["hull"] = [[round(p[0] - origin_x, 2), round(p[1] - origin_z, 2)] for p in col["hull"]]
            if "faces" in col:
                shift = (origin_x, 0.0, origin_z)
                col["faces"] = [round(v - shift[i % 3], 3) for i, v in enumerate(col["faces"])]

        fname = f"chunk_{cx}_{cz}.json"
        with open(os.path.join(OUT_DIR, fname), "w") as f:
            json.dump({"near": near_json, "far": far_json, "collisions": c["collisions"]}, f)
        manifest["chunks"].append({"cx": cx, "cz": cz, "file": fname,
                                    "origin_x": origin_x, "origin_z": origin_z,
                                    "x0": cx * CHUNK_SIZE, "z0": cz * CHUNK_SIZE,
                                    "x1": (cx + 1) * CHUNK_SIZE, "z1": (cz + 1) * CHUNK_SIZE})

    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    if only_chunk is not None and os.path.exists(manifest_path):
        previous = json.load(open(manifest_path))
        kept = [entry for entry in previous.get("chunks", [])
                if (entry["cx"], entry["cz"]) != only_chunk]
        manifest["chunks"] = kept + manifest["chunks"]
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=1)

    print(f"wrote {len(manifest['chunks'])} chunks, {total_tris_near} near tris, {total_tris_far} far tris, "
          f"{sum(len(c['collisions']) for c in chunks.values())} collision shapes")
    print(f"done in {time.time()-t0:.1f}s")


def _write_template_index(records, template_of):
    """Compact lookup the in-game editor reads. Not the mesh."""
    out = {}
    for record in records:
        bid = record.get("id")
        template = template_of.get(bid)
        if not template:
            continue
        coords = footprint_coords(record)
        if len(coords) < 3:
            continue
        center = polygon_centroid_2d(coords)
        cx, cz = chunk_key(center[0], center[1], CHUNK_SIZE)
        out[str(bid)] = {
            "form": template["form"],
            "storeys": template["storeys"],
            "roof": template["roof"],
            "roof_axis": template["roof_axis"],
            "porch": template["porch"],
            "material": template["material"],
            "dressing": template["dressing"],
            "ground": template.get("ground") or "normal",
            "awnings": template.get("awnings") or "some",
            "color": template.get("color") or "auto",
            "flip_normals": bool(template.get("flip_normals")),
            "x": round(center[0], 1),
            "z": round(center[1], 1),
            "cx": cx,
            "cz": cz,
        }
    with open(os.path.join(OUT_DIR, "template_index.json"), "w") as handle:
        json.dump(out, handle)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk", default="", help="cx,cz — rebuild only that 200 m chunk")
    args = parser.parse_args()
    only = None
    if args.chunk:
        cx_s, cz_s = args.chunk.split(",")
        only = (int(cx_s), int(cz_s))
    main(only)
