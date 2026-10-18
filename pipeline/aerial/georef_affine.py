#!/usr/bin/env python3
"""Records where each Illinois 2025 tile's pixels really are in the game world.

fetch_illinois.py asks the image service for a Web Mercator box made from two
opposite corners of a 512 m square of the game world, and records the square as
the tile's extent. But the game's frame is UTM zone 16N, whose grid north is
about 1.7 degrees off true (Mercator) north at Dixon, so the picture is turned
and stretched against that square: right along one diagonal, up to ~15 m off
at the other two corners. Tracing or extracting against `world_x0 + px * mpp`
inherits that error.

This adds to each tile (in index.json and its _georef.json) the exact mapping
`pixel_from_world`: [a, b, c, d, e, f] with px = a*x + b*z + c and
py = d*x + e*z + f (game meters to tile pixels), fitted through the
projection at three corners, and `affine_residual_m`, its worst error at the
fourth corner and the center (millimeters). aerial_crop.py uses it.

Run: cd pipeline/aerial && ../../.venv/bin/python georef_affine.py
"""
import json
import os

from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
TILES_DIR = os.path.join(ROOT, "data", "raw", "il2025")


def projector():
    """game (x, z) -> Web Mercator (mx, my), as fetch_illinois.py computes it."""
    origin = json.load(open(os.path.join(ROOT, "game", "data", "world_origin.json")))
    e0, n0 = origin["origin_easting"], origin["origin_northing"]
    utm_to_wgs = Transformer.from_crs("EPSG:26916", "EPSG:4326", always_xy=True)
    wgs_to_merc = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

    def merc(x, z):
        lon, lat = utm_to_wgs.transform(e0 + x, n0 - z)
        return wgs_to_merc.transform(lon, lat)
    return merc


def pixel_mapping(tile, merc):
    """The tile's pixel_from_world affine and its worst residual in meters."""
    wx0, wz0, wx1, wz1 = tile["world_x0"], tile["world_z0"], tile["world_x1"], tile["world_z1"]
    width, height = tile["size_px"]
    (ax, ay), (bx, by) = merc(wx0, wz0), merc(wx1, wz1)
    mx0, mx1, my0, my1 = min(ax, bx), max(ax, bx), min(ay, by), max(ay, by)
    # The image server keeps pixels square: when the requested box's aspect differs from the
    # image's, it widens the short side about its centre (checked against the server's own
    # returned extent: a 705.7 x 668.5 m request came back 705.7 x 705.7). Without this, rows
    # drift up to ~14 m at a tile's top and bottom edges.
    want = width / height
    if (mx1 - mx0) / (my1 - my0) > want:
        half, mid = (mx1 - mx0) / want / 2, (my0 + my1) / 2
        my0, my1 = mid - half, mid + half
    else:
        half, mid = (my1 - my0) * want / 2, (mx0 + mx1) / 2
        mx0, mx1 = mid - half, mid + half

    def pixel(x, z):
        mx, my = merc(x, z)
        return (mx - mx0) / (mx1 - mx0) * width, (my1 - my) / (my1 - my0) * height

    (p0, q0), (p1, q1), (p2, q2) = pixel(wx0, wz0), pixel(wx1, wz0), pixel(wx0, wz1)
    a, d = (p1 - p0) / (wx1 - wx0), (q1 - q0) / (wx1 - wx0)
    b, e = (p2 - p0) / (wz1 - wz0), (q2 - q0) / (wz1 - wz0)
    c, f = p0 - a * wx0 - b * wz0, q0 - d * wx0 - e * wz0
    worst = 0.0
    for x, z in ((wx1, wz1), ((wx0 + wx1) / 2, (wz0 + wz1) / 2)):
        px, py = pixel(x, z)
        worst = max(worst, abs(a * x + b * z + c - px) * tile["mpp"], abs(d * x + e * z + f - py) * tile["mpp"])
    return [a, b, c, d, e, f], worst


def main():
    merc = projector()
    index_path = os.path.join(TILES_DIR, "index.json")
    index = json.load(open(index_path))
    worst = 0.0
    for tile in index["tiles"]:
        mapping, residual = pixel_mapping(tile, merc)
        tile["pixel_from_world"] = mapping
        tile["affine_residual_m"] = round(residual, 4)
        worst = max(worst, residual)
        georef = os.path.join(TILES_DIR, f"{tile['tile']}_georef.json")
        if os.path.exists(georef):
            json.dump(tile, open(georef, "w"), indent=1)
    json.dump(index, open(index_path, "w"), indent=1)
    print(f"{len(index['tiles'])} tiles; worst affine residual {worst * 1000:.1f} mm")


if __name__ == "__main__":
    main()
