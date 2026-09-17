#!/usr/bin/env python3
"""Build the Dixon play-area and horizon heightmaps from the NED19 DEM tiles.

Outputs (game/data/):
  world_origin.json
  heightmap_play_1m.r32              raw-resampled + hydro-flattened river, 1m spacing
  heightmap_play_1m_road_conformed.r32   same + road corridors carved flat (~2% camber)
  heightmap_horizon_12.5m.r32        coarse 10km x 10km terrain for distant view
  water_reaches.json                 river reach polygons + flat pool elevations
                                      (consumed by build_vectors.py for water.json)

All heights are float32, little-endian, row-major starting at the NW corner
(row 0 = max northing), value = elevation_m - base_elevation_m. This matches
Godot's expectation of "north is -Z" when the raw buffer is fed row-by-row
into an Image starting at the top (north) row.
"""
import json
import os
import struct
import sys

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.vrt import WarpedVRT
from scipy.ndimage import distance_transform_edt, map_coordinates
from scipy.spatial import cKDTree
from shapely.geometry import LineString
from shapely.ops import linemerge, unary_union

sys.path.insert(0, os.path.dirname(__file__))
from common import (
    DEM_TILES, GAME_DATA, HORIZON_SIZE_M, HORIZON_SPACING_M,
    ORIGIN_EASTING, ORIGIN_NORTHING, PLAY_SPACING_M, SIZE_M, WORLD_CRS,
    horizon_extent, world_extent,
)
from osm_common import clip_lines_by_bounds, load_osm, relation_multipolygon_utm, way_polygon_utm

os.makedirs(GAME_DATA, exist_ok=True)


def warp_grid(min_e, min_n, max_e, max_n, spacing, resampling):
    width = int(round((max_e - min_e) / spacing))
    height = int(round((max_n - min_n) / spacing))
    dst_transform = Affine(spacing, 0.0, min_e, 0.0, -spacing, max_n)
    acc = np.full((height, width), np.nan, dtype=np.float32)
    for tile_path in DEM_TILES:
        with rasterio.open(tile_path) as src:
            with WarpedVRT(
                src, crs=WORLD_CRS, transform=dst_transform,
                width=width, height=height, resampling=resampling,
                src_nodata=src.nodata, nodata=np.nan,
            ) as vrt:
                arr = vrt.read(1).astype(np.float32)
        mask = np.isnan(acc) & ~np.isnan(arr)
        acc[mask] = arr[mask]
    return acc, dst_transform, width, height


def bilinear_sample(arr, transform, easting, northing):
    """Sample arr (row-major, transform maps col,row -> e,n) at UTM points."""
    inv = ~transform
    cols, rows = inv * (easting, northing)
    return map_coordinates(arr, [rows, cols], order=1, mode="nearest")


