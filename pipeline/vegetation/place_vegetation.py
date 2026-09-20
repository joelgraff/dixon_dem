#!/usr/bin/env python3
"""Builds the Dixon vegetation placement plan: deterministic tree/shrub
instance lists + a grass density/type raster mask, consumed by
game/vegetation/vegetation.gd to build chunked MultiMesh vegetation.

Reads game/data/{landuse,trees,roads,buildings,water,rails,world_origin}.json
+ the road-conformed heightmap. Writes into game/vegetation/data/ (this
workstream's own folder — never game/data/, which belongs to the data
pipeline workstream).

Run: cd pipeline/vegetation && ../../.venv/bin/python place_vegetation.py
See docs/vegetation_notes.md for the placement rules in prose.
"""
import json
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Point, Polygon, LineString, box
from shapely.ops import unary_union
from shapely.prepared import prep

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common as pc
from veg_common import Heightmap, HashGrid, seeded_rng, walk_polyline, load_json

OUT_DIR = os.path.join(pc.ROOT, "game", "vegetation", "data")
os.makedirs(OUT_DIR, exist_ok=True)

SEED = 20260917  # deterministic master seed

# --- Road geometry constants (mirrors pipeline/roads/build_road_plan.py so
# our parkway strip lines up with the sidewalk/curb that team builds; we
# duplicate the numbers rather than importing their module to keep the two
# workstreams' pipelines decoupled). ---
CURB_WIDTH = 0.12
GUTTER_WIDTH = 0.35
PARKWAY_GAP = 2.0
SIDEWALK_W_RESIDENTIAL = 1.7
SIDEWALK_W_DOWNTOWN = 3.6
DOWNTOWN_STREET_WORDS = ("galena", "1st", "first", "2nd", "second", "3rd", "third", "hennepin", "peoria")
DOWNTOWN_BOUNDS = (1330.0, -1780.0, 1920.0, -1030.0)  # x0,z0,x1,z1

STREET_TREE_HIGHWAYS = {"residential", "tertiary", "secondary", "unclassified", "living_street"}
MINOR_HIGHWAYS = {"service", "track", "footway", "cycleway", "path", "pedestrian", "steps"}

DOWNTOWN_CENTER = (1691.9, -1233.5)  # courthouse, used as the "old core" anchor


def is_downtown_way(tags, sample_pt):
    name = (tags.get("name") or "").lower()
    x, z = sample_pt
    x0, z0, x1, z1 = DOWNTOWN_BOUNDS
    in_box = x0 <= x <= x1 and z0 <= z <= z1
    if any(w in name for w in DOWNTOWN_STREET_WORDS) and in_box:
        return True
    return False


# ---------------------------------------------------------------------------
# Species table
# ---------------------------------------------------------------------------
# form: deciduous | conifer | hedge | shrub  (drives which Godot mesh builder runs)
SPECIES = {
    "bur_oak":          dict(form="deciduous", h=(14, 24), r=(7, 11)),
    "white_oak":        dict(form="deciduous", h=(14, 23), r=(7, 10)),
    "silver_maple":     dict(form="deciduous", h=(12, 22), r=(6, 10)),
    "sugar_maple":      dict(form="deciduous", h=(12, 20), r=(6, 9)),
    "honey_locust":     dict(form="deciduous", h=(9, 16), r=(4, 7)),
    "cottonwood":       dict(form="deciduous", h=(16, 26), r=(7, 11)),
    "american_elm":     dict(form="deciduous", h=(13, 22), r=(6, 9)),
    "hackberry":        dict(form="deciduous", h=(10, 17), r=(5, 8)),
    "willow":           dict(form="deciduous", h=(7, 12), r=(5, 9)),
    "white_pine":       dict(form="conifer", h=(12, 20), r=(3, 5)),
    "blue_spruce":      dict(form="conifer", h=(8, 14), r=(2.5, 4)),
    "arborvitae":       dict(form="hedge", h=(2, 3.5), r=(0.6, 1)),
    "shrub_foundation": dict(form="shrub", h=(0.6, 1.3), r=(0.5, 0.9)),
    "shrub_wild":       dict(form="shrub", h=(0.8, 1.8), r=(0.6, 1.2)),
    "cattail":          dict(form="shrub", h=(1.0, 1.6), r=(0.3, 0.5)),
}

MIX_STREET = [("american_elm", 35), ("hackberry", 30), ("honey_locust", 30), ("sugar_maple", 5)]
MIX_DOWNTOWN = [("honey_locust", 60), ("hackberry", 40)]
MIX_YARD = [("bur_oak", 16), ("white_oak", 14), ("silver_maple", 14), ("sugar_maple", 16),
            ("honey_locust", 12), ("american_elm", 8), ("hackberry", 6),
            ("white_pine", 7), ("blue_spruce", 7)]
