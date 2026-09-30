#!/usr/bin/env python3
"""Downloads Illinois 2025 6-inch orthoimagery covering the play area.

Why this instead of screenshots: the state publishes 0.1524 m/px leaf-off imagery through
an ArcGIS ImageServer, and the request takes the bounding box, so every tile is EXACTLY
georeferenced -- no rotation to recover, no crop offset, no fitting. It is ~4x finer than
a Google Earth screen capture and it is public domain.

  service : https://data.isgs.illinois.edu/arcgis/rest/services/Imagery/IL_Blk1_West_2025/ImageServer
  native  : 0.1524 m/px, EPSG:3857, leaf-off

Note on EPSG:3857: at Dixon's latitude a "metre" of Web Mercator is only cos(lat) real
metres, so the requested extent is divided by cos(lat) to get true ground metres.

Writes tiles + per-tile georef JSON into data/raw/il2025/, each recording the world-space
(x, z) of its top-left corner so downstream extraction needs no registration step.

The recorded world box is only where the tile was asked for: the game's UTM
grid is turned ~1.7 degrees from Mercator's north, so the picture is up to
~15 m off it at two corners. Each tile also gets `pixel_from_world`, the exact
mapping (georef_affine.py), which is what to place it by.

Run: cd pipeline/aerial && ../../.venv/bin/python fetch_illinois.py [--mpp 0.25] [--tile 512]
"""
import argparse
import json
import math
import os
import time
import urllib.request

from pyproj import Transformer

from georef_affine import pixel_mapping, projector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(ROOT, "data", "raw", "il2025")
SERVICE = ("https://data.isgs.illinois.edu/arcgis/rest/services/Imagery/"
           "IL_Blk1_West_2025/ImageServer/exportImage")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mpp", type=float, default=0.25, help="ground metres per pixel to request")
    ap.add_argument("--tile", type=float, default=512.0, help="tile size in ground metres")
    ap.add_argument("--limit", type=int, default=0, help="stop after N tiles (0 = all)")
    args = ap.parse_args()

    origin = json.load(open(os.path.join(ROOT, "game", "data", "world_origin.json")))
    E0, N0, SIZE = origin["origin_easting"], origin["origin_northing"], origin["size_m"]
    utm_to_wgs = Transformer.from_crs("EPSG:26916", "EPSG:4326", always_xy=True)
    wgs_to_merc = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

    merc = projector()
    os.makedirs(OUT_DIR, exist_ok=True)
    n = int(math.ceil(SIZE / args.tile))
    px = int(round(args.tile / args.mpp))
    made, skipped = 0, 0
    index = []

    for iz in range(n):
        for ix in range(n):
            wx0 = ix * args.tile
            wz0 = -SIZE + iz * args.tile          # world z is negative northwards
            wx1 = min(wx0 + args.tile, SIZE)
            wz1 = min(wz0 + args.tile, 0.0)
            name = f"tile_{ix:02d}_{iz:02d}"
            png = os.path.join(OUT_DIR, name + ".png")
            meta_path = os.path.join(OUT_DIR, name + "_georef.json")

            # world -> UTM -> lon/lat -> web mercator, for both corners
            corners = []
            for wx, wz in ((wx0, wz0), (wx1, wz1)):
                lon, lat = utm_to_wgs.transform(E0 + wx, N0 - wz)
                corners.append(wgs_to_merc.transform(lon, lat))
            (mx0, my0), (mx1, my1) = corners
            bbox = f"{min(mx0,mx1)},{min(my0,my1)},{max(mx0,mx1)},{max(my0,my1)}"

            meta = {
                "tile": name,
                "world_x0": wx0, "world_z0": wz0,
                "world_x1": wx1, "world_z1": wz1,
                "size_px": [px, px],
                "mpp": args.mpp,
                "note": "north-up, axis-aligned in world coords: "
                        "x = world_x0 + px*mpp ; z = world_z0 + py*mpp",
                "source": "Illinois IL_Blk1_West_2025 (0.1524 m/px native), EPSG:3857 request",
            }

            meta["pixel_from_world"], meta["affine_residual_m"] = pixel_mapping(meta, merc)

            if os.path.exists(png) and os.path.getsize(png) > 10000:
                skipped += 1
                index.append(meta)
                continue

            url = (f"{SERVICE}?bbox={bbox}&bboxSR=3857&imageSR=3857"
                   f"&size={px},{px}&format=png&f=image")
            try:
                with urllib.request.urlopen(url, timeout=180) as r:
                    data = r.read()
            except Exception as e:                       # keep going; report at the end
                print(f"  {name}: FAILED ({e})")
                continue
            if len(data) < 10000:
                print(f"  {name}: empty response ({len(data)} bytes) - outside coverage?")
                continue
            open(png, "wb").write(data)
            json.dump(meta, open(meta_path, "w"), indent=1)
            index.append(meta)
            made += 1
            print(f"  {name}: {len(data)//1024} KB  world x {wx0:.0f}..{wx1:.0f}  z {wz0:.0f}..{wz1:.0f}")
            time.sleep(0.3)                              # be polite to the state server
            if args.limit and made >= args.limit:
                break
        if args.limit and made >= args.limit:
            break

    json.dump({"tiles": index, "mpp": args.mpp, "tile_m": args.tile},
              open(os.path.join(OUT_DIR, "index.json"), "w"), indent=1)
    print(f"downloaded {made} tiles, {skipped} already present -> {OUT_DIR}")


if __name__ == "__main__":
    main()
