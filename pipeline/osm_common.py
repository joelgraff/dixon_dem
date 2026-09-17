"""Helpers for turning raw Overpass JSON (data/raw/osm_*.json) into shapely
geometry in UTM 16N (EPSG:26916) meters, plus shared road-tag heuristics.
"""
import json
import os

from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import linemerge, polygonize, unary_union

from common import DATA_RAW

_T = Transformer.from_crs("EPSG:4326", "EPSG:26916", always_xy=True)


def load_osm(name):
    path = os.path.join(DATA_RAW, f"osm_{name}.json")
    with open(path) as f:
        return json.load(f)["elements"]


def geom_to_utm_coords(geometry):
    """List of {lat,lon} dicts (Overpass 'geometry') -> list of (e,n) tuples."""
    coords = []
    for pt in geometry:
        e, n = _T.transform(pt["lon"], pt["lat"])
        coords.append((e, n))
    return coords


def way_line_utm(el):
    geom = el.get("geometry")
    if not geom or len(geom) < 2:
        return None
    return LineString(geom_to_utm_coords(geom))


def way_polygon_utm(el):
    geom = el.get("geometry")
    if not geom or len(geom) < 4:
        return None
    coords = geom_to_utm_coords(geom)
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    try:
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if not poly.is_empty else None
    except Exception:
        return None


def relation_multipolygon_utm(el):
    """Assemble outer/inner member ways (each with its own 'geometry') into a
    (Multi)Polygon. Handles multi-segment rings via linemerge/polygonize."""
    outer_lines = []
    inner_lines = []
    for m in el.get("members", []):
        geom = m.get("geometry")
        if not geom or len(geom) < 2:
            continue
        coords = geom_to_utm_coords(geom)
        if len(coords) < 2:
            continue
        line = LineString(coords)
        if m.get("role") == "inner":
            inner_lines.append(line)
        else:
            outer_lines.append(line)

    def rings_to_polys(lines):
        if not lines:
            return []
        merged = linemerge(lines)
        polys = list(polygonize(merged if hasattr(merged, "geoms") else [merged]))
        return polys

    outer_polys = rings_to_polys(outer_lines)
    inner_polys = rings_to_polys(inner_lines)
    if not outer_polys:
        return None
    outer_u = unary_union(outer_polys)
    if inner_polys:
        inner_u = unary_union(inner_polys)
        outer_u = outer_u.difference(inner_u)
    if outer_u.is_empty:
        return None
    return outer_u


def clip_lines_by_bounds(elements, min_e, min_n, max_e, max_n, pad=0.0):
    """Filter Overpass way elements to those whose bbox overlaps the given
    UTM bounds (fast prefilter using the element's own lon/lat 'bounds')."""
    from pyproj import Transformer as _Tr
    out = []
    for el in elements:
        b = el.get("bounds")
        if not b:
            out.append(el)
            continue
        e1, n1 = _T.transform(b["minlon"], b["minlat"])
        e2, n2 = _T.transform(b["maxlon"], b["maxlat"])
        be_min, be_max = min(e1, e2), max(e1, e2)
        bn_min, bn_max = min(n1, n2), max(n1, n2)
        if be_max < min_e - pad or be_min > max_e + pad:
            continue
        if bn_max < min_n - pad or bn_min > max_n + pad:
            continue
        out.append(el)
    return out


# --- Road tag heuristics ---------------------------------------------------
# (default lanes, default width_m) by highway class -- Dixon is a small
# Midwestern city: 3.3-3.6m lanes, narrow residential streets, standard
# arterial widths for a US-52/IL-26 corridor.
HIGHWAY_DEFAULTS = {
    "motorway": (2, 2 * 3.6 + 2.0),
    "trunk": (2, 2 * 3.5 + 1.5),
    "primary": (2, 2 * 3.5 + 1.5),
    "secondary": (2, 2 * 3.4),
    "tertiary": (2, 2 * 3.3),
    "unclassified": (1, 5.5),
    "residential": (2, 6.5),
    "living_street": (1, 5.0),
    "service": (1, 4.0),
    "track": (1, 3.0),
    "footway": (1, 1.8),
    "path": (1, 1.5),
    "pedestrian": (1, 4.0),
    "steps": (1, 1.8),
    "cycleway": (1, 2.0),
    "alley": (1, 3.5),
}
DEFAULT_HIGHWAY = (2, 6.0)


def road_width_m(tags):
    hwy = tags.get("highway", "")
    lanes_default, width_default = HIGHWAY_DEFAULTS.get(hwy, DEFAULT_HIGHWAY)
    if "width" in tags:
        try:
            return float(tags["width"].split()[0])
        except (ValueError, IndexError):
            pass
    lanes = tags.get("lanes")
    if lanes:
        try:
            n = float(lanes)
            per_lane = 3.6 if hwy in ("motorway", "trunk", "primary") else 3.3
            return n * per_lane + (2.0 if hwy in ("motorway", "trunk", "primary") else 0.0)
        except ValueError:
            pass
    return width_default


def road_lanes(tags):
    hwy = tags.get("highway", "")
    lanes_default, _ = HIGHWAY_DEFAULTS.get(hwy, DEFAULT_HIGHWAY)
    if "lanes" in tags:
        try:
            return int(float(tags["lanes"]))
        except ValueError:
            pass
    return lanes_default


def is_bridge(tags):
    return tags.get("bridge") not in (None, "no")


def road_layer(tags):
    try:
        return int(tags.get("layer", "0"))
    except ValueError:
        return 0