MIX_PARK = [("bur_oak", 20), ("white_oak", 16), ("sugar_maple", 18), ("silver_maple", 12),
            ("honey_locust", 10), ("american_elm", 10), ("hackberry", 6),
            ("white_pine", 4), ("blue_spruce", 4)]
MIX_WOOD_RIPARIAN = [("cottonwood", 34), ("silver_maple", 26), ("willow", 18),
                      ("american_elm", 16), ("hackberry", 6)]
MIX_WOOD_GENERAL = [("bur_oak", 26), ("white_oak", 22), ("hackberry", 16),
                     ("american_elm", 18), ("sugar_maple", 18)]
MIX_FOUNDATION_SHRUB = [("shrub_foundation", 78), ("arborvitae", 22)]


def weighted_choice(rng, mix):
    total = sum(w for _, w in mix)
    r = rng.random() * total
    acc = 0.0
    for name, w in mix:
        acc += w
        if r <= acc:
            return name
    return mix[-1][0]


# ---------------------------------------------------------------------------
# Load source data
# ---------------------------------------------------------------------------
print("loading game/data/*.json ...")
landuse = load_json("landuse.json")["areas"]
trees_osm = load_json("trees.json")["points"]
roads = load_json("roads.json")
ways = roads["ways"]
junction_nodes = roads["junction_nodes"]
buildings = load_json("buildings.json")["buildings"]
water = load_json("water.json")
rails = load_json("rails.json")

hm = Heightmap()


def sample_y(x, z):
    return hm.sample(x, z)


# ---------------------------------------------------------------------------
# Play-area clip box. Every game/data/*.json layer is fetched from OSM with
# only a 500m *bbox* margin, but Overpass returns each way/relation's FULL
# unclipped geometry if any part touches that box -- e.g. rails.json contains
# a mainline way ~66km long, roads.json spans x down to -10756. Left
# unclipped, placement (esp. line-walks: streets/rails) scatters vegetation
# far outside the playable square. Clip every line/point layer to the play
# area (+ small margin) before placing anything.
# ---------------------------------------------------------------------------
wo = pc.load_world_origin()
_size_m = wo["size_m"]
_CLIP_MARGIN = 20.0
PLAY_BOX = box(-_CLIP_MARGIN, -_size_m - _CLIP_MARGIN, _size_m + _CLIP_MARGIN, _CLIP_MARGIN)


def clip_line_parts(line):
    """Intersect a LineString with PLAY_BOX; return a list of LineStrings."""
    try:
        clipped = line.intersection(PLAY_BOX)
    except Exception:
        return []
    if clipped.is_empty:
        return []
    if clipped.geom_type == "LineString":
        return [clipped]
    if clipped.geom_type == "MultiLineString":
        return list(clipped.geoms)
    if clipped.geom_type == "GeometryCollection":
        return [g for g in clipped.geoms if g.geom_type == "LineString"]
    return []


def clip_poly_parts(poly):
    try:
        clipped = poly.intersection(PLAY_BOX)
    except Exception:
        return []
    if clipped.is_empty:
        return []
    if clipped.geom_type == "Polygon":
        return [clipped]
    if clipped.geom_type == "MultiPolygon":
        return list(clipped.geoms)
    if clipped.geom_type == "GeometryCollection":
        return [g for g in clipped.geoms if g.geom_type == "Polygon"]
    return []


def in_play_box(x, z):
    return -_CLIP_MARGIN <= x <= _size_m + _CLIP_MARGIN and -_size_m - _CLIP_MARGIN <= z <= _CLIP_MARGIN


# ---------------------------------------------------------------------------
# Build shapely geometry
# ---------------------------------------------------------------------------
print("building geometry ...")


def poly_from_ring(ring):
    pts = [(p["x"], p["z"]) for p in ring]
    if len(pts) < 3:
        return None
    try:
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area < 1.0:
            return None
        return poly
    except Exception:
        return None


landuse_polys = []  # (poly, tags)
for a in landuse:
    poly = poly_from_ring(a["polygon"])
    if poly:
        for part in clip_poly_parts(poly):
            if part.area >= 1.0:
                landuse_polys.append((part, a.get("tags", {})))

PARK_LEISURE = {"park", "nature_reserve", "playground", "recreation_ground"}
PITCH_LEISURE = {"pitch"}
COMMERCIAL_LANDUSE = {"commercial", "retail", "industrial", "brownfield"}
OPEN_GRASS_NATURAL = {"grassland", "wetland"}

