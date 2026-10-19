#!/usr/bin/env python3
"""Extracts paved off-street surfaces from the Illinois 6-inch orthoimagery.

Supersedes extract_paved.py (which worked off the single rotated Google aerial).

Two things changed and both matter:
  * The imagery is exactly georeferenced, so there is no fitting step. It is NOT north-up
    in game space, though: each tile is Web Mercator, turned ~1.7 deg against the UTM grid,
    and is placed by its `pixel_from_world` affine (georef_affine.py, via aerial_crop.py).
    Until 2026-10-18 this placed tiles by their requested box instead, up to ~15 m off.
  * Colour alone CANNOT separate pavement from roofs on this imagery. Measured on
    tile_03_02: Galena Ave asphalt val 0.52, courthouse roof val 0.26, theatre roof 0.99.
    Roofs sit on both sides of asphalt. It is also leaf-off, so dormant lawn is brown
    (rgb 61,55,39) and the usual "green = vegetation" test fails.
    Instead roofs are removed GEOMETRICALLY using the 5,794 building footprints we now
    hold (OSM + Microsoft + curated). That is what makes this reliable: the earlier attempt
    leaked roofs because OSM only had 707 footprints and the rest were unmapped.

Remaining colour test only has to separate pavement from dormant grass/bare earth:
pavement is brighter and less saturated (val 0.52 / sat 0.21 vs lawn 0.24 / sat 0.37).

Rectangles are decomposed in STREET-GRID-ALIGNED space (Dixon's grid runs ~344 deg), so lot
edges come out parallel to the streets instead of as north-up staircases.

Run: cd pipeline/aerial && ../../.venv/bin/python extract_paved_il.py
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

import aerial_crop

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

OUT_JSON = os.path.join(ROOT, "game", "data", "aerial_paved.json")
OUT_PREVIEW = os.path.join(ROOT, "captures", "aerial", "paved_il_preview.png")

MPP = 0.5                 # working resolution of the mask, metres per pixel
SOURCE_MPP = 0.25         # the tiles' own resolution, sampled before reducing to MPP
TILE_M = 512.0            # world block cut from the imagery per crop
MIN_AREA_M2 = 150.0       # below this it is a driveway or an apron, not a lot
MIN_RECT_M2 = 8.0
ROAD_PAD_M = 2.0          # kerb + gutter
BUILDING_PAD_M = 1.5      # eaves and the shadow skirt beside a wall

VAL_MIN, VAL_MAX = 0.33, 0.97
SAT_MAX = 0.30

HALF_W = {"motorway": 11.0, "trunk": 9.0, "primary": 9.0, "secondary": 8.0, "tertiary": 7.0,
          "residential": 5.5, "unclassified": 5.5, "living_street": 5.0, "service": 3.4,
          "track": 2.5, "pedestrian": 3.0, "footway": 1.2, "cycleway": 1.2, "path": 1.0}


def street_bearing():
    """Dominant street bearing, so lot rectangles align with the grid."""
    ways = json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]
    hist = np.zeros(90)
    for w in ways:
        if (w.get("tags") or {}).get("highway") not in HALF_W:
            continue
        vs = w["vertices"]
        for i in range(len(vs) - 1):
            dx = vs[i + 1]["x"] - vs[i]["x"]
            dz = vs[i + 1]["z"] - vs[i]["z"]
            L = math.hypot(dx, dz)
            if L < 5:
                continue
            ang = math.degrees(math.atan2(dx, -dz)) % 90.0
            hist[int(ang)] += L
    return float(np.argmax(hist))


def build_masks(size_m):
    """Pavement-coloured pixels and imagery coverage on the MPP world grid.

    Each tile is placed by its `pixel_from_world` affine (georef_affine.py) via
    aerial_crop.Aerial, not by its requested box: the tiles are Web Mercator, turned
    ~1.7 deg against the UTM grid, and the box alone is up to ~15 m off at two corners.
    The world is cut in TILE_M blocks at the tiles' own 0.25 m, then reduced to MPP.
    """
    n = int(size_m / MPP)
    paved = np.zeros((n, n), dtype=bool)
    got = np.zeros((n, n), dtype=bool)
    aerial = aerial_crop.Aerial()
    step = int(TILE_M / MPP)
    for iz in range(0, n, step):
        for ix in range(0, n, step):
            w, h = min(step, n - ix), min(step, n - iz)
            x0, z0 = ix * MPP, iz * MPP - size_m
            crop = aerial.crop(x0, z0, x0 + w * MPP, z0 + h * MPP, mpp=SOURCE_MPP)
            a = np.asarray(crop.resize((w, h), Image.BILINEAR), dtype=np.float32)
            rgb, alpha = a[..., :3], a[..., 3]
            mx, mn = rgb.max(-1), rgb.min(-1)
            val = mx / 255.0
            sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
            covered = alpha > 250       # tile edges blend with transparency; drop them
            paved[iz:iz + h, ix:ix + w] = (val > VAL_MIN) & (val < VAL_MAX) & (sat < SAT_MAX) & covered
            got[iz:iz + h, ix:ix + w] = covered
    return paved, got


def draw_world_polys(n, size_m, polys, pad_px):
    img = Image.new("1", (n, n), 0)
    d = ImageDraw.Draw(img)
    for poly in polys:
        pts = [(x / MPP, (z + size_m) / MPP) for x, z in poly]
        if len(pts) >= 3:
            d.polygon(pts, fill=1)
    m = np.array(img, dtype=bool)
    if pad_px > 0:
        m = ndimage.binary_dilation(m, iterations=pad_px)
    return m


def building_polys():
    out = []
    for name in ("buildings.json", "buildings_ms.json", "buildings_curated.json"):
        p = os.path.join(ROOT, "game", "data", name)
        if not os.path.exists(p):
            continue
        data = json.load(open(p))
        recs = data.get("buildings", data if isinstance(data, list) else [])
        for b in recs:
            fp = b.get("footprint") or []
            if len(fp) >= 3:
                out.append([(q["x"], q["z"]) for q in fp])
    return out


def road_mask(n, size_m):
    img = Image.new("1", (n, n), 0)
    d = ImageDraw.Draw(img)
    for w in json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]:
        cls = (w.get("tags") or {}).get("highway")
        if cls not in HALF_W:
            continue
        width_px = max(1, int(2 * (HALF_W[cls] + ROAD_PAD_M) / MPP))
        vs = w["vertices"]
        for i in range(len(vs) - 1):
            a = (vs[i]["x"] / MPP, (vs[i]["z"] + size_m) / MPP)
            b = (vs[i + 1]["x"] / MPP, (vs[i + 1]["z"] + size_m) / MPP)
            d.line([a, b], fill=1, width=width_px)
    return np.array(img, dtype=bool)


def maximal_rectangles(mask, min_px):
    """Greedy exact-tiling decomposition, run PER BLOB on a cropped bounding box.

    The first version rescanned the whole 7600x7600 rotated mask for every rectangle it
    emitted -- ~58M Python-level operations per rectangle, hundreds of rectangles, so it
    ran for 24 minutes without finishing. Cropping to each blob's bounding box keeps every
    scan small, and the histogram pass is vectorised with numpy.
    """
    rects = []
    lbl, n = ndimage.label(mask)
    objs = ndimage.find_objects(lbl)
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        sub = (lbl[sl] == i)
        oy, ox = sl[0].start, sl[1].start
        m = sub.copy()
        h, w = m.shape
        while True:
            best = (0, 0, 0, 0, 0)
            heights = np.zeros(w, dtype=np.int32)
            for y in range(h):
                heights = np.where(m[y], heights + 1, 0)
                # largest rectangle in histogram, iterative stack
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
            rects.append((left + ox, top + oy, right + ox, bottom + oy))
            m[top:bottom + 1, left:right + 1] = False
    return rects


def main():
    origin = json.load(open(os.path.join(ROOT, "game", "data", "world_origin.json")))
    size_m = origin["size_m"]
    n = int(size_m / MPP)

    print("building masks from tiles...", flush=True)
    paved, got = build_masks(size_m)
    print(f"imagery covers {100.0 * got.mean():.0f}% of the play area")

    bld = draw_world_polys(n, size_m, building_polys(), int(BUILDING_PAD_M / MPP))
    rd = road_mask(n, size_m)
    # Whitewater below the dam is bright and desaturated, so it reads as pavement.
    # Mapped water is the principled way to remove it.
    water = json.load(open(os.path.join(ROOT, "game", "data", "water.json")))
    wpolys = [[(q["x"], q["z"]) for q in r.get("polygon", [])] for r in water.get("reaches", [])]
    wet = draw_world_polys(n, size_m, [w for w in wpolys if len(w) >= 3], int(2.0 / MPP))
    cand = paved & got & ~bld & ~rd & ~wet
    print(f"paved pixels after removing {bld.sum()/ (1/MPP)**2:,.0f} m2 of buildings and roads: "
          f"{cand.sum() * MPP * MPP:,.0f} m2")

    cand = ndimage.binary_opening(cand, iterations=1)
    cand = ndimage.binary_closing(cand, structure=np.ones((9, 9), bool))
    cand = ndimage.binary_opening(cand, iterations=2)

    lbl, nlab = ndimage.label(cand)
    keep = np.zeros_like(cand)
    kept = 0
    for i, size in enumerate(ndimage.sum(cand, lbl, range(1, nlab + 1)), start=1):
        if size * MPP * MPP >= MIN_AREA_M2:
            keep |= lbl == i
            kept += 1

    # Decompose in street-grid space so lot edges run parallel to the streets.
    # The transform is written explicitly rather than using ndimage.rotate(reshape=True),
    # whose internal centring offset I got wrong the first time -- every quad came out
    # displaced (drawn over the river, missing the lots) even though the mask was correct.
    # affine_transform maps OUTPUT coords -> INPUT coords as i = M @ o + offset, so the
    # same M/offset convert a rectangle corner straight back to mask pixels. No inversion.
    bearing = street_bearing()
    th = math.radians(bearing)
    cos_t, sin_t = math.cos(th), math.sin(th)
    M = np.array([[cos_t, -sin_t], [sin_t, cos_t]])      # (row, col)
    h_in, w_in = keep.shape
    corners = np.array([[0, 0], [0, w_in], [h_in, 0], [h_in, w_in]], dtype=float)
    c_in = np.array([h_in / 2.0, w_in / 2.0])
    rot_c = (corners - c_in) @ M.T
    out_h = int(np.ceil(rot_c[:, 0].max() - rot_c[:, 0].min()))
    out_w = int(np.ceil(rot_c[:, 1].max() - rot_c[:, 1].min()))
    c_out = np.array([out_h / 2.0, out_w / 2.0])
    offset = c_in - M @ c_out
    rot = ndimage.affine_transform(keep.astype(np.uint8), M, offset=offset,
                                   output_shape=(out_h, out_w), order=0) > 0

    rects = maximal_rectangles(rot, int(MIN_RECT_M2 / (MPP * MPP)))
    quads = []
    for x0, y0, x1, y1 in rects:
        corner_list = []
        for px, py in ((x0, y0), (x1 + 1, y0), (x1 + 1, y1 + 1), (x0, y1 + 1)):
            i = M @ np.array([float(py), float(px)]) + offset      # -> (row, col) in mask
            corner_list.append([i[1] * MPP, i[0] * MPP - size_m])  # -> world (x, z)
        quads.append(corner_list)

    json.dump({"note": "Paved off-street surfaces from Illinois 2025 6-inch imagery; "
                       "roofs removed using the building footprint set, not colour. "
                       "Source: pipeline/aerial/extract_paved_il.py",
               "quads": quads}, open(OUT_JSON, "w"))

    area = keep.sum() * MPP * MPP
    print(f"kept {kept} lots of {nlab} blobs   area {area:,.0f} m2   rects {len(quads)}   "
          f"(grid bearing {bearing:.0f} deg)")
    print("wrote", OUT_JSON)

    prev = Image.new("RGB", (n // 2, n // 2), (20, 22, 24))
    d = ImageDraw.Draw(prev)
    small = np.array(Image.fromarray((keep * 255).astype(np.uint8)).resize((n // 2, n // 2)))
    ys, xs = np.nonzero(small)
    for x, y in zip(xs[::7], ys[::7]):
        d.point((int(x), int(y)), fill=(255, 60, 200))
    for w in json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]:
        vs = w["vertices"]
        for i in range(len(vs) - 1):
            a = (vs[i]["x"] / MPP / 2, (vs[i]["z"] + size_m) / MPP / 2)
            b = (vs[i + 1]["x"] / MPP / 2, (vs[i + 1]["z"] + size_m) / MPP / 2)
            d.line([a, b], fill=(90, 95, 105), width=1)
    os.makedirs(os.path.dirname(OUT_PREVIEW), exist_ok=True)
    prev.save(OUT_PREVIEW)
    print("preview", OUT_PREVIEW)


if __name__ == "__main__":
    main()
