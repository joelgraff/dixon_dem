#!/usr/bin/env python3
"""Turn the raw OSM JSON (data/raw/osm_*.json) into per-layer game data
(game/data/*.json) in Godot local coordinates (x east, z = -north, meters),
with terrain Y sampled from the heightmaps built by build_heightmap.py.

Must run after build_heightmap.py (needs game/data/world_origin.json and the
.r32 heightmaps to sample vertex elevations).
"""
import json
import os
import sys

import numpy as np
from affine import Affine
from pyproj import Transformer
from scipy.ndimage import map_coordinates
from shapely.geometry import Point

sys.path.insert(0, os.path.dirname(__file__))
from common import GAME_DATA, LANDMARK_LONLAT, ORIGIN_EASTING, ORIGIN_NORTHING, to_godot
from osm_common import (
    is_bridge, load_osm, relation_multipolygon_utm, road_lanes, road_layer,
    road_width_m, way_line_utm, way_polygon_utm,
)

_T_LONLAT_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:26916", always_xy=True)


def load_grid(name):
    info = WORLD_ORIGIN["heightmaps"]["play" if name == "play_road" else name]
    path = os.path.join(GAME_DATA, info["road_conformed_file"] if name == "play_road" else info["file"])
    w, h = info["width"], info["height"]
    arr = np.fromfile(path, dtype="<f4").reshape(h, w)
    transform = Affine(info["spacing_m"], 0.0, info["origin_easting"], 0.0, -info["spacing_m"], info["origin_northing_top"])
    return arr, transform


def bilinear_sample(arr, transform, e, n):
    inv = ~transform
    col, row = inv * (np.asarray(e), np.asarray(n))
    return map_coordinates(arr, [np.atleast_1d(row), np.atleast_1d(col)], order=1, mode="nearest")


def sample_y(arr, transform, e, n):
    return float(bilinear_sample(arr, transform, [e], [n])[0])


def godot_xz(e, n):
    x = e - ORIGIN_EASTING
    z = -(n - ORIGIN_NORTHING)
    return x, z


def ensure_ccw(coords):
    """coords: list of (x,z) Godot-space. Returns CCW-ordered copy (shoelace test
    in x/z plane; Godot z = -north so CCW in x/z corresponds to a sensible
    winding for an upward-facing polygon)."""
    area2 = 0.0
    for i in range(len(coords) - 1):
        x1, z1 = coords[i]
        x2, z2 = coords[i + 1]
        area2 += x1 * z2 - x2 * z1
    if area2 < 0:
        return list(reversed(coords))
    return coords


def main():
    global WORLD_ORIGIN
    with open(os.path.join(GAME_DATA, "world_origin.json")) as f:
        WORLD_ORIGIN = json.load(f)

    raw_arr, raw_tf = load_grid("play")
    road_arr, road_tf = load_grid("play_road")

    build_roads_rails(raw_arr, raw_tf, road_arr, road_tf)
    build_buildings(raw_arr, raw_tf)
    build_water(raw_arr, raw_tf)
    build_landuse(raw_arr, raw_tf)
    build_points(raw_arr, raw_tf)  # pois, trees, lamps
    print("build_vectors: done.")


# ---------------------------------------------------------------------------
def landmark_lonlat_utm():
    out = {}
    for k, (lon, lat) in LANDMARK_LONLAT.items():
        e, n = _T_LONLAT_TO_UTM.transform(lon, lat)
        out[k] = (e, n)
    return out


# Distance-fallback candidates only (used when a building has no matching
# name tag). dixon_arch is deliberately excluded here: it's a small standalone
# monument resolved unambiguously via BUILDING_NAME_HINTS, and including it in
# the distance fallback would pull in unrelated nearby buildings (it sits ~15m
# from the interpolated nachusa_house anchor).
BUILDING_LANDMARK_KEYS = ["lee_county_courthouse", "dixon_theatre", "reagan_boyhood_home", "nachusa_house"]