park_polys, wood_polys, commercial_polys, residential_polys = [], [], [], []
open_grass_polys, pitch_polys, cemetery_polys = [], [], []
for poly, tags in landuse_polys:
    leisure = tags.get("leisure")
    landuse_tag = tags.get("landuse")
    natural = tags.get("natural")
    if leisure in PARK_LEISURE:
        park_polys.append((poly, tags))
    elif leisure in PITCH_LEISURE:
        pitch_polys.append((poly, tags))
    elif natural == "wood":
        wood_polys.append((poly, tags))
    elif landuse_tag == "cemetery":
        cemetery_polys.append((poly, tags))
    elif landuse_tag in COMMERCIAL_LANDUSE:
        commercial_polys.append((poly, tags))
    elif landuse_tag == "residential":
        residential_polys.append((poly, tags))
    elif natural in OPEN_GRASS_NATURAL:
        open_grass_polys.append((poly, tags))

commercial_union = unary_union([p for p, _ in commercial_polys]) if commercial_polys else Polygon()
commercial_prep = prep(commercial_union) if not commercial_union.is_empty else None

# Buildings. Prefer the buildings workstream's own BAKED collision hulls
# (game/buildings/_build/chunk_*.json -- read-only cross-workstream read,
# see docs/buildings_notes.md) over game/data/buildings.json's raw OSM
# footprints: the bake includes ~900 procedurally-infilled houses/garages on
# blocks OSM never mapped (game/data/buildings.json only has the original
# 707), and the hull is already the exact as-built rectangle (houses are
# simplified to their min-rotated-rect there). Falls back to
# game/data/buildings.json alone if the bake hasn't been run yet.
building_recs = []  # dict: poly, area, is_house
_build_dir = os.path.join(pc.ROOT, "game", "buildings", "_build")
_hull_count = 0
if os.path.isdir(_build_dir):
    import glob
    for chunk_path in glob.glob(os.path.join(_build_dir, "chunk_*.json")):
        try:
            chunk = json.load(open(chunk_path))
        except Exception:
            continue
        for c in chunk.get("collisions", []):
            hull = c.get("hull")
            if not hull or len(hull) < 3:
                continue
            poly = poly_from_ring([{"x": p[0], "z": p[1]} for p in hull])
            if not poly or not poly.intersects(PLAY_BOX):
                continue
            _hull_count += 1
            is_house = (
                poly.area <= 550.0
                and (commercial_prep is None or not commercial_prep.intersects(poly.centroid))
            )
            building_recs.append(dict(poly=poly, area=poly.area, is_house=is_house))
print(f"  loaded {_hull_count} baked building hulls from game/buildings/_build/ (includes procedural infill)"
      if _hull_count else "  no buildings bake found, falling back to buildings.json")

if not building_recs:
    for b in buildings:
        poly = poly_from_ring(b["footprint"])
        if not poly or not poly.intersects(PLAY_BOX):
            continue
        is_house = (
            b.get("tags", {}).get("landmark_id") is None
            and poly.area <= 550.0
            and (commercial_prep is None or not commercial_prep.intersects(poly.centroid))
        )
        building_recs.append(dict(poly=poly, area=poly.area, is_house=is_house))

# Landmark footprints (buildings.json entries the buildings team explicitly
# skipped, left for the landmarks team) still get a placement-exclusion
# buffer even if nothing is built there yet, so trees don't pre-empt that
# ground.
landmark_polys = []
for b in buildings:
    if b.get("tags", {}).get("landmark_id"):
        poly = poly_from_ring(b["footprint"])
        if poly and poly.intersects(PLAY_BOX):
            landmark_polys.append(poly)

buildings_tight = unary_union([r["poly"].buffer(0.8) for r in building_recs] +
                               [p.buffer(1.0) for p in landmark_polys])
buildings_tight_prep = prep(buildings_tight)

# Water
water_reach_polys = []
for r in water.get("reaches", []):
    poly = poly_from_ring(r["polygon"])
    if poly:
        water_reach_polys.extend(p for p in clip_poly_parts(poly) if p.area >= 1.0)
stream_lines = []
for s in water.get("streams", []):
    pts = [(v["x"], v["z"]) for v in s["vertices"]]
    if len(pts) >= 2:
        stream_lines.extend(clip_line_parts(LineString(pts)))

water_excl_parts = [p.buffer(0.5) for p in water_reach_polys] + [l.buffer(2.0) for l in stream_lines]
water_excl = unary_union(water_excl_parts) if water_excl_parts else Polygon()
water_excl_prep = prep(water_excl) if not water_excl.is_empty else None

water_near_ref = unary_union(water_reach_polys) if water_reach_polys else Polygon()
water_near_buffer = water_near_ref.buffer(35.0) if not water_near_ref.is_empty else Polygon()
water_near_prep = prep(water_near_buffer) if not water_near_buffer.is_empty else None

# Riverbank ring (for tall grass + cattails) — outside the water polygon, within 10m of it
riverbank_ring = None
if not water_near_ref.is_empty:
    riverbank_ring = water_near_ref.buffer(10.0).difference(water_near_ref)

# Rails
rail_lines = []
for w in rails.get("ways", rails if isinstance(rails, list) else []):
    verts = w.get("vertices") if isinstance(w, dict) else None
    if verts:
        pts = [(v["x"], v["z"]) for v in verts]
        if len(pts) >= 2:
            rail_lines.extend(clip_line_parts(LineString(pts)))