def build_water_reaches(play_extent):
    """Assemble Rock River polygon(s) in/near the play area, split into
    reaches by the dam, and estimate each reach's flat pool elevation from
    the raw DEM (percentile of pixels well inside the polygon)."""
    min_e, min_n, max_e, max_n = play_extent
    pad = 300.0
    wl = load_osm("water_landuse")
    wl = clip_lines_by_bounds(wl, min_e, min_n, max_e, max_n, pad=pad)

    # Split water polygons into the big national river RELATION (assembled
    # from many outer-way segments -- this is the one that lacks a proper
    # inner-ring hole for islands, likely because the relation's inner
    # members weren't within our AOI clip) vs. locally-mapped WAY features
    # (small ponds, backwater lagoons, etc, each its own distinct polygon).
    # Island subtraction below is applied ONLY to the relation polygon, so a
    # legitimately-mapped lagoon *inside* an island's footprint (a separate
    # natural=water way) is not accidentally erased along with it.
    relation_polys = []
    way_polys = []
    for el in wl:
        if el["type"] == "relation" and el.get("tags", {}).get("natural") == "water":
            p = relation_multipolygon_utm(el)
            if p is not None and not p.is_empty:
                relation_polys.append(p)
        elif el["type"] == "way":
            tags = el.get("tags", {})
            if tags.get("natural") == "water" or tags.get("waterway") == "riverbank":
                p = way_polygon_utm(el)
                if p is not None:
                    way_polys.append(p)
    if not relation_polys and not way_polys:
        print("  WARNING: no river polygon found near play area; skipping hydro-flatten")
        return []

    # Subtract river islands (Van Arnam Island, Willow Park islet, ...) --
    # these are mapped as separate leisure=nature_reserve/place=island(et)
    # ways, not as inner rings of the water relation, so they must be
    # explicitly punched out of the water polygon or the island terrain gets
    # wrongly flattened/submerged by hydro-flatten below.
    island_polys = []
    for el in wl:
        tags = el.get("tags", {})
        if tags.get("place") in ("island", "islet") or tags.get("natural") == "island":
            p = way_polygon_utm(el) if el["type"] == "way" else (
                relation_multipolygon_utm(el) if el["type"] == "relation" else None)
            if p is not None and not p.is_empty:
                island_polys.append(p)

    relation_union = unary_union(relation_polys) if relation_polys else None
    if relation_union is not None and island_polys:
        islands_union = unary_union(island_polys)
        relation_union = relation_union.difference(islands_union)
        print(f"  subtracted {len(island_polys)} island polygon(s) ({islands_union.area:.0f} m^2) from the river relation")

    all_polys = ([relation_union] if relation_union is not None and not relation_union.is_empty else []) + way_polys
    river = unary_union(all_polys)
    aoi_box = _box(min_e - pad, min_n - pad, max_e + pad, max_n + pad)
    river = river.intersection(aoi_box)
    if river.is_empty:
        print("  WARNING: river polygon empty after clipping to AOI")
        return []

    # dam line(s) -- used to split the *main channel* piece into two reaches.
    # shapely's vector split() is unreliable on messy multi-segment riverbank
    # rings (see below), so we fit the dam's dominant crossing direction via
    # PCA and then cut with a big half-plane polygon (robust: it's just an
    # intersection, not a topological split).
    dam_lines = []
    for el in wl:
        if el["type"] == "way" and el.get("tags", {}).get("waterway") == "dam":
            geom = el.get("geometry")
            if geom and len(geom) >= 2:
                from osm_common import geom_to_utm_coords
                dam_lines.append(LineString(geom_to_utm_coords(geom)))
    dam = None
    if dam_lines:
        # The dam is often mapped as several disjoint/zigzagging ways that
        # don't form one clean line end-to-end (linemerge can even produce a
        # path whose first/last coordinate coincide). What we actually need
        # is just the dam's *dominant crossing direction* through the river,
        # so fit it via PCA over all dam vertices instead of trusting path
        # endpoints -- robust to however the source ways are split/ordered.
        all_coords = np.concatenate([np.array(l.coords) for l in dam_lines], axis=0)
        centroid = all_coords.mean(axis=0)
        centered = all_coords - centroid
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        direction = vt[0]  # principal axis = direction along the dam crossing
        dam = LineString([tuple(centroid - direction * 100), tuple(centroid + direction * 100)])

    pieces = list(river.geoms) if hasattr(river, "geoms") else [river]
    MAIN_CHANNEL_AREA_M2 = 20000.0

    raw_arr, raw_transform, rw, rh = warp_grid(min_e - pad, min_n - pad, max_e + pad, max_n + pad, 2.0, Resampling.bilinear)

    def half_plane_polygon(centroid, direction, sign, big=8000.0):
        """Polygon covering the entire half-plane on one side of the line
        through `centroid` along `direction` (sign = +1/-1 picks the side,
        matching the same cross-product convention used elsewhere)."""
        cx, cy = centroid
        dx, dy = direction
        norm = (dx ** 2 + dy ** 2) ** 0.5 or 1.0
        dx, dy = dx / norm, dy / norm
        px, py = -dy * sign, dx * sign  # perpendicular, pointing to the `sign` side
        p1 = (cx - dx * big, cy - dy * big)
        p2 = (cx + dx * big, cy + dy * big)
        p3 = (p2[0] + px * big, p2[1] + py * big)
        p4 = (p1[0] + px * big, p1[1] + py * big)
        from shapely.geometry import Polygon as _Poly
        return _Poly([p1, p2, p3, p4])

    reaches = []
    for i, poly in enumerate(pieces):
        if poly.area < 50:
            continue

        is_main_channel = poly.area > MAIN_CHANNEL_AREA_M2 and dam is not None and poly.intersects(dam.buffer(5.0))
        if is_main_channel:
            for sign, label in ((1, "a"), (-1, "b")):
                side_poly = poly.intersection(half_plane_polygon(centroid, direction, sign))
                if side_poly.geom_type not in ("Polygon", "MultiPolygon"):
                    # intersection can return a GeometryCollection with stray
                    # points/lines at the cut boundary -- keep only the areal parts
                    polys_only = [g for g in getattr(side_poly, "geoms", []) if g.geom_type in ("Polygon", "MultiPolygon")]
                    side_poly = unary_union(polys_only) if polys_only else None
                if side_poly is None or side_poly.is_empty:
                    continue
                core = side_poly.buffer(-6.0)
                if core.is_empty:
                    core = side_poly.buffer(-2.0)
                if core.is_empty:
                    core = side_poly
                m = rasterize([(core, 1)], out_shape=(rh, rw), transform=raw_transform, fill=0, dtype=np.uint8).astype(bool)
                vals = raw_arr[m & ~np.isnan(raw_arr)]
                if vals.size == 0:
                    continue
                pool = float(np.round(np.percentile(vals, 15), 2))
                reaches.append({"id": f"river_{label}", "polygon": side_poly, "pool_level_m": pool,
                                 "centroid_n": side_poly.centroid.y})
        else:
            core = poly.buffer(-6.0)
            if core.is_empty:
                core = poly.buffer(-2.0)
            if core.is_empty:
                core = poly
            poly_mask = rasterize([(core, 1)], out_shape=(rh, rw), transform=raw_transform, fill=0, dtype=np.uint8).astype(bool)
            vals = raw_arr[poly_mask & ~np.isnan(raw_arr)]
            if vals.size == 0:
                continue
            pool = float(np.round(np.percentile(vals, 15), 2))
            reaches.append({"id": f"pond_{i}", "polygon": poly, "pool_level_m": pool,
                             "centroid_n": poly.centroid.y})

    # label the two river reaches by which side actually has the higher pool
    # (the impounded/upstream side of a dam sits higher than the tailwater)
    river_reaches = [r for r in reaches if r["id"].startswith("river_")]
    if len(river_reaches) == 2:
        river_reaches.sort(key=lambda r: -r["pool_level_m"])
        river_reaches[0]["id"] = "river_upstream"
        river_reaches[1]["id"] = "river_downstream"

    reaches.sort(key=lambda r: -r["centroid_n"])
    print(f"  found {len(reaches)} water reach(es): " + ", ".join(f"{r['id']}={r['pool_level_m']}m" for r in reaches))
    return reaches