# Name keywords checked first (most reliable) before falling back to nearest-
# anchor distance -- several landmark anchors sit only a few meters apart
# (e.g. Dixon Memorial Arch vs. the interpolated Nachusa House site), so pure
# distance matching alone mis-assigns them.
BUILDING_NAME_HINTS = [
    ("courthouse", "lee_county_courthouse"),
    ("theatre", "dixon_theatre"),
    ("theater", "dixon_theatre"),
    ("boyhood home", "reagan_boyhood_home"),
    ("memorial arch", "dixon_arch"),
    ("nachusa", "nachusa_house"),
]


def building_name_hint(tags):
    name = (tags.get("name") or "").lower()
    if not name:
        return None
    for kw, key in BUILDING_NAME_HINTS:
        if kw in name:
            return key
    return None


def estimate_height_m(tags, footprint_area_m2):
    def parse_num(s):
        try:
            return float("".join(ch for ch in s if (ch.isdigit() or ch == "." or ch == "-")))
        except (ValueError, TypeError):
            return None

    if "height" in tags:
        v = parse_num(tags["height"])
        if v:
            return round(v, 1)
    if "building:height" in tags:
        v = parse_num(tags["building:height"])
        if v:
            return round(v, 1)

    levels = None
    for key in ("building:levels", "levels"):
        if key in tags:
            levels = parse_num(tags[key])
            if levels:
                break

    btype = tags.get("building", "yes")
    amenity = tags.get("amenity", "")
    residential_types = {"house", "detached", "semidetached_house", "bungalow", "residential", "terrace", "cabin", "static_caravan"}
    garage_types = {"garage", "garages", "shed", "carport"}
    institutional_types = {"church", "cathedral", "courthouse", "school", "public", "civic", "hospital", "hotel"}

    if levels:
        per_level = 3.0 if btype in residential_types else 3.8
        return round(levels * per_level, 1)

    if btype in garage_types:
        return 3.0
    if btype in residential_types:
        return 5.5  # ~1.5-2 storeys
    if btype in institutional_types or amenity in ("courthouse", "place_of_worship", "school") or footprint_area_m2 > 600:
        return round(float(np.clip(6.0 + footprint_area_m2 / 200.0, 8.0, 24.0)), 1)
    if btype in ("commercial", "retail", "office", "yes"):
        return 10.0  # downtown commercial, ~2.5 storeys
    return 7.0


def build_buildings(raw_arr, raw_tf):
    elements = load_osm("buildings")
    landmarks = landmark_lonlat_utm()
    out = []
    for el in elements:
        tags = el.get("tags", {})
        if el["type"] == "way":
            poly = way_polygon_utm(el)
        elif el["type"] == "relation":
            poly = relation_multipolygon_utm(el)
        else:
            continue
        if poly is None or poly.is_empty or poly.area < 4:
            continue
        polys = list(poly.geoms) if hasattr(poly, "geoms") else [poly]
        for p in polys:
            ext = list(p.exterior.coords)
            coords_xz = [godot_xz(e, n) for e, n in ext]
            coords_xz = ensure_ccw(coords_xz)
            ys = [sample_y(raw_arr, raw_tf, e, n) for e, n in ext]
            centroid = p.centroid
            landmark_id = building_name_hint(tags)
            if landmark_id is None:
                best_d = 60.0
                for key in BUILDING_LANDMARK_KEYS:
                    le, ln = landmarks[key]
                    d = ((centroid.x - le) ** 2 + (centroid.y - ln) ** 2) ** 0.5
                    if d < best_d:
                        best_d = d
                        landmark_id = key
            rec = {
                "id": el["id"],
                "footprint": [{"x": x, "z": z} for x, z in coords_xz],
                "ground_y_min": round(min(ys), 2),
                "ground_y_max": round(max(ys), 2),
                "height_m": estimate_height_m(tags, p.area),
                "tags": {
                    "name": tags.get("name"),
                    "building": tags.get("building"),
                    "amenity": tags.get("amenity"),
                    "levels": tags.get("building:levels") or tags.get("levels"),
                    "height": tags.get("height"),
                    "roof_shape": tags.get("roof:shape"),
                    "roof_material": tags.get("roof:material"),
                    "building_material": tags.get("building:material"),
                },
            }
            if landmark_id:
                rec["landmark_id"] = landmark_id
            out.append(rec)
    with open(os.path.join(GAME_DATA, "buildings.json"), "w") as f:
        json.dump({"buildings": out}, f)
    print(f"  buildings.json: {len(out)} footprints")


