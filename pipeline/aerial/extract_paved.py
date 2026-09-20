#!/usr/bin/env python3
"""Extracts paved off-street surfaces (parking lots, aprons, service yards) from the
user's Google Earth aerial and writes them as world-space quads for the roads bake.

Why: OSM has essentially no parking data for downtown Dixon (2 landuse areas inside the
whole aerial), yet parking lots are a large share of the ground plane there. Without them
the lots render as grass/terrain, which is the single biggest infrastructure gap in the
reconstruction.

Method (all verifiable offline, no Godot needed):
  1. Classify aerial pixels: vegetation / water / deep shadow / paved.
     "Paved" = low saturation, mid brightness, not vegetation/water/shadow.
  2. Subtract what the model already builds: road carriageways (rasterised from roads.json
     with per-class widths) and building footprints (buildings.json + curated), each dilated
     a little so kerbs and eaves don't leak in.
  3. Clean up with morphological opening/closing, drop blobs under MIN_AREA_M2.
  4. Decompose the remaining mask into maximal axis-aligned rectangles IN AERIAL PIXEL SPACE
     (parking lots are rectilinear and aligned with the street grid, which the aerial is
     rotated to), then convert each rectangle's corners to world coordinates.
     Rectangles tile exactly, so there is no polygon-simplification error to review.

Output: game/data/aerial_paved.json   ({"quads": [[[x,z] x4], ...]})
        plus a preview PNG so the extraction can be eyeballed against the photo.

Run: cd pipeline/aerial && ../../.venv/bin/python extract_paved.py
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "pipeline", "buildings"))
import classify  # noqa: E402  (georeference lives with the buildings pipeline)

AERIAL = os.path.join(ROOT, "screenshots", "dixon_downtown_aerial.png")
OUT_JSON = os.path.join(ROOT, "game", "data", "aerial_paved.json")
OUT_PREVIEW = os.path.join(ROOT, "captures", "aerial", "paved_preview.png")

PX_PER_M = classify.AERIAL_SCALE          # 3.0
MIN_AREA_M2 = 260.0                       # only substantial lots; smaller fragments read as
                                          # scattered patches in game, which looks worse than nothing
MIN_RECT_M2 = 6.0                         # discard slivers during decomposition
ROAD_DILATE_M = 2.2                       # kerb + gutter + parking lane
BUILDING_DILATE_M = 1.2                   # eaves / shadow skirt

# Road half-widths by OSM class (metres), mirroring pipeline/roads/build_road_plan.py.
HALF_W = {
    "motorway": 11.0, "trunk": 9.0, "primary": 9.0, "secondary": 8.0, "tertiary": 7.0,
    "residential": 5.5, "unclassified": 5.5, "living_street": 5.0, "service": 3.4,
    "track": 2.5, "footway": 1.2, "cycleway": 1.2, "path": 1.0, "pedestrian": 3.0, "steps": 1.0,
}


def load_masks(shape):
    """Rasterise roads and buildings into aerial pixel space."""
    h, w = shape
    road = Image.new("1", (w, h), 0)
    bld = Image.new("1", (w, h), 0)
    dr, db = ImageDraw.Draw(road), ImageDraw.Draw(bld)

    ways = json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]
    for way in ways:
        cls = (way.get("tags") or {}).get("highway")
        hw = HALF_W.get(cls, 5.0) + ROAD_DILATE_M
        pts = [classify.world_to_aerial_px(v["x"], v["z"]) for v in way["vertices"]]
        for i in range(len(pts) - 1):
            dr.line([tuple(pts[i]), tuple(pts[i + 1])], fill=1, width=int(2 * hw * PX_PER_M))

    for path, key in ((os.path.join(ROOT, "game", "data", "buildings.json"), "buildings"),
                      (os.path.join(ROOT, "game", "data", "buildings_curated.json"), None)):
        if not os.path.exists(path):
            continue
        data = json.load(open(path))
        recs = data[key] if key and key in data else (data if isinstance(data, list) else data.get("buildings", []))
        for b in recs:
            fp = b.get("footprint") or []
            if len(fp) < 3:
                continue
            pts = [tuple(classify.world_to_aerial_px(p["x"], p["z"])) for p in fp]
            db.polygon(pts, fill=1)

    road_m = np.array(road, dtype=bool)
    bld_m = ndimage.binary_dilation(np.array(bld, dtype=bool),
                                    iterations=max(1, int(BUILDING_DILATE_M * PX_PER_M)))
    return road_m, bld_m


def classify_paved(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    val = mx / 255.0
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)

    vegetation = (g > r * 1.04) & (g > b * 1.02)
    water = (b > r * 1.10) & (b > g * 1.02) & (val < 0.55)
    shadow = val < 0.14
    # Measured on this aerial (pipeline/aerial notes): asphalt lots are DARK with
    # relatively high saturation from cars and stall stripes -- Court Clerk lot
    # val 0.43 / sat 0.29, top-left lot val 0.31 / sat 0.23 -- while downtown ROOFS are
    # bright and desaturated (tan roof val 0.81 / sat 0.12, warehouse 0.72 / 0.09).
    # Brightness is therefore the separator, not saturation; the first pass had the
    # saturation test backwards and threw the lots away.
    bright_roof = val > 0.68
    paved = ((val > 0.16) & (sat < 0.42)
             & ~vegetation & ~water & ~shadow & ~bright_roof)
    return paved


def maximal_rectangles(mask, min_px):
    """Greedy decomposition of a boolean mask into axis-aligned rectangles.

    Tiles the mask exactly (no shape approximation): repeatedly take the largest
    all-true rectangle by the classic histogram method, emit it, clear it, repeat.
    """
    m = mask.copy()
    rects = []
    h, w = m.shape
    heights = np.zeros(w, dtype=np.int32)
    while True:
        best = (0, 0, 0, 0, 0)  # area, top, left, bottom, right
        heights[:] = 0
        for y in range(h):
            row = m[y]
            heights = np.where(row, heights + 1, 0)
            stack = []
            for x in range(w + 1):
                cur = heights[x] if x < w else 0
                start = x
                while stack and stack[-1][1] >= cur:
                    sx, sh = stack.pop()
                    area = sh * (x - sx)
                    if area > best[0]:
                        best = (area, y - sh + 1, sx, y, x - 1)
                    start = sx
                stack.append((start, cur))
        if best[0] < min_px:
            break
        _, top, left, bottom, right = best
        rects.append((left, top, right, bottom))
        m[top:bottom + 1, left:right + 1] = False
    return rects


def main():
    img = Image.open(AERIAL).convert("RGB")
    rgb = np.asarray(img, dtype=np.float32)
    h, w = rgb.shape[:2]

    paved = classify_paved(rgb)
    road_m, bld_m = load_masks((h, w))
    cand = paved & ~road_m & ~bld_m

    # Clean: drop speckle, close stall stripes and car-sized holes.
    # Cars and stall stripes fragment a lot into speckle; close over car-sized gaps
    # (~5 m) so a lot comes out as one contiguous surface rather than confetti.
    cand = ndimage.binary_opening(cand, iterations=1)
    cand = ndimage.binary_closing(cand, structure=np.ones((17, 17), bool))
    cand = ndimage.binary_opening(cand, iterations=2)
    cand = ndimage.binary_closing(cand, structure=np.ones((9, 9), bool))

    lbl, n = ndimage.label(cand)
    min_px_blob = MIN_AREA_M2 * PX_PER_M ** 2
    # In the residential fringe (aerial x < AERIAL_HOUSE_ZONE_PX_X) OSM building coverage is
    # poor, so a grey house roof plus its driveway can merge into a blob and get paved over.
    # Require a much larger blob there -- real lots in that zone (e.g. the Court Clerk lot)
    # are thousands of m2, house roofs are a few hundred.
    house_zone_min_px = 900.0 * PX_PER_M ** 2
    keep = np.zeros_like(cand)
    kept = 0
    objs = ndimage.find_objects(lbl)
    for i, size in enumerate(ndimage.sum(cand, lbl, range(1, n + 1)), start=1):
        sl = objs[i - 1]
        cx_px = (sl[1].start + sl[1].stop) / 2.0
        floor_px = house_zone_min_px if cx_px < classify.AERIAL_HOUSE_ZONE_PX_X else min_px_blob
        if size >= floor_px:
            keep |= lbl == i
            kept += 1

    rects = maximal_rectangles(keep, int(MIN_RECT_M2 * PX_PER_M ** 2))
    quads = []
    for x0, y0, x1, y1 in rects:
        corners = [(x0, y0), (x1 + 1, y0), (x1 + 1, y1 + 1), (x0, y1 + 1)]
        quads.append([list(classify.aerial_px_to_world(px, py)) for px, py in corners])

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump({
        "note": "Paved off-street surfaces traced from the Google Earth aerial; "
                "world-space quads (x, z). Source: pipeline/aerial/extract_paved.py",
        "px_per_m": PX_PER_M,
        "quads": quads,
    }, open(OUT_JSON, "w"))

    os.makedirs(os.path.dirname(OUT_PREVIEW), exist_ok=True)
    prev = img.copy()
    ov = Image.new("RGBA", prev.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for x0, y0, x1, y1 in rects:
        d.rectangle([x0, y0, x1, y1], fill=(255, 40, 200, 90), outline=(255, 40, 200, 200))
    prev = Image.alpha_composite(prev.convert("RGBA"), ov).convert("RGB")
    prev.save(OUT_PREVIEW)

    area_m2 = keep.sum() / PX_PER_M ** 2
    print(f"paved blobs kept: {kept} of {n}   area {area_m2:,.0f} m2   rects {len(rects)}")
    print(f"wrote {OUT_JSON}")
    print(f"preview {OUT_PREVIEW}")


if __name__ == "__main__":
    main()