rails_excl = unary_union([l.buffer(2.5) for l in rail_lines]) if rail_lines else Polygon()
rails_excl_prep = prep(rails_excl) if not rails_excl.is_empty else None

# Road ROW (curb+parkway+sidewalk both sides) — used to keep non-street
# vegetation off roads/sidewalks; NOT used for street-tree slot validation
# (those points sit inside this by construction).
road_row_polys = []
road_lines = []  # (LineString, tags, half_width)
for w in ways:
    tags = w.get("tags", {})
    pts = [(v["x"], v["z"]) for v in w["vertices"]]
    if len(pts) < 2:
        continue
    full_line = LineString(pts)
    if not full_line.intersects(PLAY_BOX):
        continue
    hw = (tags.get("width_m") or 6.0) / 2.0
    hwy = tags.get("highway")
    for line in clip_line_parts(full_line):
        if line.length < 1.0:
            continue
        road_lines.append((line, tags, hw))
        mid = line.interpolate(0.5, normalized=True)
        downtown = is_downtown_way(tags, (mid.x, mid.y))
        if hwy in MINOR_HIGHWAYS:
            row_half = hw + 2.0
        else:
            sw = SIDEWALK_W_DOWNTOWN if downtown else SIDEWALK_W_RESIDENTIAL
            parkway = 0.0 if downtown else PARKWAY_GAP
            row_half = hw + CURB_WIDTH + parkway + sw
        try:
            road_row_polys.append(line.buffer(row_half, cap_style=2))
        except Exception:
            pass

road_row_union = unary_union(road_row_polys) if road_row_polys else Polygon()
road_row_prep = prep(road_row_union)

# Junction points (for street-tree gap-at-intersections)
junction_pts = [(j["x"], j["z"]) for j in junction_nodes if in_play_box(j["x"], j["z"])]

# Unified "hard exclusion" for park/wood/downtown-planter/cattail/rail-weed placement
hard_excl = unary_union([g for g in [buildings_tight, road_row_union, water_excl, rails_excl] if g and not g.is_empty])
hard_excl_prep = prep(hard_excl)


def blocked(x, z):
    p = Point(x, z)
    return hard_excl_prep.contains(p)


def near_water(x, z):
    if water_near_prep is None:
        return False
    return water_near_prep.contains(Point(x, z))


def dist_to_downtown_core(x, z):
    return math.hypot(x - DOWNTOWN_CENTER[0], z - DOWNTOWN_CENTER[1])


# ---------------------------------------------------------------------------
# Output accumulators
# ---------------------------------------------------------------------------
trees_out = []
shrubs_out = []
grid_trees = HashGrid(cell_size=6.0)
grid_shrubs = HashGrid(cell_size=3.0)


def add_tree(x, z, species, category, min_spacing, rng):
    if not grid_trees.is_far_enough(x, z, min_spacing):
        return False
    if blocked(x, z) and category not in ("street", "osm", "downtown"):
        return False
    spec = SPECIES[species]
    h = rng.uniform(*spec["h"])
    r = rng.uniform(*spec["r"])
    y = sample_y(x, z)
    trees_out.append(dict(
        x=round(x, 2), y=round(y, 2), z=round(z, 2),
        species=species, category=category,
        height_m=round(h, 2), canopy_r_m=round(r, 2),
        rot_deg=round(rng.uniform(0, 360), 1),
        seed=rng.randint(0, 2 ** 31 - 1),
    ))
    grid_trees.insert(x, z)
    return True


def add_shrub(x, z, species, category, min_spacing, rng):
    if not grid_shrubs.is_far_enough(x, z, min_spacing):
        return False
    spec = SPECIES[species]
    h = rng.uniform(*spec["h"])
    r = rng.uniform(*spec["r"])
    y = sample_y(x, z)
    shrubs_out.append(dict(
        x=round(x, 2), y=round(y, 2), z=round(z, 2),
        species=species, category=category,
        height_m=round(h, 2), canopy_r_m=round(r, 2),
        rot_deg=round(rng.uniform(0, 360), 1),
        seed=rng.randint(0, 2 ** 31 - 1),
    ))
    grid_shrubs.insert(x, z)
    return True


# 1. OSM explicit trees (keep, always) -------------------------------------
print("placing OSM trees.json points ...")
for t in trees_osm:
    if not in_play_box(t["x"], t["z"]):
        continue
    rng = seeded_rng("osm", t["id"])
    species = t.get("species")
    if not species or species not in SPECIES:
        if near_water(t["x"], t["z"]):
            species = weighted_choice(rng, MIX_WOOD_RIPARIAN)
        else:
            species = weighted_choice(rng, MIX_PARK)
    add_tree(t["x"], t["z"], species, "osm", 4.0, rng)

