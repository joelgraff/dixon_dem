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

Mapped car parks (OSM amenity=parking/fuel, data/raw/osm_parking.json) are taken outright.
Elsewhere the colour test only has to separate pavement from dormant grass and bare earth.
Saturation alone (the test until 2026-10-18) let gravel and dirt yards through and missed
dark fresh asphalt; yellowness, (g - b) / max, separates all three (see YELLOW_MAX). A colour
blob is then kept as a lot only if, as a whole, it is not yellow (gravel), is mostly
LOT_CORE_M wide (not a track, shoulder or driveway) and reaches a road or a mapped car park.
Texture was tried and does not help: parked cars make real lots as busy as gravel.
The road mask takes the asphalt edges the aerial width survey measured (alignments.json),
so the outer lanes of wide roads are not left behind as lots; rails mask their ballast.

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

# Colour of one pixel, after averaging over SMOOTH_PX (1.5 m) to quiet cars and paint.
# "Yellowness" is (g - b) / max(r, g, b). Measured inside the OSM parking areas it holds at
# ~0.15 at every brightness; dormant lawn is 0.20-0.37 and gravel/dirt yards 0.16-0.26.
# That is what lets dark fresh asphalt (val 0.20-0.33) in: saturation alone could not
# tell it from dark lawn.
VAL_MIN, VAL_MAX = 0.33, 0.97
SAT_MAX = 0.30
YELLOW_MAX = 0.20
DARK_VAL_MIN = 0.15            # fresh asphalt, val 0.15-0.33
DARK_SAT_MAX = 0.32
DARK_YELLOW_MAX = 0.21
SMOOTH_PX = 3
# Per lot: the median yellowness of a whole blob. OSM lots: p95 0.165; the gravel yard at
# 1291,-59: 0.173.
LOT_YELLOW_MAX = 0.168
STRIP_M = 5.0                  # narrower than this is a sidewalk, a driveway or road edge, not a lot
LOT_CORE_M = 10.0              # a lot is mostly this wide: one parking row and its aisle is ~12 m.
LOT_CORE_FRACTION = 0.4        # share of a lot's area left by a LOT_CORE_M opening. Of 182 colour lots,
                               # 154 keep over half. Below 0.4: the running track at 1041,-1794 (0.28,
                               # wide only at its curve and start), building aprons, storage-unit aisles.
CONNECT_M = 4.0                # a lot reaches a road or a mapped car park within this
OSM_MIN_AREA_M2 = 40.0

RAIL_HALF_M = 5.0             # track and ballast shoulders; ballast is dark and neutral, like asphalt
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
    """Pavement-coloured pixels, imagery coverage and yellowness on the MPP world grid.

    Each tile is placed by its `pixel_from_world` affine (georef_affine.py) via
    aerial_crop.Aerial, not by its requested box: the tiles are Web Mercator, turned
    ~1.7 deg against the UTM grid, and the box alone is up to ~15 m off at two corners.
    The world is cut in TILE_M blocks at the tiles' own 0.25 m, then reduced to MPP.
    """
    n = int(size_m / MPP)
    paved = np.zeros((n, n), dtype=bool)
    got = np.zeros((n, n), dtype=bool)
    yellow = np.zeros((n, n), dtype=np.float32)
    aerial = aerial_crop.Aerial()
    step = int(TILE_M / MPP)
    for iz in range(0, n, step):
        for ix in range(0, n, step):
            w, h = min(step, n - ix), min(step, n - iz)
            x0, z0 = ix * MPP, iz * MPP - size_m
            crop = aerial.crop(x0, z0, x0 + w * MPP, z0 + h * MPP, mpp=SOURCE_MPP)
            a = np.asarray(crop.resize((w, h), Image.BILINEAR), dtype=np.float32)
            rgb, alpha = a[..., :3], a[..., 3]
            covered = alpha > 250       # tile edges blend with transparency; drop them
            rgb = ndimage.uniform_filter(rgb, size=(SMOOTH_PX, SMOOTH_PX, 1))
            mx, mn = rgb.max(-1), rgb.min(-1)
            val = mx / 255.0
            sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
            yel = (rgb[..., 1] - rgb[..., 2]) / np.maximum(mx, 1)
            light = (val > VAL_MIN) & (val < VAL_MAX) & (sat < SAT_MAX) & (yel < YELLOW_MAX)
            dark = (val >= DARK_VAL_MIN) & (val <= VAL_MIN) & (sat < DARK_SAT_MAX) & (yel < DARK_YELLOW_MAX)
            paved[iz:iz + h, ix:ix + w] = (light | dark) & covered
            got[iz:iz + h, ix:ix + w] = covered
            yellow[iz:iz + h, ix:ix + w] = yel
    return paved, got, yellow


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