def _box(minx, miny, maxx, maxy):
    from shapely.geometry import box
    return box(minx, miny, maxx, maxy)


def hydro_flatten(arr, transform, width, height, reaches, max_depth=3.0):
    out = arr.copy()
    spacing = abs(transform.a)
    for r in reaches:
        mask = rasterize([(r["polygon"], 1)], out_shape=(height, width), transform=transform, fill=0, dtype=np.uint8).astype(bool)
        if r.get("dam_line") is not None:
            ys_idx, xs_idx = np.mgrid[0:height, 0:width]
            grid_e, grid_n = transform * (xs_idx + 0.5, ys_idx + 0.5)
            (x0, y0), (x1, y1) = list(r["dam_line"].coords)[0], list(r["dam_line"].coords)[-1]
            dx, dy = x1 - x0, y1 - y0
            cross = dx * (grid_n - y0) - dy * (grid_e - x0)
            mask = mask & (np.sign(cross) == r["dam_sign"])
        if not mask.any():
            continue
        dist = distance_transform_edt(mask, sampling=(spacing, spacing))
        depth = np.clip(dist * 0.5, 0.0, max_depth)
        bed = r["pool_level_m"] - depth
        out[mask] = bed.astype(np.float32)[mask]
    return out


def load_road_lines(min_e, min_n, max_e, max_n):
    from osm_common import road_width_m, is_bridge, way_line_utm
    roads = load_osm("roads_rails")
    roads = clip_lines_by_bounds(roads, min_e, min_n, max_e, max_n, pad=50.0)
    out = []
    for el in roads:
        tags = el.get("tags", {})
        if "highway" not in tags:
            continue
        if is_bridge(tags):
            continue
        line = way_line_utm(el)
        if line is None or line.length < 1.0:
            continue
        out.append((line, road_width_m(tags)))
    return out