# 2. Street trees ------------------------------------------------------------
print("placing street trees ...")
n_street = 0
for line, tags, hw in road_lines:
    hwy = tags.get("highway")
    if hwy not in STREET_TREE_HIGHWAYS or tags.get("bridge"):
        continue
    pts = list(line.coords)
    mid = line.interpolate(0.5, normalized=True)
    downtown = is_downtown_way(tags, (mid.x, mid.y))
    way_seed = seeded_rng("street", tags.get("name"), round(pts[0][0]), round(pts[0][1]))
    if downtown:
        offset = hw + CURB_WIDTH + 0.9
        spacing = 22.0
        keep_prob = 0.30
        mix = MIX_DOWNTOWN
        size_scale = 0.55
    else:
        offset = hw + CURB_WIDTH + PARKWAY_GAP * 0.5
        spacing = 12.5
        keep_prob = 0.85
        mix = MIX_STREET
        size_scale = 1.0
    for x, z, tx, tz, d in walk_polyline(pts, spacing, 0.25, way_seed):
        nx, nz = -tz, tx  # left normal
        for side in (1.0, -1.0):
            px, pz = x + nx * offset * side, z + nz * offset * side
            rng = seeded_rng("street", tags.get("name"), round(px, 1), round(pz, 1))
            if rng.random() > keep_prob:
                continue
            if any(math.hypot(px - jx, pz - jz) < 7.5 for jx, jz in junction_pts
                   if abs(px - jx) < 8 and abs(pz - jz) < 8):
                continue
            if buildings_tight_prep.contains(Point(px, pz)) or (water_excl_prep and water_excl_prep.contains(Point(px, pz))):
                continue
            species = weighted_choice(rng, mix)
            spec = SPECIES[species]
            h = rng.uniform(*spec["h"]) * size_scale
            r = rng.uniform(*spec["r"]) * size_scale
            if add_tree(px, pz, species, "downtown" if downtown else "street", 6.0, rng):
                trees_out[-1]["height_m"] = round(h, 2)
                trees_out[-1]["canopy_r_m"] = round(r, 2)
                n_street += 1
print(f"  {n_street} street/downtown trees")

# 3. Yard trees + foundation shrubs -----------------------------------------
print("placing yard trees + foundation shrubs ...")
n_yard, n_found = 0, 0
for rec in building_recs:
    if not rec["is_house"]:
        continue
    poly = rec["poly"]
    cx, cz = poly.centroid.x, poly.centroid.y
    core_dist = dist_to_downtown_core(cx, cz)
    if core_dist < 600:
        age_bias, tree_count_choices = 1.25, (2, 3, 3)
    elif core_dist < 1200:
        age_bias, tree_count_choices = 1.0, (1, 2, 2)
    else:
        age_bias, tree_count_choices = 0.8, (0, 1, 2)
    rng = seeded_rng("yard", round(cx, 1), round(cz, 1))
    n_trees = rng.choice(tree_count_choices)
    bbox = poly.bounds
    reach = max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * 0.5 + rng.uniform(4.0, 9.0)
    attempts = 0
    placed = 0
    while placed < n_trees and attempts < 12:
        attempts += 1
        ang = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(3.5, reach)
        px, pz = cx + math.cos(ang) * dist, cz + math.sin(ang) * dist
        pt = Point(px, pz)
        if poly.buffer(1.5).contains(pt):
            continue
        if buildings_tight_prep.contains(pt) or road_row_prep.contains(pt) or (water_excl_prep and water_excl_prep.contains(pt)):
            continue
        species = weighted_choice(rng, MIX_YARD)
        spec = SPECIES[species]
        h = rng.uniform(*spec["h"]) * age_bias
        r = rng.uniform(*spec["r"]) * min(age_bias, 1.15)
        if add_tree(px, pz, species, "yard", 5.0, rng):
            trees_out[-1]["height_m"] = round(min(h, spec["h"][1] * 1.3), 2)
            trees_out[-1]["canopy_r_m"] = round(min(r, spec["r"][1] * 1.3), 2)
            placed += 1
            n_yard += 1

    # foundation shrubs along ~60% of houses
    if rng.random() < 0.6:
        ring = list(poly.exterior.coords)
        for i in range(len(ring) - 1):
            x0, z0 = ring[i]
            x1, z1 = ring[i + 1]
            seg_len = math.hypot(x1 - x0, z1 - z0)
            if seg_len < 3.0 or rng.random() < 0.4:
                continue
            steps = max(1, int(seg_len / 1.6))
            for s in range(steps):
                t = (s + 0.5) / steps
                sx, sz = x0 + (x1 - x0) * t, z0 + (z1 - z0) * t
                tx, tz = (x1 - x0) / seg_len, (z1 - z0) / seg_len
                # outward normal (away from centroid)
                nx, nz = -tz, tx
                if (sx + nx - cx) ** 2 + (sz + nz - cz) ** 2 < (sx - cx) ** 2 + (sz - cz) ** 2:
                    nx, nz = -nx, -nz
                ox, oz = sx + nx * 1.0, sz + nz * 1.0
                srng = seeded_rng("found", round(ox, 1), round(oz, 1))
                if buildings_tight_prep.contains(Point(ox, oz)) or road_row_prep.contains(Point(ox, oz)):
                    continue
                species = weighted_choice(srng, MIX_FOUNDATION_SHRUB)
                if add_shrub(ox, oz, species, "foundation", 1.3, srng):
                    n_found += 1