def load_reach_polygons():
    """Reach polygons as shapely Polygons + pool level, for bridge-clearance lookups."""
    from shapely.geometry import Polygon
    path = os.path.join(GAME_DATA, "_water_reaches_utm.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        reaches = json.load(f)["reaches"]
    out = []
    for r in reaches:
        try:
            poly = Polygon(r["polygon_utm"])
        except Exception:
            continue
        out.append((poly, r["pool_level_m"]))
    return out


BRIDGE_CLEARANCE_M = {
    # highway class -> design clearance above the adjacent pool level, for
    # bridges that actually cross a water reach. Galena Ave (US-52/IL-26) is
    # the major crossing and targets ~6-10m per the brief; lesser roads/foot
    # bridges over minor water get less.
    "motorway": 7.5, "trunk": 7.5, "primary": 7.5, "secondary": 6.5,
    "tertiary": 5.5, "unclassified": 5.0, "residential": 5.0,
    "footway": 6.5, "cycleway": 6.5, "pedestrian": 6.0, "steps": 5.0,
}
DEFAULT_BRIDGE_CLEARANCE_M = 5.0
WATER_CROSSING_SEARCH_M = 250.0
BRIDGE_APPROACH_INSET_M = 12.0  # how far to step in from a bridge endpoint
                                  # before sampling terrain, to dodge riverbank
                                  # DEM noise right at the waterline


def bridge_deck_endpoints(line, tags, base_arr, base_tf, reach_polys, is_rail=False):
    """Return (y0, y1) local-Y deck elevations for a bridge's two ends.

    If the bridge crosses within WATER_CROSSING_SEARCH_M of a river/pond
    reach, the deck is set to that reach's flat pool level plus a design
    clearance (sampling the DEM right at a bridge's OSM endpoint is
    unreliable -- those nodes often sit right at the mapped waterline, which
    in a bare-earth LIDAR DEM reads as ~water level, not the true abutment/
    embankment height). Otherwise (e.g. a rail viaduct over a dry ravine or
    street), fall back to sampling terrain inset a bit from each endpoint.
    """
    mid = line.interpolate(0.5, normalized=True)
    nearest_pool = None
    nearest_d = WATER_CROSSING_SEARCH_M
    for poly, pool in reach_polys:
        d = poly.distance(mid)
        if d < nearest_d:
            nearest_d = d
            nearest_pool = pool
    if nearest_pool is not None:
        clearance = DEFAULT_BRIDGE_CLEARANCE_M if is_rail else BRIDGE_CLEARANCE_M.get(tags.get("highway"), DEFAULT_BRIDGE_CLEARANCE_M)
        y = (nearest_pool - WORLD_ORIGIN["base_elevation_m"]) + clearance
        return y, y

    length = line.length or 1.0
    inset = min(BRIDGE_APPROACH_INSET_M, length * 0.4)
    p0 = line.interpolate(inset)
    p1 = line.interpolate(length - inset)
    y0 = sample_y(base_arr, base_tf, p0.x, p0.y)
    y1 = sample_y(base_arr, base_tf, p1.x, p1.y)
    return y0, y1


def build_roads_rails(raw_arr, raw_tf, road_arr, road_tf):
    elements = load_osm("roads_rails")
    landmarks = landmark_lonlat_utm()
    bridge_landmark_e, bridge_landmark_n = landmarks["galena_bridge"]
    reach_polys = load_reach_polygons()

    road_ways = []
    rail_ways = []
    bridge_ways = []
    node_way_map = {}  # node_id -> set(way_id)
    node_pos = {}  # node_id -> (e,n)

    for el in elements:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        line = way_line_utm(el)
        if line is None:
            continue
        node_ids = el.get("nodes", [])
        geom = el.get("geometry", [])
        for nid, pt in zip(node_ids, geom):
            e, n = _T_LONLAT_TO_UTM.transform(pt["lon"], pt["lat"])
            node_pos[nid] = (e, n)
            node_way_map.setdefault(nid, set()).add(el["id"])

        bridge = is_bridge(tags)

        if "highway" in tags:
            coords = list(line.coords)
            if bridge:
                y0, y1 = bridge_deck_endpoints(line, tags, road_arr, road_tf, reach_polys)
                total_len = line.length or 1.0
                acc = 0.0
                verts = []
                for i, (e, n) in enumerate(coords):
                    if i > 0:
                        acc += ((e - coords[i - 1][0]) ** 2 + (n - coords[i - 1][1]) ** 2) ** 0.5
                    t = acc / total_len
                    y = y0 + (y1 - y0) * t
                    x, z = godot_xz(e, n)
                    verts.append({"x": x, "y": round(float(y), 2), "z": z, "node_id": node_ids[i] if i < len(node_ids) else None})
            else:
                verts = []
                for i, (e, n) in enumerate(coords):
                    y = sample_y(road_arr, road_tf, e, n)
                    x, z = godot_xz(e, n)
                    verts.append({"x": x, "y": round(float(y), 2), "z": z, "node_id": node_ids[i] if i < len(node_ids) else None})

            rec = {
                "id": el["id"],
                "vertices": verts,
                "tags": {
                    "highway": tags.get("highway"),
                    "name": tags.get("name"),
                    "lanes": road_lanes(tags),
                    "width_m": round(road_width_m(tags), 2),
                    "oneway": tags.get("oneway") == "yes",
                    "bridge": bridge,
                    "layer": road_layer(tags),
                    "surface": tags.get("surface"),
                    "sidewalk": tags.get("sidewalk"),
                },
            }
            mid = line.interpolate(0.5, normalized=True)
            if bridge and ((mid.x - bridge_landmark_e) ** 2 + (mid.y - bridge_landmark_n) ** 2) ** 0.5 < 150:
                rec["landmark_id"] = "galena_bridge"
            road_ways.append(rec)
            if bridge:
                bridge_ways.append(rec["id"])

        elif "railway" in tags:
            coords = list(line.coords)
            verts = []
            if bridge:
                y0, y1 = bridge_deck_endpoints(line, tags, raw_arr, raw_tf, reach_polys, is_rail=True)
                total_len = line.length or 1.0
                acc = 0.0
                for i, (e, n) in enumerate(coords):
                    if i > 0:
                        acc += ((e - coords[i - 1][0]) ** 2 + (n - coords[i - 1][1]) ** 2) ** 0.5
                    t = acc / total_len
                    y = y0 + (y1 - y0) * t
                    x, z = godot_xz(e, n)
                    verts.append({"x": x, "y": round(float(y), 2), "z": z})
            else:
                for e, n in coords:
                    y = sample_y(raw_arr, raw_tf, e, n)
                    x, z = godot_xz(e, n)
                    verts.append({"x": x, "y": round(float(y), 2), "z": z})
            rail_ways.append({
                "id": el["id"],
                "vertices": verts,
                "tags": {
                    "railway": tags.get("railway"),
                    "name": tags.get("name"),
                    "bridge": bridge,
                    "layer": road_layer(tags),
                    "usage": tags.get("usage"),
                },
            })

    # junction nodes = referenced by >=2 highway ways
    junction_nodes = []
    highway_node_map = {}
    for el in elements:
        if el["type"] != "way" or "highway" not in el.get("tags", {}):
            continue
        for nid in el.get("nodes", []):
            highway_node_map.setdefault(nid, set()).add(el["id"])
    for nid, ways in highway_node_map.items():
        if len(ways) >= 2 and nid in node_pos:
            e, n = node_pos[nid]
            x, z = godot_xz(e, n)
            y = sample_y(road_arr, road_tf, e, n)
            junction_nodes.append({"node_id": nid, "x": x, "y": round(float(y), 2), "z": z, "way_ids": sorted(ways)})

    with open(os.path.join(GAME_DATA, "roads.json"), "w") as f:
        json.dump({"ways": road_ways, "junction_nodes": junction_nodes}, f)
    with open(os.path.join(GAME_DATA, "rails.json"), "w") as f:
        json.dump({"ways": rail_ways}, f)
    with open(os.path.join(GAME_DATA, "bridges.json"), "w") as f:
        bridges_out = [w for w in road_ways if w["tags"]["bridge"]]
        for w in rail_ways:
            if w["tags"]["bridge"]:
                bridges_out.append({"id": w["id"], "vertices": w["vertices"], "tags": {**w["tags"], "kind": "railway"}})
        json.dump({"bridges": bridges_out}, f)
    print(f"  roads.json: {len(road_ways)} ways, {len(junction_nodes)} junction nodes")
    print(f"  rails.json: {len(rail_ways)} ways")
    print(f"  bridges.json: {len(bridges_out)} bridge segments")


def build_water(raw_arr, raw_tf):
    with open(os.path.join(GAME_DATA, "_water_reaches_utm.json")) as f:
        reaches = json.load(f)["reaches"]

    reach_polys = []
    for r in reaches:
        coords_xz = [godot_xz(e, n) for e, n in r["polygon_utm"]]
        coords_xz = ensure_ccw(coords_xz)
        reach_polys.append({
            "id": r["id"],
            "kind": "river" if r["id"].startswith("river_") else "pond",
            "polygon": [{"x": x, "z": z} for x, z in coords_xz],
            "surface_y": round(r["pool_level_m"] - WORLD_ORIGIN["base_elevation_m"], 2),
        })

    # linear waterway features (streams, ditches) not part of the flattened polygons
    wl = load_osm("water_landuse")
    landmarks = landmark_lonlat_utm()
    dam_e, dam_n = landmarks["dixon_dam"]
    streams = []
    dams = []
    for el in wl:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        wtag = tags.get("waterway")
        if wtag in ("stream", "ditch", "drain", "canal"):
            line = way_line_utm(el)
            if line is None:
                continue
            verts = []
            for e, n in line.coords:
                y = sample_y(raw_arr, raw_tf, e, n)
                x, z = godot_xz(e, n)
                verts.append({"x": x, "y": round(float(y), 2), "z": z})
            streams.append({"id": el["id"], "kind": wtag, "name": tags.get("name"), "vertices": verts})
        elif wtag == "dam":
            line = way_line_utm(el)
            if line is None:
                continue
            verts = []
            for e, n in line.coords:
                y = sample_y(raw_arr, raw_tf, e, n)
                x, z = godot_xz(e, n)
                verts.append({"x": x, "y": round(float(y), 2), "z": z})
            rec = {"id": el["id"], "name": tags.get("name"), "vertices": verts}
            mid = line.interpolate(0.5, normalized=True)
            if ((mid.x - dam_e) ** 2 + (mid.y - dam_n) ** 2) ** 0.5 < 200:
                rec["landmark_id"] = "dixon_dam"
            dams.append(rec)

    with open(os.path.join(GAME_DATA, "water.json"), "w") as f:
        json.dump({"reaches": reach_polys, "streams": streams, "dams": dams}, f)
    print(f"  water.json: {len(reach_polys)} reach polygons, {len(streams)} streams, {len(dams)} dam features")


LANDUSE_KEEP_KEYS = ("landuse", "leisure", "natural")


def build_landuse(raw_arr, raw_tf):
    elements = load_osm("water_landuse")
    out = []
    for el in elements:
        tags = el.get("tags", {})
        if not any(k in tags for k in LANDUSE_KEEP_KEYS):
            continue
        if tags.get("natural") == "water" or tags.get("waterway"):
            continue  # handled in water.json
        if el["type"] == "way":
            poly = way_polygon_utm(el)
        elif el["type"] == "relation":
            poly = relation_multipolygon_utm(el)
        else:
            continue
        if poly is None or poly.is_empty or poly.area < 25:
            continue
        polys = list(poly.geoms) if hasattr(poly, "geoms") else [poly]
        for p in polys:
            ext = list(p.exterior.coords)
            coords_xz = ensure_ccw([godot_xz(e, n) for e, n in ext])
            out.append({
                "id": el["id"],
                "polygon": [{"x": x, "z": z} for x, z in coords_xz],
                "tags": {
                    "landuse": tags.get("landuse"),
                    "leisure": tags.get("leisure"),
                    "natural": tags.get("natural"),
                    "name": tags.get("name"),
                },
            })
    with open(os.path.join(GAME_DATA, "landuse.json"), "w") as f:
        json.dump({"areas": out}, f)
    print(f"  landuse.json: {len(out)} polygons")


def build_points(raw_arr, raw_tf):
    landmarks = landmark_lonlat_utm()
    point_landmark_keys = ["lincoln_statue", "dixon_arch"]

    def nearest_landmark(e, n, max_d=40.0):
        best_k, best_d = None, max_d
        for k in point_landmark_keys:
            le, ln = landmarks[k]
            d = ((e - le) ** 2 + (n - ln) ** 2) ** 0.5
            if d < best_d:
                best_d, best_k = d, k
        return best_k

    pts = load_osm("points")
    pois, trees, lamps, barrier_lines = [], [], [], []
    for el in pts:
        tags = el.get("tags", {})

        # Barrier WAYS (fences, walls, retaining walls) keep their full line
        # geometry -- collapsing a wall to a single centroid point loses the
        # shape entirely, which matters for riverbank retaining walls etc.
        if el["type"] == "way" and "barrier" in tags:
            line = way_line_utm(el) if el.get("geometry") else None
            if line is None:
                continue
            verts = []
            for e, n in line.coords:
                y = sample_y(raw_arr, raw_tf, e, n)
                x, z = godot_xz(e, n)
                verts.append({"x": x, "y": round(float(y), 2), "z": z})
            barrier_lines.append({"id": el["id"], "barrier": tags.get("barrier"), "name": tags.get("name"), "vertices": verts})
            continue

        if el["type"] == "node":
            e, n = _T_LONLAT_TO_UTM.transform(el["lon"], el["lat"])
        elif el["type"] == "way":
            line = way_line_utm(el) if el.get("geometry") else None
            if line is None:
                continue
            c = line.centroid
            e, n = c.x, c.y
        else:
            continue
        y = sample_y(raw_arr, raw_tf, e, n)
        x, z = godot_xz(e, n)

        if tags.get("natural") == "tree":
            trees.append({"id": el["id"], "x": x, "y": round(float(y), 2), "z": z, "species": tags.get("species") or tags.get("genus")})
        elif tags.get("highway") == "street_lamp":
            lamps.append({"id": el["id"], "x": x, "y": round(float(y), 2), "z": z})
        elif "barrier" in tags:  # barrier nodes (point obstacles: gates, bollards, ...)
            pois.append({"id": el["id"], "x": x, "y": round(float(y), 2), "z": z,
                         "tags": {"barrier": tags.get("barrier")}})
        else:
            rec = {"id": el["id"], "x": x, "y": round(float(y), 2), "z": z,
                   "tags": {"amenity": tags.get("amenity"), "name": tags.get("name"),
                            "historic": tags.get("historic"), "tourism": tags.get("tourism"),
                            "man_made": tags.get("man_made")}}
            lid = nearest_landmark(e, n)
            if lid:
                rec["landmark_id"] = lid
            pois.append(rec)

    with open(os.path.join(GAME_DATA, "pois.json"), "w") as f:
        json.dump({"points": pois, "barrier_lines": barrier_lines}, f)
    with open(os.path.join(GAME_DATA, "trees.json"), "w") as f:
        json.dump({"points": trees}, f)
    with open(os.path.join(GAME_DATA, "lamps.json"), "w") as f:
        json.dump({"points": lamps}, f)
    print(f"  pois.json: {len(pois)} points, {len(barrier_lines)} barrier lines  trees.json: {len(trees)}  lamps.json: {len(lamps)}")


if __name__ == "__main__":
    main()
