#!/usr/bin/env python3
"""Fetch OSM data for the Dixon play area (+500m margin) from Overpass API.

Saves raw JSON per category to data/raw/osm_<category>.json. Idempotent:
skips categories whose output file already exists unless --force is passed.
Polite: one request per category, retried with backoff on server busy (504),
short pause between requests.
"""
import argparse
import json
import os
import sys
import time

import requests
from pyproj import Transformer

sys.path.insert(0, os.path.dirname(__file__))
from common import DATA_RAW, OSM_MARGIN_M, OVERPASS_HEADERS, OVERPASS_URL, world_extent

os.makedirs(DATA_RAW, exist_ok=True)

_t = Transformer.from_crs("EPSG:26916", "EPSG:4326", always_xy=True)


def bbox_lonlat():
    min_e, min_n, max_e, max_n = world_extent()
    min_e -= OSM_MARGIN_M
    min_n -= OSM_MARGIN_M
    max_e += OSM_MARGIN_M
    max_n += OSM_MARGIN_M
    corners = [(min_e, min_n), (max_e, min_n), (min_e, max_n), (max_e, max_n)]
    lons, lats = [], []
    for e, n in corners:
        lon, lat = _t.transform(e, n)
        lons.append(lon)
        lats.append(lat)
    return min(lats), min(lons), max(lats), max(lons)  # south,west,north,east


S, W, N, E = bbox_lonlat()
BBOX = f"{S:.6f},{W:.6f},{N:.6f},{E:.6f}"

QUERIES = {
    "roads_rails": f"""
[out:json][timeout:180];
(
  way["highway"]({BBOX});
  way["railway"]({BBOX});
);
out body geom;
""",
    "power": f"""
[out:json][timeout:180];
(
  way["power"~"^(line|minor_line|cable)$"]({BBOX});
  node["power"~"^(pole|tower|portal|terminal|transformer)$"]({BBOX});
);
out body geom;
""",
    "buildings": f"""
[out:json][timeout:180];
(
  way["building"]({BBOX});
  relation["building"]({BBOX});
);
out body geom;
""",
    "water_landuse": f"""
[out:json][timeout:180];
(
  way["waterway"]({BBOX});
  way["natural"="water"]({BBOX});
  relation["natural"="water"]({BBOX});
  way["waterway"="riverbank"]({BBOX});
  way["landuse"]({BBOX});
  way["leisure"]({BBOX});
  way["natural"]["natural"!="tree"]({BBOX});
);
out body geom;
""",
    "parking": f"""
[out:json][timeout:180];
(
  way["amenity"~"^(parking|parking_space|fuel)$"]({BBOX});
  relation["amenity"="parking"]({BBOX});
  way["area:highway"]({BBOX});
);
out body geom;
""",
    "points": f"""
[out:json][timeout:180];
(
  node["amenity"]({BBOX});
  node["natural"="tree"]({BBOX});
  node["highway"="street_lamp"]({BBOX});
  node["barrier"]({BBOX});
  way["barrier"]({BBOX});
  node["historic"]({BBOX});
  node["tourism"]({BBOX});
  way["man_made"="bridge"]({BBOX});
);
out body geom;
""",
}


def fetch(name, query, max_attempts=6):
    out_path = os.path.join(DATA_RAW, f"osm_{name}.json")
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(OVERPASS_URL, data={"data": query}, headers=OVERPASS_HEADERS, timeout=200)
        except requests.exceptions.RequestException as ex:
            print(f"  [{name}] network error {ex}, retry {attempt}/{max_attempts}")
            time.sleep(10 * attempt)
            continue
        if r.status_code == 200:
            data = r.json()
            with open(out_path, "w") as f:
                json.dump(data, f)
            print(f"  [{name}] {len(data.get('elements', []))} elements -> {out_path}")
            return True
        print(f"  [{name}] HTTP {r.status_code}, retry {attempt}/{max_attempts}")
        time.sleep(10 * attempt)
    print(f"  [{name}] FAILED after {max_attempts} attempts")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    print(f"OSM bbox (south,west,north,east) = {BBOX}")
    for i, (name, query) in enumerate(QUERIES.items()):
        out_path = os.path.join(DATA_RAW, f"osm_{name}.json")
        if os.path.exists(out_path) and not args.force:
            print(f"  [{name}] exists, skipping (--force to refetch)")
            continue
        print(f"Fetching [{name}]...")
        ok = fetch(name, query)
        if not ok:
            sys.exit(1)
        if i < len(QUERIES) - 1:
            time.sleep(5)


if __name__ == "__main__":
    main()