print(f"  {n_yard} yard trees, {n_found} foundation shrubs")

# 4. Park / cemetery trees ---------------------------------------------------
print("placing park + cemetery trees ...")


def scatter_polygon(poly, density_per_m2, min_spacing, mix, category, rng, conifer_specimen_prob=0.0,
                     riparian_check=False, understory_mix=None, understory_prob=0.0, max_pts=4000):
    target = min(int(poly.area * density_per_m2), max_pts)
    if target <= 0:
        return 0
    pprep = prep(poly)
    minx, minz, maxx, maxz = poly.bounds
    placed = 0
    attempts = 0
    max_attempts = target * 25 + 200
    while placed < target and attempts < max_attempts:
        attempts += 1
        px = rng.uniform(minx, maxx)
        pz = rng.uniform(minz, maxz)
        if not pprep.contains(Point(px, pz)):
            continue
        if blocked(px, pz):
            continue
        local_mix = mix
        if riparian_check and near_water(px, pz):
            local_mix = MIX_WOOD_RIPARIAN
        if understory_mix and rng.random() < understory_prob:
            species = weighted_choice(rng, understory_mix)
            if add_shrub(px, pz, species, category + "_understory", 2.0, rng):
                placed += 1
            continue
        species = weighted_choice(rng, local_mix)
        if conifer_specimen_prob and rng.random() < conifer_specimen_prob:
            species = "white_pine" if rng.random() < 0.5 else "blue_spruce"
        if add_tree(px, pz, species, category, min_spacing, rng):
            placed += 1
    return placed


n_park = 0
for poly, tags in park_polys:
    rng = seeded_rng("park", tags.get("name"), round(poly.centroid.x, 1))
    is_nature_reserve = tags.get("leisure") == "nature_reserve"
    density = 0.010 if is_nature_reserve else 0.006
    spacing = 6.0 if is_nature_reserve else 9.0
    n_park += scatter_polygon(poly, density, spacing, MIX_PARK, "park", rng,
                               conifer_specimen_prob=0.10, riparian_check=True)
for poly, tags in cemetery_polys:
    rng = seeded_rng("cemetery", tags.get("name"), round(poly.centroid.x, 1))
    n_park += scatter_polygon(poly, 0.004, 10.0, MIX_PARK, "park", rng, conifer_specimen_prob=0.12)
# pitch/playground: keep the field open, just a thin edge row
for poly, tags in pitch_polys:
    rng = seeded_rng("pitch", tags.get("name"), round(poly.centroid.x, 1))
    edge = poly.buffer(-2.0)
    if not edge.is_empty:
        ring = poly.exterior.difference(edge.buffer(0.1)) if not edge.is_empty else poly.exterior
    # simpler: scatter a very low density ring by sampling near boundary
    boundary = poly.boundary
    blen = boundary.length
    d = 0.0
    while d < blen:
        pt = boundary.interpolate(d)
        d += rng.uniform(14.0, 22.0)
        inward = poly.centroid
        dx, dz = inward.x - pt.x, inward.y - pt.y
        dl = math.hypot(dx, dz) or 1.0
        px, pz = pt.x + dx / dl * 3.0, pt.y + dz / dl * 3.0
        if blocked(px, pz):
            continue
        species = weighted_choice(rng, MIX_PARK)
        add_tree(px, pz, species, "park", 8.0, rng)
        n_park += 1
print(f"  {n_park} park/cemetery/pitch-edge trees")

# Manual accent clusters at landmark open spaces not covered by a landuse
# polygon (courthouse lawn, Lincoln statue) — small clumps, deterministic.
print("placing landmark accent trees ...")
LANDMARK_ACCENTS = [
    ("courthouse_lawn", 1691.9, -1233.5, 45.0, 8),
    ("lincoln_statue", 1387.8, -1726.6, 40.0, 6),
]
n_accent = 0
for name, cx, cz, radius, count in LANDMARK_ACCENTS:
    rng = seeded_rng("accent", name)
    tries = 0
    placed = 0
    while placed < count and tries < count * 20:
        tries += 1
        ang = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(10.0, radius)
        px, pz = cx + math.cos(ang) * dist, cz + math.sin(ang) * dist
        if blocked(px, pz):
            continue
        species = weighted_choice(rng, MIX_PARK)
        if add_tree(px, pz, species, "park", 9.0, rng):
            placed += 1
            n_accent += 1
