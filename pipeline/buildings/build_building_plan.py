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
import infill
import palette

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


def main():
    t0 = time.time()
    buildings_data = load("buildings.json")["buildings"]
    roads_data = load("roads.json")
    water_data = load("water.json")
    landuse_data = load("landuse.json")
    rails_data = load("rails.json")
    origin_json = load("world_origin.json")

    print(f"loaded data in {time.time()-t0:.1f}s")

    # -- exclusion index for infill (existing footprints, water, rails, non-residential landuse)
    excl = PolyIndex(cell=80.0)
    for b in buildings_data:
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

    all_records = [b for b in buildings_data if not b.get("landmark_id")] + infill_records
    n_landmark_skipped = sum(1 for b in buildings_data if b.get("landmark_id"))
    print(f"total to build: {len(all_records)} (skipped {n_landmark_skipped} landmark footprints)")

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
        tags = b.get("tags", {}) or {}
        arche = classify.classify(tags, cx, cz, area)
        counts[arche] = counts.get(arche, 0) + 1
        # Resample ground level from the same road-conformed heightmap terrain.gd
        # renders from (rather than trusting buildings.json's own ground_y_min,
        # which may have been sampled from a slightly different pass) so
        # buildings sit flush with the now-live terrain mesh.
        ground_y = sampler.sample(cx, cz)
        height_m = b.get("height_m")
        bid = b.get("id")
        rng = rng_for("bld", bid)
        c = chunk_for(cx, cz)
        mb, mb_far = c["near"], c["far"]

        try:
            if arche == "downtown_commercial":
                res = archetypes.build_downtown_commercial(mb, mb_far, coords, ground_y, height_m, tags, rng, bid)
            elif arche == "church":
                res = archetypes.build_boxy_building(mb, mb_far, coords, ground_y, height_m, tags, rng, bid, is_church=True)
            elif arche == "institutional":
                res = archetypes.build_boxy_building(mb, mb_far, coords, ground_y, height_m, tags, rng, bid)
            elif arche == "industrial":
                res = archetypes.build_boxy_building(mb, mb_far, coords, ground_y, height_m, tags, rng, bid, is_industrial=True)
            elif arche == "bigbox_retail":
                res = archetypes.build_boxy_building(mb, mb_far, coords, ground_y, height_m, tags, rng, bid, is_bigbox=True)
            elif arche == "strip_commercial":
                res = archetypes.build_downtown_commercial(mb, mb_far, coords, ground_y, height_m, tags, rng, bid)
            elif arche == "garage":
                res = archetypes.build_garage(mb, mb_far, coords, ground_y, rng, bid)
            else:
                res = archetypes.build_residential_house(mb, mb_far, coords, ground_y, height_m, tags, rng, bid, road_idx)
        except Exception as e:
            print(f"  ! building {bid} ({arche}) failed: {e}")
            res = None

        if res:
            hull = convex_hull(res["hull"])
            c["collisions"].append({
                "hull": [[round(p[0], 2), round(p[1], 2)] for p in hull],
                "y0": round(res["y0"], 2),
                "y1": round(res["y1"], 2),
            })

    print("archetype counts:", counts)

    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.endswith(".json"):
            os.remove(os.path.join(OUT_DIR, f))

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
        for g in near_json.values():
            total_tris_near += len(g["indices"]) // 3
        for g in far_json.values():
            total_tris_far += len(g["indices"]) // 3
        fname = f"chunk_{cx}_{cz}.json"
        with open(os.path.join(OUT_DIR, fname), "w") as f:
            json.dump({"near": near_json, "far": far_json, "collisions": c["collisions"]}, f)
        manifest["chunks"].append({"cx": cx, "cz": cz, "file": fname,
                                    "x0": cx * CHUNK_SIZE, "z0": cz * CHUNK_SIZE,
                                    "x1": (cx + 1) * CHUNK_SIZE, "z1": (cz + 1) * CHUNK_SIZE})

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)

    print(f"wrote {len(manifest['chunks'])} chunks, {total_tris_near} near tris, {total_tris_far} far tris, "
          f"{sum(len(c['collisions']) for c in chunks.values())} collision shapes")
    print(f"done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