def smooth_profile(dists, elevs, window_m=15.0):
    if len(dists) < 3:
        return elevs
    out = np.array(elevs, dtype=np.float64)
    for i in range(len(dists)):
        lo = dists[i] - window_m / 2
        hi = dists[i] + window_m / 2
        sel = (dists >= lo) & (dists <= hi)
        out[i] = np.mean(np.array(elevs)[sel])
    return out


def road_conform(arr, transform, width, height, roads):
    out = arr.copy()
    all_pts = []   # (e, n)
    all_elev = []
    all_hw = []    # half-width at that sample
    corridor_polys = []

    for line, wid in roads:
        n = max(2, int(line.length / 2.0))
        dists = np.linspace(0, line.length, n)
        pts = [line.interpolate(d) for d in dists]
        es = np.array([p.x for p in pts])
        ns = np.array([p.y for p in pts])
        elevs = bilinear_sample(arr, transform, es, ns)
        elevs_smooth = smooth_profile(dists, elevs, window_m=15.0)
        half_w = wid / 2.0
        for e, n, el in zip(es, ns, elevs_smooth):
            all_pts.append((e, n))
            all_elev.append(el)
            all_hw.append(half_w)
        corridor_polys.append((line.buffer(half_w + 1.5, cap_style=2), 1))

    if not all_pts:
        return out

    corridor_mask = rasterize(corridor_polys, out_shape=(height, width), transform=transform, fill=0, dtype=np.uint8).astype(bool)
    rows, cols = np.nonzero(corridor_mask)
    if rows.size == 0:
        return out
    xs, ys = transform * (cols + 0.5, rows + 0.5)  # pixel-center -> UTM

    tree = cKDTree(np.array(all_pts))
    dist_to_center, idx = tree.query(np.column_stack([xs, ys]), k=1)
    center_elev = np.array(all_elev)[idx]
    half_w = np.array(all_hw)[idx]
    buffer_r = half_w + 1.5

    camber_drop = np.clip(0.02 * dist_to_center, 0.0, 0.02 * (half_w + 0.5))
    conformed = center_elev - camber_drop

    # feather the last ~2m of the buffer back to the raw surface
    feather_start = np.maximum(buffer_r - 2.0, half_w)
    t = np.clip((dist_to_center - feather_start) / np.maximum(buffer_r - feather_start, 0.01), 0.0, 1.0)
    alpha = 1.0 - (3 * t ** 2 - 2 * t ** 3)  # smoothstep, 1 at center -> 0 at edge
    raw_here = arr[rows, cols]
    blended = alpha * conformed + (1 - alpha) * raw_here

    out[rows, cols] = blended.astype(np.float32)
    return out


def write_r32(path, arr):
    arr = np.ascontiguousarray(arr.astype("<f4"))
    with open(path, "wb") as f:
        f.write(arr.tobytes())