print(f"  {n_accent} landmark accent trees")

# 5. Wood / riparian dense woods ---------------------------------------------
print("placing wood/riparian trees ...")
n_wood = 0
for poly, tags in wood_polys:
    rng = seeded_rng("wood", round(poly.centroid.x, 1), round(poly.centroid.y, 1))
    riparian = near_water(poly.centroid.x, poly.centroid.y)
    mix = MIX_WOOD_RIPARIAN if riparian else MIX_WOOD_GENERAL
    n_wood += scatter_polygon(poly, 0.018, 5.5, mix, "wood_riparian" if riparian else "wood", rng,
                               riparian_check=True, understory_mix=[("shrub_wild", 100)], understory_prob=0.18)
# nature_reserve polys already covered above via park_polys (Van Arnam Island, Willow Park)
print(f"  {n_wood} wood/riparian trees+understory")

# 6. Open grassland/wetland: sparse willow/shrub clumps -----------------------
print("placing wetland/grassland shrub clumps ...")
n_wet = 0
for poly, tags in open_grass_polys:
    rng = seeded_rng("wet", round(poly.centroid.x, 1))
    n_wet += scatter_polygon(poly, 0.005, 5.0, [("willow", 40), ("shrub_wild", 60)], "wetland", rng)
print(f"  {n_wet} wetland shrubs/willows")

# 7. Riverbank cattails -------------------------------------------------------
print("placing riverbank cattails ...")
n_cattail = 0
if riverbank_ring is not None and not riverbank_ring.is_empty:
    geoms = riverbank_ring.geoms if hasattr(riverbank_ring, "geoms") else [riverbank_ring]
    for g in geoms:
        if g.area < 2.0:
            continue
        rng = seeded_rng("cattail", round(g.centroid.x, 1), round(g.centroid.y, 1))
        n_cattail += scatter_polygon(g, 0.09, 1.2, [("cattail", 100)], "cattail", rng, max_pts=600)
print(f"  {n_cattail} cattail clumps")

# 8. Downtown planters (sparse, along commercial-zone sidewalks) -------------
print("placing downtown planters ...")
n_planter = 0
for line, tags, hw in road_lines:
    hwy = tags.get("highway")
    if hwy not in STREET_TREE_HIGHWAYS.union({"primary", "secondary"}):
        continue
    pts = list(line.coords)
    mid = line.interpolate(0.5, normalized=True)
    if not is_downtown_way(tags, (mid.x, mid.y)):
        continue
    rng = seeded_rng("planter", tags.get("name"))
    offset = hw + CURB_WIDTH + 0.9
    for x, z, tx, tz, d in walk_polyline(pts, 45.0, 0.2, rng):
        nx, nz = -tz, tx
        for side in (1.0, -1.0):
            if rng.random() > 0.35:
                continue
            px, pz = x + nx * offset * side, z + nz * offset * side
            if buildings_tight_prep.contains(Point(px, pz)):
                continue
            species = weighted_choice(rng, MIX_DOWNTOWN)
            if add_tree(px, pz, species, "downtown", 10.0, rng):
                trees_out[-1]["height_m"] = round(trees_out[-1]["height_m"] * 0.5, 2)
                trees_out[-1]["canopy_r_m"] = round(trees_out[-1]["canopy_r_m"] * 0.55, 2)
                n_planter += 1
print(f"  {n_planter} downtown planter trees")

# 9. Rail-side weeds -----------------------------------------------------------
print("placing rail-side weed shrubs ...")
n_rail = 0
for line in rail_lines:
    rng = seeded_rng("rail", round(line.coords[0][0], 1))
    pts = list(line.coords)
    for x, z, tx, tz, d in walk_polyline(pts, 5.0, 0.4, rng):
        nx, nz = -tz, tx
        for side in (1.0, -1.0):
            if rng.random() > 0.5:
                continue
            off = rng.uniform(3.0, 8.0)
            px, pz = x + nx * off * side, z + nz * off * side
            if buildings_tight_prep.contains(Point(px, pz)) or road_row_prep.contains(Point(px, pz)):
                continue
            if water_excl_prep and water_excl_prep.contains(Point(px, pz)):
                continue
            if add_shrub(px, pz, "shrub_wild", "rail", 2.5, rng):
                n_rail += 1
print(f"  {n_rail} rail-side shrubs")

print(f"TOTAL trees: {len(trees_out)}  shrubs: {len(shrubs_out)}")

with open(os.path.join(OUT_DIR, "trees.json"), "w") as f:
    json.dump({"seed": SEED, "count": len(trees_out), "instances": trees_out}, f)
with open(os.path.join(OUT_DIR, "shrubs.json"), "w") as f:
    json.dump({"seed": SEED, "count": len(shrubs_out), "instances": shrubs_out}, f)