def parking_polys():
    """OSM amenity=parking / fuel areas (data/raw/osm_parking.json, fetch_osm.py) as world rings."""
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    from osm_common import load_osm, relation_multipolygon_utm, way_polygon_utm
    from shapely.geometry import MultiPolygon

    origin = json.load(open(os.path.join(ROOT, "game", "data", "world_origin.json")))
    e0, n0 = origin["origin_easting"], origin["origin_northing"]
    out = []
    for el in load_osm("parking"):
        tags = el.get("tags") or {}
        if tags.get("amenity") not in ("parking", "fuel") or tags.get("parking") in ("underground", "multi-storey"):
            continue
        g = way_polygon_utm(el) if el["type"] == "way" else relation_multipolygon_utm(el)
        if g is None:
            continue
        for poly in (g.geoms if isinstance(g, MultiPolygon) else [g]):
            out.append([(e - e0, -(nn - n0)) for e, nn in poly.exterior.coords])
    return out


def road_mask(n, size_m, service=True):
    """OSM centrelines at the class half-width, widened to the asphalt edges the aerial width
    survey measured (alignments.json, measured_road_polys): divided arterials run wider than
    their class, and the extra lanes used to come out as long strips of "lot"."""
    img = Image.new("1", (n, n), 0)
    d = ImageDraw.Draw(img)
    for w in json.load(open(os.path.join(ROOT, "game", "data", "roads.json")))["ways"]:
        cls = (w.get("tags") or {}).get("highway")
        if cls not in HALF_W or (cls == "service" and not service):
            continue
        width_px = max(1, int(2 * (HALF_W[cls] + ROAD_PAD_M) / MPP))
        vs = w["vertices"]
        for i in range(len(vs) - 1):
            a = (vs[i]["x"] / MPP, (vs[i]["z"] + size_m) / MPP)
            b = (vs[i + 1]["x"] / MPP, (vs[i + 1]["z"] + size_m) / MPP)
            d.line([a, b], fill=1, width=width_px)
    for poly in measured_road_polys():
        d.polygon([(x / MPP, (z + size_m) / MPP) for x, z in poly], fill=1)
    return np.array(img, dtype=bool)


def rail_mask(n, size_m):
    img = Image.new("1", (n, n), 0)
    d = ImageDraw.Draw(img)
    for w in json.load(open(os.path.join(ROOT, "game", "data", "rails.json")))["ways"]:
        pts = [(v["x"] / MPP, (v["z"] + size_m) / MPP) for v in w["vertices"]]
        d.line(pts, fill=1, width=int(2 * (RAIL_HALF_M + ROAD_PAD_M) / MPP), joint="curve")
    return np.array(img, dtype=bool)