def main():
    print("Building play-area heightmap...")
    min_e, min_n, max_e, max_n = world_extent()
    play_arr, play_transform, pw, ph = warp_grid(min_e, min_n, max_e, max_n, PLAY_SPACING_M, Resampling.cubic)
    print(f"  play grid: {pw}x{ph} @ {PLAY_SPACING_M}m, elev range {np.nanmin(play_arr):.2f}..{np.nanmax(play_arr):.2f}")

    base_elevation_m = float(np.floor(np.nanmin(play_arr)) - 2.0)  # margin for riverbed carve below min raw elev

    print("Assembling river reaches + hydro-flattening...")
    reaches = build_water_reaches((min_e, min_n, max_e, max_n))
    play_hydro = hydro_flatten(play_arr, play_transform, pw, ph, reaches) if reaches else play_arr.copy()

    print("Road-conforming...")
    roads = load_road_lines(min_e, min_n, max_e, max_n)
    print(f"  {len(roads)} non-bridge road segments")
    play_road = road_conform(play_hydro, play_transform, pw, ph, roads)

    print("Building horizon heightmap...")
    hmin_e, hmin_n, hmax_e, hmax_n = horizon_extent()
    horizon_arr, horizon_transform, hw, hh = warp_grid(hmin_e, hmin_n, hmax_e, hmax_n, HORIZON_SPACING_M, Resampling.average)
    if reaches:
        horizon_arr = hydro_flatten(horizon_arr, horizon_transform, hw, hh, reaches, max_depth=2.0)
    print(f"  horizon grid: {hw}x{hh} @ {HORIZON_SPACING_M}m")

    # write outputs, offset by base_elevation_m
    write_r32(os.path.join(GAME_DATA, "heightmap_play_1m.r32"), play_hydro - base_elevation_m)
    write_r32(os.path.join(GAME_DATA, "heightmap_play_1m_road_conformed.r32"), play_road - base_elevation_m)
    write_r32(os.path.join(GAME_DATA, "heightmap_horizon_12.5m.r32"), horizon_arr - base_elevation_m)

    world_origin = {
        "crs": "EPSG:26916",
        "origin_easting": ORIGIN_EASTING,
        "origin_northing": ORIGIN_NORTHING,
        "base_elevation_m": base_elevation_m,
        "size_m": SIZE_M,
        "godot_axis_convention": "x = east (easting - origin_easting), y = up (elevation_m - base_elevation_m), z = -north (-(northing - origin_northing))",
        "heightmaps": {
            "play": {
                "file": "heightmap_play_1m.r32",
                "road_conformed_file": "heightmap_play_1m_road_conformed.r32",
                "format": "float32 little-endian, row-major, row 0 = north edge (max northing), col 0 = west edge (min easting)",
                "width": pw, "height": ph, "spacing_m": PLAY_SPACING_M,
                "origin_easting": min_e, "origin_northing_top": max_n,
                "elev_min_m": float(np.nanmin(play_hydro)), "elev_max_m": float(np.nanmax(play_hydro)),
            },
            "horizon": {
                "file": "heightmap_horizon_12.5m.r32",
                "format": "float32 little-endian, row-major, row 0 = north edge (max northing), col 0 = west edge (min easting)",
                "width": hw, "height": hh, "spacing_m": HORIZON_SPACING_M,
                "size_m": HORIZON_SIZE_M,
                "origin_easting": hmin_e, "origin_northing_top": hmax_n,
                "elev_min_m": float(np.nanmin(horizon_arr)), "elev_max_m": float(np.nanmax(horizon_arr)),
            },
        },
        "river_reaches": [
            {"id": r["id"], "pool_level_m": r["pool_level_m"], "pool_level_local_y": r["pool_level_m"] - base_elevation_m}
            for r in reaches
        ],
    }
    with open(os.path.join(GAME_DATA, "world_origin.json"), "w") as f:
        json.dump(world_origin, f, indent=2)

    # save reach polygons (UTM) for build_vectors.py to consume -> water.json
    def explode_polys(poly):
        """A reach polygon can end up a MultiPolygon (e.g. an island split
        leaves disjoint slivers) -- emit one ring per part rather than
        crashing on/silently dropping the non-primary parts."""
        return list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]

    reaches_out_list = []
    for r in reaches:
        parts = explode_polys(r["polygon"])
        for j, part in enumerate(parts):
            if part.exterior is None or part.area < 10:
                continue
            suffix = "" if len(parts) == 1 else f"_{j}"
            reaches_out_list.append({
                "id": r["id"] + suffix, "pool_level_m": r["pool_level_m"],
                "polygon_utm": list(part.exterior.coords),
            })
    reaches_out = {"reaches": reaches_out_list}
    with open(os.path.join(GAME_DATA, "_water_reaches_utm.json"), "w") as f:
        json.dump(reaches_out, f)

    print(f"base_elevation_m = {base_elevation_m}")
    print("Done.")


if __name__ == "__main__":
    main()