# ---------------------------------------------------------------------------
# Grass mask raster
# ---------------------------------------------------------------------------
print("rasterizing grass mask ...")
wo = pc.load_world_origin()
PX_PER_M = 0.5  # 2 m/px
size_m = wo["size_m"]
img_w = int(size_m * PX_PER_M)
img_h = img_w
# world (x,z) -> pixel: x in [0,size_m], z in [-size_m,0] (north is -z)
# Godot origin (0,0) maps to the *top-left* of the world square in our layout
# (x0=0 west edge, z0=0 north edge, z decreases southward -> increasing +z is
# south). Play area spans x:[0,size_m], z:[-size_m,0].
ORIGIN_X, ORIGIN_Z_TOP = 0.0, 0.0


def to_px(x, z):
    return ((x - ORIGIN_X) * PX_PER_M, (-(z - ORIGIN_Z_TOP)) * PX_PER_M)


# R = grass density (mown lawn baseline), G = tallness (unmown/riverbank/wetland)
MOWN = (200, 40, 0)
TALL = (190, 210, 0)
BLACK = (0, 0, 0)

# NOTE: OSM tags almost none of Dixon's actual residential fabric as
# landuse=residential (2 tiny polygons total in landuse.json) -- like most
# small-town OSM coverage, the yards/lawns that make up most of the town
# simply have no polygon at all. So this mask does NOT build up from
# landuse polygons; it starts as grass EVERYWHERE in the play area and
# subtracts the specific things that are demonstrably not grass (roads,
# buildings, water, rails, downtown/commercial pavement, dense wood floor),
# then re-adds the parkway ribbon (which the road-ROW subtraction removes
# along with the sidewalk) and marks explicit tall/unmown zones on top.
img = Image.new("RGB", (img_w, img_h), MOWN)
draw = ImageDraw.Draw(img)


def draw_poly(poly, rgb):
    if poly is None or poly.is_empty:
        return
    geoms = poly.geoms if hasattr(poly, "geoms") else [poly]
    for g in geoms:
        if g.is_empty or not hasattr(g, "exterior") or g.exterior is None:
            continue
        pts = [to_px(x, z) for x, z in g.exterior.coords]
        draw.polygon(pts, fill=rgb)
        for interior in g.interiors:
            ipts = [to_px(x, z) for x, z in interior.coords]
            draw.polygon(ipts, fill=BLACK)


# 1. Non-grass ground: downtown/commercial pavement & lots, dense wood floor
for poly, _ in commercial_polys:
    draw_poly(poly, BLACK)
for poly, _ in wood_polys:
    draw_poly(poly, BLACK)

# 2. Explicit tall/unmown zones (drawn before the hard subtraction so roads
# and water still win where they overlap a wetland/grassland polygon)
for poly, _ in open_grass_polys:
    draw_poly(poly, TALL)
if riverbank_ring is not None:
    draw_poly(riverbank_ring, TALL)

# 3. Hard subtraction: pavement/sidewalk ROW, buildings, water, rails
draw_poly(road_row_union, BLACK)
draw_poly(buildings_tight, BLACK)
draw_poly(unary_union(water_reach_polys) if water_reach_polys else Polygon(), BLACK)
draw_poly(rails_excl, BLACK)

# 4. Re-add the parkway ribbon (grass strip between curb and sidewalk on
# residential/tertiary streets) that step 3 just subtracted along with the
# rest of the ROW.
for line, tags, hw in road_lines:
    hwy = tags.get("highway")
    if hwy not in STREET_TREE_HIGHWAYS:
        continue
    mid = line.interpolate(0.5, normalized=True)
    if is_downtown_way(tags, (mid.x, mid.y)):
        continue
    center = hw + CURB_WIDTH + PARKWAY_GAP * 0.5
    for side in (1.0, -1.0):
        try:
            strip = line.parallel_offset(center * side, side="left" if side > 0 else "right", join_style=2)
            draw_poly(strip.buffer(PARKWAY_GAP * 0.5, cap_style=2), MOWN)
        except Exception:
            pass

mask_path = os.path.join(OUT_DIR, "grass_mask.png")
img.save(mask_path)
with open(os.path.join(OUT_DIR, "grass_mask.json"), "w") as f:
    json.dump({
        "width": img_w, "height": img_h, "px_per_m": PX_PER_M,
        "origin_x": ORIGIN_X, "origin_z_top": ORIGIN_Z_TOP,
        "note": "pixel (0,0) = world (x=0,z=0); +col = +x east; +row = -z (south). "
                "R channel = mown-lawn density 0-1 (val/200 clamped), "
                "G channel = tall/unmown density 0-1 (val/210 clamped).",
    }, f, indent=2)
print(f"grass mask: {mask_path} ({img_w}x{img_h}px @ {1/PX_PER_M}m/px)")

print("done.")