def measured_road_polys(step=2.0, chunk=20.0):
    """The asphalt edges the aerial width survey measured, padded by ROAD_PAD_M, as bands
    along each route. Edges are taken at the middle of each counted block and interpolated
    between them (held flat past the ends), so junction gaps and blocks whose fit failed get
    their neighbours' width rather than falling back to the class half-width."""
    path = os.path.join(ROOT, "game", "data", "alignments.json")
    if not os.path.exists(path):
        return []
    sys.path.insert(0, os.path.join(ROOT, "pipeline", "roads"))
    import alignment as al

    out = []
    for r in json.load(open(path))["routes"]:
        blocks = [b for b in (r.get("width") or {}).get("block_detail", []) if b.get("counts")]
        if not blocks:
            continue
        a = al.Alignment(r["pis"], r["radii"])
        mids = [(b["sta"][0] + b["sta"][1]) / 2 for b in blocks]
        rights = [b["right"] for b in blocks]
        lefts = [b["left"] for b in blocks]
        # short overlapping chunks, so a band never folds over itself on a curve
        for s0 in np.arange(0.0, a.length, chunk):
            stas = np.linspace(s0, min(s0 + chunk + step, a.length), max(2, int(chunk / step) + 1))
            right_side, left_side = [], []
            for s in stas:
                x, z, h = a.point_at(s)
                for side, o in ((right_side, np.interp(s, mids, rights) - ROAD_PAD_M),
                                (left_side, np.interp(s, mids, lefts) + ROAD_PAD_M)):
                    side.append((x + h[1] * o, z - h[0] * o))
            out.append(right_side + left_side[::-1])
    return out


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
    paved, got, yellow = build_masks(size_m)
    print(f"imagery covers {100.0 * got.mean():.0f}% of the play area")

    bld = draw_world_polys(n, size_m, building_polys(), int(BUILDING_PAD_M / MPP))
    rd = road_mask(n, size_m)
    # Whitewater below the dam is bright and desaturated, so it reads as pavement.
    # Mapped water is the principled way to remove it.
    water = json.load(open(os.path.join(ROOT, "game", "data", "water.json")))
    wpolys = [[(q["x"], q["z"]) for q in r.get("polygon", [])] for r in water.get("reaches", [])]
    wet = draw_world_polys(n, size_m, [w for w in wpolys if len(w) >= 3], int(2.0 / MPP))
    cand = paved & got & ~bld & ~rd & ~wet & ~rail_mask(n, size_m)
    print(f"paved pixels after removing {bld.sum()/ (1/MPP)**2:,.0f} m2 of buildings and roads: "
          f"{cand.sum() * MPP * MPP:,.0f} m2")

    # Mapped car parks are lots outright, whatever their colour (OSM gives no surface for
    # any of them here). Their service aisles stay in: the road plan cuts its own roads out.
    park = draw_world_polys(n, size_m, parking_polys(), 0)
    osm = park & got & ~bld & ~wet & ~road_mask(n, size_m, service=False)
    osm = ndimage.binary_opening(osm, iterations=1)
    lbl, nlab = ndimage.label(osm)
    sizes = ndimage.sum(osm, lbl, range(1, nlab + 1)) * MPP * MPP
    osm = np.isin(lbl, 1 + np.flatnonzero(sizes >= OSM_MIN_AREA_M2))
    print(f"OSM parking: {int((sizes >= OSM_MIN_AREA_M2).sum())} areas, {osm.sum() * MPP * MPP:,.0f} m2")

    cand &= ~park
    cand = ndimage.binary_opening(cand, iterations=1)
    cand = ndimage.binary_closing(cand, structure=np.ones((9, 9), bool))
    # A disc STRIP_M across: sidewalks, driveways and the outer lanes of a road wider than
    # its mask are narrower than any lot.
    r = int(STRIP_M / MPP / 2)
    disc = np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r
    cand = ndimage.binary_opening(cand, structure=disc)

    lbl, nlab = ndimage.label(cand)
    idx = np.arange(1, nlab + 1)
    area = ndimage.sum(cand, lbl, idx) * MPP * MPP
    yel = ndimage.median(yellow, lbl, idx)
    reach = ndimage.binary_dilation(rd | osm, iterations=int(CONNECT_M / MPP) + 1)
    touches = ndimage.maximum(reach, lbl, idx) > 0
    r = int(LOT_CORE_M / MPP / 2)
    disc = np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r
    core = ndimage.binary_opening(cand, structure=disc)
    wide = ndimage.sum(core, lbl, idx) * MPP * MPP >= LOT_CORE_FRACTION * area
    big = area >= MIN_AREA_M2
    colour = big & (yel < LOT_YELLOW_MAX)
    good = colour & touches & wide
    print(f"colour blobs >= {MIN_AREA_M2:.0f} m2: {int(big.sum())}; dropped {int((big & ~colour).sum())} "
          f"as gravel/dirt/lawn (median yellowness), {int((colour & ~wide).sum())} mostly narrower than "
          f"{LOT_CORE_M:.0f} m, {int((colour & wide & ~touches).sum())} with no road or car park "
          f"within {CONNECT_M:.0f} m")
    keep = np.isin(lbl, idx[good]) | osm
    kept = ndimage.label(keep)[1]

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
    print(f"kept {kept} lots ({int(good.sum())} from colour) of {nlab} blobs   area {area:,.0f} m2   rects {len(quads)}   "
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
