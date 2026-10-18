#!/usr/bin/env python3
"""bake_splat.py -- terrain workstream helper.

Reads game/data/landuse.json, rails.json, water.json (produced by the data
pipeline -- read-only), plus the authoritative transportation layout, and
bakes two RGBA8 splat/mask textures that
game/terrain/shaders/terrain.gdshader uses to blend ground materials:

  game/terrain/textures/terrain_splat_a.png
    R = lawn (mowed grass: parks/residential/cemetery/playgrounds/pitches)
    G = wooded ground / leaf litter (natural=wood, nature reserves)
    B = gravel/ballast (railway corridors, quarries)
    A = riverbank mud (buffer around water + wetland polygons)

  game/terrain/textures/terrain_splat_b.png
    R = reserved paved layer (zero; real paving is transportation geometry)
    G = bare dirt (farmland, brownfield)
    B = unused (0)
    A = 255 (opaque, unused)

Everything not covered by one of the above stays implicit "wild/dry grass"
in the shader (1 - sum of weights, clamped). Texels are 2m (1350x1350
covers the 2700x2700 play square exactly), aligned to local Godot space:
col = x/2, row = (z+2700)/2 (row 0 = north edge, matching the heightmap
convention documented in pipeline_notes.md).

This script only READS game/data/*.json and WRITES into game/terrain/
(the terrain workstream's own folder) -- it must never write to game/data/.

Usage: cd pipeline/terrain && ../../.venv/bin/python bake_splat.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
from roads.transport_layout import load_layout, paint_geometry  # noqa: E402
DATA = ROOT / "game" / "data"
OUT = ROOT / "game" / "terrain" / "textures"

PLAY_SIZE_M = 2700.0
TEXELS_PER_M = 0.5  # 2m per texel
TEX_SIZE = int(PLAY_SIZE_M * TEXELS_PER_M)  # 1350

BLUR_RADIUS_TEXELS = 2.5  # soft splat edges (~5m)


def load(name):
    with open(DATA / name) as f:
        return json.load(f)


def world_to_px(x, z):
    """Local Godot (x,z) meters -> (col,row) float pixel coords, row0=north."""
    col = x * TEXELS_PER_M
    row = (z + PLAY_SIZE_M) * TEXELS_PER_M
    return col, row


def new_mask():
    return Image.new("L", (TEX_SIZE, TEX_SIZE), 0)


def draw_polygon(mask, ring, value=255):
    if len(ring) < 3:
        return
    pts = [world_to_px(p["x"], p["z"]) for p in ring]
    ImageDraw.Draw(mask).polygon(pts, fill=value)


def draw_buffered_line(mask, verts, width_m, value=255):
    """Rasterize a polyline buffered to width_m using shapely, filled."""
    from shapely.geometry import LineString

    if len(verts) < 2:
        return
    coords = [(v["x"], v["z"]) for v in verts]
    try:
        line = LineString(coords)
        if line.length <= 0:
            return
        poly = line.buffer(width_m, cap_style=2, join_style=2)
    except Exception:
        return
    geoms = poly.geoms if poly.geom_type == "MultiPolygon" else [poly]
    for g in geoms:
        ring = [{"x": c[0], "z": c[1]} for c in g.exterior.coords]
        draw_polygon(mask, ring)


def blur(mask):
    return mask.filter(ImageFilter.GaussianBlur(BLUR_RADIUS_TEXELS))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    landuse = load("landuse.json")["areas"]
    rails = load("rails.json")["ways"]
    water = load("water.json")
    transportation = load_layout()

    lawn = new_mask()
    wood = new_mask()
    gravel = new_mask()
    mud = new_mask()
    paved = new_mask()
    dirt = new_mask()

    LAWN_LEISURE = {"park", "playground", "pitch", "recreation_ground", "garden"}
    LAWN_LANDUSE = {"residential", "cemetery"}
    WOOD_NATURAL = {"wood"}
    WOOD_LEISURE = {"nature_reserve"}
    GRAVEL_LANDUSE = {"quarry"}
    MUD_NATURAL = {"wetland"}
    DIRT_LANDUSE = {"farmland", "brownfield"}

    n_lawn = n_wood = n_gravel = n_mud = n_paved = n_dirt = 0
    for area in landuse:
        tags = area.get("tags", {})
        ring = area.get("polygon", [])
        lu = tags.get("landuse")
        le = tags.get("leisure")
        na = tags.get("natural")
        if le in LAWN_LEISURE or lu in LAWN_LANDUSE:
            draw_polygon(lawn, ring); n_lawn += 1
        if na in WOOD_NATURAL or le in WOOD_LEISURE:
            draw_polygon(wood, ring); n_wood += 1
        if lu in GRAVEL_LANDUSE:
            draw_polygon(gravel, ring); n_gravel += 1
        if na in MUD_NATURAL:
            draw_polygon(mud, ring); n_mud += 1
        if lu in DIRT_LANDUSE:
            draw_polygon(dirt, ring); n_dirt += 1

    # Railway corridors -> gravel ballast. width_m per track bed, generous
    # enough to read clearly at 2m/texel.
    for way in rails:
        draw_buffered_line(gravel, way.get("vertices", []), width_m=6.0)

    # Riverbank mud: buffer around every water reach polygon's boundary and
    # every minor stream line. Widened from the original 9m/5m -- at typical
    # eye-height viewing distances along a riverbank the earlier width read
    # as a near-invisible sliver; this is a visible mud/brush band without
    # swallowing the whole near-shore lawn.
    for reach in water.get("reaches", []):
        ring = reach.get("polygon", [])
        verts = [{"x": p["x"], "y": 0, "z": p["z"]} for p in ring]
        draw_buffered_line(mud, verts + ([verts[0]] if verts else []), width_m=16.0)
    for stream in water.get("streams", []):
        draw_buffered_line(mud, stream.get("vertices", []), width_m=8.0)

    print(f"landuse matches: lawn={n_lawn} wood={n_wood} gravel_landuse={n_gravel} "
          f"mud_natural={n_mud} paved={n_paved} dirt={n_dirt} "
          f"rail_ways={len(rails)} water_reaches={len(water.get('reaches', []))} "
          f"streams={len(water.get('streams', []))}")

    for name in ("parkway", "verge"):
        paint_geometry(lawn, transportation[name], 255, world_to_px)
    # Paving is exclusively real transportation geometry, never a land-use tint.
    lawn, wood, gravel, mud, dirt = (blur(m) for m in (lawn, wood, gravel, mud, dirt))

    tex_a = Image.merge("RGBA", (lawn, wood, gravel, mud))
    tex_b = Image.merge("RGBA", (paved, dirt, Image.new("L", (TEX_SIZE, TEX_SIZE), 0),
                                  Image.new("L", (TEX_SIZE, TEX_SIZE), 255)))

    tex_a.save(OUT / "terrain_splat_a.png")
    tex_b.save(OUT / "terrain_splat_b.png")
    print(f"wrote {OUT / 'terrain_splat_a.png'} and terrain_splat_b.png ({TEX_SIZE}x{TEX_SIZE}, "
          f"{1/TEXELS_PER_M:.1f}m/texel)")


if __name__ == "__main__":
    main()
