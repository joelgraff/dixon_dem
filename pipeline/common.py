"""Shared configuration for the Dixon data pipeline.

All coordinates in this module (except lon/lat) are UTM 16N (EPSG:26916) meters.
"""
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEMS_DIR = os.path.join(ROOT, "dems")
DATA_RAW = os.path.join(ROOT, "data", "raw")
GAME_DATA = os.path.join(ROOT, "game", "data")
CAPTURES_DIR = os.path.join(ROOT, "captures", "pipeline")

SRC_CRS = "EPSG:4269"     # NAD83 geographic, native CRS of the NED19 .img tiles
WORLD_CRS = "EPSG:26916"  # NAD83 / UTM zone 16N, the game's world CRS

# The two NED19 1/9" Lee County tiles that jointly cover both the play area
# and the 10x10km horizon extent (play area straddles the -89.5 deg tile seam).
DEM_TILES = [
    os.path.join(DEMS_DIR, "ned19_n42x00_w089x50_il_leeco_2009.img"),
    os.path.join(DEMS_DIR, "ned19_n42x00_w089x75_il_leeco_2009.img"),
]

# --- Play area definition ------------------------------------------------
# Derived from real OSM landmark coordinates (Overpass query, 2026-09-17):
# a clean square in UTM 16N, integer-meter origin, chosen so every required
# landmark (Galena Ave bridge, Dixon dam, Van Arnam Island, Page Park /
# Dixon HS, Lincoln statue, Lee County Courthouse, Dixon Theatre, Reagan
# Boyhood Home, Nachusa House site, Dixon Memorial Arch) sits inside with
# margin. See docs/pipeline_notes.md for the landmark survey.
ORIGIN_EASTING = 292300.0
ORIGIN_NORTHING = 4634000.0
SIZE_M = 2700.0  # play-area square edge length, "~2.5 x 2.5 km" per brief

# Base elevation is set by build_heightmap.py (min play-area sampled elev,
# rounded) once the DEM is read; kept here as fallback only.
DEFAULT_BASE_ELEVATION_M = 190.0

# --- Heightmap resolutions ------------------------------------------------
PLAY_SPACING_M = 1.0     # play-area heightmap grid spacing
HORIZON_SIZE_M = 10000.0  # horizon heightmap edge length
HORIZON_SPACING_M = 12.5  # horizon heightmap grid spacing (~800x800 grid)

# OSM fetch margin around the play area
OSM_MARGIN_M = 500.0

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_HEADERS = {
    "User-Agent": "DixonGameDataPipeline/1.0 (contact: monograff76@gmail.com)"
}

# Known landmark anchor points (lon, lat), surveyed via Overpass on 2026-09-17.
# Used to tag landmark_id on the nearest matching building/point in build_vectors.py.
LANDMARK_LONLAT = {
    "lee_county_courthouse": (-89.4812625, 41.8421983),
    "dixon_theatre": (-89.4821248, 41.8431317),
    "reagan_boyhood_home": (-89.4805721, 41.8361721),
    "nachusa_house": (-89.4818592, 41.8421379),  # interpolated, not addr-tagged in OSM
    "lincoln_statue": (-89.4851149, 41.8465647),
    "dixon_arch": (-89.4819832, 41.8420208),
    "galena_bridge": (-89.4835830, 41.8456930),
    "dixon_dam": (-89.4809000, 41.8455500),
}


def world_extent():
    """Returns (min_e, min_n, max_e, max_n) of the play area in UTM meters."""
    return (
        ORIGIN_EASTING,
        ORIGIN_NORTHING,
        ORIGIN_EASTING + SIZE_M,
        ORIGIN_NORTHING + SIZE_M,
    )


def horizon_extent():
    cx = ORIGIN_EASTING + SIZE_M / 2.0
    cy = ORIGIN_NORTHING + SIZE_M / 2.0
    half = HORIZON_SIZE_M / 2.0
    return (cx - half, cy - half, cx + half, cy + half)


def load_world_origin():
    path = os.path.join(GAME_DATA, "world_origin.json")
    with open(path) as f:
        return json.load(f)


def to_godot(easting, northing, elevation_m, base_elevation_m):
    """UTM (easting, northing, elevation) -> Godot local (x east, y up, z south->neg north)."""
    x = easting - ORIGIN_EASTING
    z = -(northing - ORIGIN_NORTHING)
    y = elevation_m - base_elevation_m
    return x, y, z
