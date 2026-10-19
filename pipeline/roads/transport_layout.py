"""Authoritative, non-overlapping transportation polygons in local (x, z) metres."""
import json
import hashlib
import math
from pathlib import Path

import numpy as np
import shapely

from shapely import constrained_delaunay_triangles, difference, intersection, set_precision, union_all
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import explain_validity

from roads.common_roads import MeshBuild

ROOT = Path(__file__).resolve().parents[2]
LAYOUT_PATH = ROOT / "game/roads/_build/transport_layout.json"
OVERRIDES_PATH = ROOT / "pipeline/roads/layout_overrides.json"
CURB_WIDTH = 0.12
CURB_REVEAL = 0.1524
CURB_REVEAL_OLDER = 0.102   # design_standards.json cross_section.curb_reveal_older, a template's 'older' curb
GUTTER_WIDTH = 0.3048
ROAD_BIAS = 0.085
TOP_BIAS = ROAD_BIAS + CURB_REVEAL
PARKWAY_GAP = 2.0
SIDEWALK_W_RESIDENTIAL = 1.7
SIDEWALK_W_DOWNTOWN = 3.6
MESH_CELL_M = 8.0
MIN_LOT_AREA_M2 = 150.0
MIN_LOT_WIDTH_M = 3.0
MAX_SMALL_HOLE_M2 = 36.0
MAX_LOT_ENVELOPE_RATIO = 1.6
AREA_TOLERANCE = 1e-5
OVERLAY_GRID_M = 1e-6
BOUNDARY_SIMPLIFY_M = 0.025


def polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        if not geometry.is_empty:
            yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from polygon_parts(part)


def checked(geometry, label):
    if not geometry.is_valid:
        raise ValueError(f"transport layout: invalid {label}: {explain_validity(geometry)}")
    if not geometry.is_empty and geometry.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"transport layout: non-polygonal {label}: {geometry.geom_type}")
    return geometry


def union(polygons):
    parts = []
    for geometry in polygons:
        if not geometry.is_valid:
            raise ValueError(f"transport layout: invalid union input: {explain_validity(geometry)}")
        parts.extend(set_precision(part, OVERLAY_GRID_M) for part in polygon_parts(geometry))
    if not parts:
        return Polygon()
    result = unary_union(parts)
    if result.geom_type == "GeometryCollection":
        result = set_precision(MultiPolygon(list(polygon_parts(result))), OVERLAY_GRID_M)
    return checked(result, "polygon union")


def load_layout(path=LAYOUT_PATH):
    with open(path) as stream:
        data = json.load(stream)
    if data.get("version") != 1:
        raise ValueError(f"unsupported transportation layout version in {path}")
    if data.get("inputs") != input_fingerprints():
        raise ValueError("stale transportation layout; run pipeline/roads/rebuild_transportation.sh")
    return {name: checked(shape(geometry), name)
            for name, geometry in data["surfaces"].items()}


def input_fingerprints():
    paths = [ROOT / "game/data" / name
             for name in ("roads.json", "buildings.json", "buildings_curated.json", "buildings_ms.json",
                          "water.json", "aerial_paved.json", "alignments.json", "templates.json")]
    paths.append(OVERRIDES_PATH)
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def paint_geometry(image, geometry, color, world_to_px):
    """Paint polygon interiors without overwriting whatever lies inside their holes."""
    from PIL import Image, ImageDraw

    for polygon in polygon_parts(geometry):
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.polygon([world_to_px(x, z) for x, z in polygon.exterior.coords], fill=255)
        for ring in polygon.interiors:
            draw.polygon([world_to_px(x, z) for x, z in ring.coords], fill=0)
        image.paste(color, (0, 0), mask)


def override_polygon(record, label):
    if not isinstance(record, dict) or not record.get("id"):
        raise ValueError(f"transport layout: {label} requires an id")
    polygon = Polygon(record["polygon"], record.get("holes", []))
    if polygon.is_empty or polygon.area < AREA_TOLERANCE:
        raise ValueError(f"transport layout: empty {label} {record['id']}")
    return checked(polygon, f"{label} {record['id']}")


def read_overrides(path=OVERRIDES_PATH):
    with open(path) as stream:
        data = json.load(stream)
    if data.get("version") != 1:
        raise ValueError(f"unsupported layout override version in {path}")
    unknown = set(data) - {"version", "junctions", "lots", "exclude_paving"}
    if unknown:
        raise ValueError(f"unknown transportation override keys: {sorted(unknown)}")
    seen = set()
    for record in data.get("junctions", []):
        node_id = record["node_id"]
        if node_id in seen:
            raise ValueError(f"duplicate junction override {node_id}")
        seen.add(node_id)
        radius = record["return_radius_m"]
        if not isinstance(radius, (int, float)) or not math.isfinite(radius) or not 2 <= radius <= 20:
            raise ValueError(f"invalid return radius at junction {node_id}")
        if record.get("profile") not in (None, "downtown", "residential"):
            raise ValueError(f"invalid roadside profile at junction {node_id}")
    for key in ("lots", "exclude_paving"):
        for record in data.get(key, []):
            override_polygon(record, key)
    return data


def clean_lots(source, exclusions, overrides):
    """Imagery is a candidate source, not a licence to emit every classified pixel."""
    accepted = []
    rejected = []
    for index, polygon in enumerate(polygon_parts(checked(source, "aerial candidates"))):
        # Opening removes thin fingers; small internal classification holes are not
        # credible grass islands. Large islands remain explicit boundaries.
        holes = []
        for ring in polygon.interiors:
            hole = Polygon(ring)
            envelope = hole.minimum_rotated_rectangle
            if hole.area > MAX_SMALL_HOLE_M2 and envelope.area <= hole.area * 1.2:
                holes.append(envelope.exterior)
        filled = Polygon(polygon.exterior, holes)
        opened = filled.buffer(-MIN_LOT_WIDTH_M / 2).buffer(MIN_LOT_WIDTH_M / 2)
        if opened.is_empty or opened.area < filled.area * 0.5:
            rejected.append({"candidate": index, "reason": "narrow or fragmented",
                             "area_m2": polygon.area, "bounds": polygon.bounds})
            continue
        envelope = opened.minimum_rotated_rectangle
        if envelope.area > filled.area * MAX_LOT_ENVELOPE_RATIO:
            rejected.append({"candidate": index, "reason": "ambiguous non-rectilinear footprint",
                             "area_m2": polygon.area, "bounds": polygon.bounds})
            continue
        regular = Polygon(envelope.exterior, holes)
        clipped = regular.difference(exclusions)
        for part in polygon_parts(clipped):
            core = part.buffer(-MIN_LOT_WIDTH_M / 2)
            if part.area < MIN_LOT_AREA_M2 or core.is_empty:
                rejected.append({"candidate": index, "reason": "small or narrow after clipping",
                                 "area_m2": part.area, "bounds": part.bounds})
            else:
                accepted.append(part)
    explicit = union([override_polygon(record, "lot")
                      for record in overrides.get("lots", [])])
    overlap = explicit.intersection(exclusions).area
    if overlap > AREA_TOLERANCE:
        raise ValueError(f"explicit parking lots overlap protected surfaces by {overlap:.3f} m2")
    blocked = union([override_polygon(record, "paving exclusion")
                     for record in overrides.get("exclude_paving", [])])
    result = union(accepted).union(explicit).difference(blocked)
    return checked(result, "parking lots"), rejected


def plan_roadside(plan):
    """(parkway, sidewalk) widths behind a curbed plan's curb: its template's, or the legacy
    downtown/residential profile for a plan built without one."""
    if getattr(plan, "parkway", None) is not None and getattr(plan, "sw_width", None) is not None:
        return (round(plan.parkway, 3), round(plan.sw_width, 3))
    return (0.0, SIDEWALK_W_DOWNTOWN) if plan.downtown else (PARKWAY_GAP, SIDEWALK_W_RESIDENTIAL)


def plan_corridor(plan):
    """The plan's carriageway: a flat-capped, round-jointed strip of its half width, which may
    change along the line (per-vertex `half_ws`, where a template width tapers)."""
    points = plan.full_centerline
    hws = getattr(plan, "half_ws", None)
    if not hws or max(hws) - min(hws) < 1e-3:
        return LineString(points).buffer(hws[0] if hws else plan.half_w, cap_style="flat", join_style="round")
    parts = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        length = math.dist(a, b)
        if length < 1e-9:
            continue
        nx, nz = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
        ha, hb = hws[i], hws[i + 1]
        parts.append(Polygon([(a[0] + nx * ha, a[1] + nz * ha), (b[0] + nx * hb, b[1] + nz * hb),
                              (b[0] - nx * hb, b[1] - nz * hb), (a[0] - nx * ha, a[1] - nz * ha)]))
        if i > 0:
            parts.append(Point(a).buffer(ha, quad_segs=16))
    return union(parts)


def older_curb_region(plans, reveal=CURB_REVEAL):
    """Where the curb is lower than the standard reveal (an 'older' curb in a template)."""
    return union([LineString(plan.full_centerline).buffer(plan.half_w + 8.0)
                  for plan in plans if plan.has_curb
                  and getattr(plan, "curb_reveal", reveal) < reveal - 1e-3])


CONFLICT_MIN_M2 = 0.5


def roadside_conflicts(surfaces, obstacles):
    """Each obstacle (building or water) a surface runs into, by surface: area and where."""
    parts = list(polygon_parts(obstacles))
    tree = STRtree(parts) if parts else None
    out = {}
    for name, geometry in surfaces.items():
        rows = []
        if tree is not None and not geometry.is_empty:
            for i in tree.query(geometry, predicate="intersects"):
                area = parts[i].intersection(geometry).area
                if area > CONFLICT_MIN_M2:
                    c = parts[i].centroid
                    rows.append({"at": [round(c.x, 1), round(c.y, 1)], "area_m2": round(area, 1)})
        rows.sort(key=lambda r: -r["area_m2"])
        out[name] = {"count": len(rows), "area_m2": round(sum(r["area_m2"] for r in rows), 1),
                     "largest": rows[:25]}
    return out


def building_conflicts(groups, buildings, min_m2=CONFLICT_MIN_M2):
    """Each building standing on a surface group, by footprint source. `buildings` is
    (polygons, [(id, source), ...]); `groups` maps a name to its geometry."""
    polygons, ids = buildings
    tree = STRtree(polygons) if polygons else None
    by_source, listed = {}, []
    for group, geometry in groups.items():
        areas = {}
        if tree is not None and not geometry.is_empty:
            for part in polygon_parts(geometry):
                for i in tree.query(part, predicate="intersects"):
                    areas[int(i)] = areas.get(int(i), 0.0) + polygons[int(i)].intersection(part).area
        for i, area in areas.items():
            if area <= min_m2:
                continue
            bid, source = ids[i]
            row = by_source.setdefault(source, {g: {"count": 0, "area_m2": 0.0} for g in groups})
            row[group]["count"] += 1
            row[group]["area_m2"] = round(row[group]["area_m2"] + area, 1)
            c = polygons[i].centroid
            listed.append({"id": bid, "source": source, "surface": group, "area_m2": round(area, 1),
                           "at": [round(c.x, 1), round(c.y, 1)]})
    listed.sort(key=lambda r: -r["area_m2"])
    return {"by_source": by_source,
            "largest": {group: [r for r in listed if r["surface"] == group][:60] for group in groups}}


def build_layout(plans, nodes, aerial, obstacles, overrides, path_ways=(), buildings=None):
    """`buildings`, optional (polygons, [(id, source)]), only adds the by-source
    building_conflicts to the report; `obstacles` already holds their geometry."""
    obstacles = set_precision(checked(obstacles, "obstacles"), OVERLAY_GRID_M)
    aerial = set_precision(checked(aerial, "aerial candidates"), OVERLAY_GRID_M)
    corridors = []
    curbed_regions = []
    roadside_regions = {}
    gutter_regions = {}
    for plan in plans:
        corridors.append(plan_corridor(plan))
        if plan.has_curb:
            line = LineString(plan.full_centerline)
            region = line.buffer(max(getattr(plan, "half_ws", None) or [plan.half_w]) + 8.0)
            curbed_regions.append(region)
            roadside_regions.setdefault(plan_roadside(plan), []).append(region)
            gutter = round(getattr(plan, "gutter_w", GUTTER_WIDTH), 4)
            if gutter > 0:
                gutter_regions.setdefault(gutter, []).append(region)
    raw = checked(union(corridors), "road corridors")
    settings = {record["node_id"]: record for record in overrides.get("junctions", [])}
    missing = set(settings) - set(nodes)
    if missing:
        raise ValueError(f"junction overrides reference missing nodes: {sorted(missing)}")

    returns = []
    applied = []
    forced = {}
    profiles = {"downtown": (0.0, SIDEWALK_W_DOWNTOWN), "residential": (PARKWAY_GAP, SIDEWALK_W_RESIDENTIAL)}
    for node in nodes.values():
        if len(node.legs) < 3:
            continue
        record = settings.get(node.id, {})
        radius = record.get("return_radius_m", 4.0)
        max_width = max((leg["way"]["tags"].get("width_m") or 6.0) / 2
                        for leg in node.legs)
        zone = Point(node.x, node.z).buffer(max_width + radius * 3 + 8)
        # Solve the intersection on the connected carriageway, not on individual
        # trimmed legs. Nearby mouths can share a layout even on 10 m segments.
        local = raw.intersection(zone.buffer(radius * 2))
        rounded = local.buffer(radius, quad_segs=16).buffer(-radius, quad_segs=16)
        returns.extend(polygon_parts(rounded.intersection(zone)))
        if record:
            applied.append(node.id)
            if record.get("profile") in profiles:
                forced.setdefault(profiles[record["profile"]], []).append(zone)
    asphalt = checked(union(polygon_parts(raw.union(union(returns)))).simplify(
        BOUNDARY_SIMPLIFY_M, preserve_topology=True), "connected asphalt")
    curbed_region = union(curbed_regions)
    curb_outer = asphalt.buffer(CURB_WIDTH, quad_segs=16)
    curb = curb_outer.difference(asphalt).intersection(curbed_region)
    # the gutter flag shows only where a template says it is not overlaid; the widest wins
    gutter = union([asphalt.difference(asphalt.buffer(-width, quad_segs=16)).intersection(union(regions))
                    for width, regions in gutter_regions.items()])
    # parkway and sidewalk per roadside profile: a junction override's zone takes its profile,
    # and otherwise the narrower parkway (downtown's none) wins where profiles' regions meet
    forced_all = {key: union(zones) for key, zones in forced.items()}
    claimed = Polygon()
    parkway_parts, sidewalk_parts = [], []
    for key in sorted(set(roadside_regions) | set(forced_all), key=lambda k: (k[0], -k[1])):
        parkway_w, sidewalk_w = key
        region = union(roadside_regions.get(key, []) + ([forced_all[key]] if key in forced_all else []))
        others = union([zone for other, zone in forced_all.items() if other != key])
        region = region.difference(others).difference(claimed).intersection(curbed_region)
        if region.is_empty:
            continue
        claimed = union([claimed, region])
        reach = CURB_WIDTH + parkway_w + sidewalk_w
        local = asphalt.intersection(region.buffer(reach + 1.0))
        inner = local.buffer(CURB_WIDTH + parkway_w, quad_segs=16)
        outer = local.buffer(reach, quad_segs=16)
        if parkway_w > 0:
            parkway_parts.append(inner.difference(curb_outer).intersection(region))
        sidewalk_parts.append(outer.difference(inner if parkway_w > 0 else curb_outer).intersection(region))
    parkway = union(parkway_parts)
    sidewalk = union(sidewalk_parts)
    # a template's roadside is a typical section; where a building stands closer to the curb the
    # walk and parkway stop at its face, and the conflict is listed for review (as is pavement
    # or curb under a building, which says the width or the alignment is wrong there)
    conflicts = roadside_conflicts({"asphalt": asphalt, "curb": curb, "parkway": parkway,
                                    "sidewalk": sidewalk}, obstacles)
    by_building = building_conflicts({"carriageway": union([asphalt, curb]),
                                      "roadside": union([parkway, sidewalk])}, buildings) if buildings else None
    parkway = parkway.difference(obstacles)
    sidewalk = sidewalk.difference(obstacles)
    small_parkways = union([part for part in polygon_parts(parkway) if part.area < 16.0])
    parkway = parkway.difference(small_parkways)
    sidewalk = sidewalk.union(small_parkways)
    footprint = checked(union([asphalt, curb, parkway, sidewalk]), "roadside footprint")
    paths = {"path_concrete": [], "path_asphalt": [], "path_gravel": []}
    for way in path_ways:
        tags = way["tags"]
        highway = tags.get("highway")
        if highway not in ("footway", "cycleway", "path", "pedestrian", "steps") or tags.get("bridge"):
            continue
        points = [(v["x"], v["z"]) for v in way["vertices"]]
        if len(points) < 2:
            continue
        name = ("path_asphalt" if highway == "cycleway" else
                "path_gravel" if highway == "path" else "path_concrete")
        paths[name].append(LineString(points).buffer(max(tags.get("width_m") or 1.8, 1.0) / 2,
                                                    cap_style="flat"))
    covered = footprint
    for name, parts in paths.items():
        paths[name] = union(parts).difference(covered)
        covered = covered.union(paths[name])
    verge = footprint.buffer(1.5, quad_segs=16).difference(covered).difference(obstacles)
    lots, rejected = clean_lots(aerial, covered.union(verge).union(obstacles), overrides)
    surfaces = {
        "asphalt": asphalt, "gutter": gutter, "curb": curb,
        "parkway": parkway, "sidewalk": sidewalk, "verge": verge, "lots": lots,
        **paths,
    }
    # Boolean overlays can retain zero-area contact lines. They are boundaries,
    # not surfaces, and must not be fed to the surface mesher.
    surfaces = {name: set_precision(checked(union(polygon_parts(geometry)), name), 0)
                for name, geometry in surfaces.items()}
    occupied = surfaces["asphalt"]
    for name in ("curb", "sidewalk", "parkway", "path_concrete", "path_asphalt",
                 "path_gravel", "verge", "lots"):
        # Inputs already share the precision grid. Do not re-snap fractional
        # crossing points after partitioning: that can move an edge into its neighbor.
        parts = list(polygon_parts(difference(surfaces[name], occupied, grid_size=0)))
        surfaces[name] = checked(parts[0] if len(parts) == 1 else MultiPolygon(parts), name)
        occupied = union_all([occupied, surfaces[name]], grid_size=0)
    surfaces["gutter"] = MultiPolygon(list(polygon_parts(
        surfaces["gutter"].intersection(surfaces["asphalt"]))))
    report = validate_layout(surfaces)
    report.update({"applied_junction_overrides": applied, "rejected_lot_fragments": rejected,
                   "roadside_conflicts": conflicts})
    if by_building is not None:
        report["building_conflicts"] = by_building
    return surfaces, report


def validate_layout(surfaces):
    for name, geometry in surfaces.items():
        checked(geometry, name)
    # Gutter replaces part of the asphalt at a slightly raised elevation;
    # all other surface interiors must be disjoint.
    disjoint = [name for name in surfaces if name != "gutter"]
    overlaps = {}
    for index, a in enumerate(disjoint):
        for b in disjoint[index + 1:]:
            area = intersection(surfaces[a], surfaces[b], grid_size=0).area
            if area > AREA_TOLERANCE:
                overlaps[f"{a}/{b}"] = area
    if overlaps:
        raise ValueError(f"transport layout: overlapping surface interiors {overlaps}")
    if difference(surfaces["gutter"], surfaces["asphalt"], grid_size=0).area > AREA_TOLERANCE:
        raise ValueError("transport layout: gutter outside carriageway")
    return {"invalid_surfaces": 0, "unintended_overlap_m2": 0.0,
            "areas_m2": {name: geometry.area for name, geometry in surfaces.items()},
            "mesh_cell_m": MESH_CELL_M, "minimum_candidate_lot_width_m": MIN_LOT_WIDTH_M}


def save_layout(surfaces, report, path=LAYOUT_PATH):
    with open(path, "w") as stream:
        json.dump({"version": 1, "inputs": input_fingerprints(),
                   "surfaces": {name: mapping(geometry)
                                           for name, geometry in surfaces.items()},
                   "quality": report}, stream)


CHUNK_M = 64.0


def _chunk_pieces(geometry, x0, z0, size, out):
    """Cuts `geometry` into the CHUNK_M squares of the size-wide square at (x0, z0) by quartering
    it, so each cut is against an ever smaller piece rather than the whole network. Appends
    (piece, chunk x0, chunk z0) to `out`."""
    if geometry.is_empty:
        return
    if size <= CHUNK_M:
        out.append((geometry, x0, z0))
        return
    half = size / 2
    xs = np.array([x0, x0 + half, x0, x0 + half])
    zs = np.array([z0, z0, z0 + half, z0 + half])
    for quarter, qx, qz in zip(shapely.intersection(geometry, shapely.box(xs, zs, xs + half, zs + half)), xs, zs):
        _chunk_pieces(quarter, qx, qz, half, out)


def surface_triangles(geometry):
    """(n, 3, 2) triangles covering `geometry`: cut into CHUNK_M chunks, then on the MESH_CELL_M
    grid (cells bound terrain spans), each piece constrained-Delaunay triangulated (holes
    preserved). Vectorised: the cells of every chunk, and the triangulations, at once."""
    empty = np.empty((0, 3, 2))
    if geometry.is_empty:
        return empty
    min_x, min_z, max_x, max_z = geometry.bounds
    x0, z0 = math.floor(min_x / CHUNK_M) * CHUNK_M, math.floor(min_z / CHUNK_M) * CHUNK_M
    size = CHUNK_M
    while x0 + size <= max_x or z0 + size <= max_z:
        size *= 2
    chunks = []
    _chunk_pieces(geometry, x0, z0, size, chunks)
    pieces, cells = [], []
    per = int(CHUNK_M / MESH_CELL_M)
    offsets = np.arange(per) * MESH_CELL_M
    ox, oz = (g.ravel() for g in np.meshgrid(offsets, offsets))
    for chunk, bx, bz in chunks:
        pieces.append(np.full(per * per, chunk, dtype=object))
        cells.append(shapely.box(bx + ox, bz + oz, bx + ox + MESH_CELL_M, bz + oz + MESH_CELL_M))
    if not chunks:
        return empty
    pieces = shapely.get_parts(shapely.intersection(np.concatenate(pieces), np.concatenate(cells)))
    pieces = pieces[(shapely.get_type_id(pieces) == 3) & (shapely.area(pieces) >= AREA_TOLERANCE)]
    if not len(pieces):
        return empty
    triangulated = shapely.constrained_delaunay_triangles(pieces)
    if (np.abs(shapely.area(triangulated) - shapely.area(pieces)) > AREA_TOLERANCE).any():
        raise ValueError("transport layout: incomplete surface triangulation")
    triangles = shapely.get_parts(triangulated)
    # each triangle's ring is 4 points, the last repeating the first
    return shapely.get_coordinates(triangles).reshape(-1, 4, 2)[:, :3]


def _graded_bias(xs, zs, tree, bias):
    """bias at a boundary of the tree's segments, falling to 0 at 1.5 m from it."""
    out = np.zeros(len(xs))
    if len(tree) == 0 or not len(xs):
        return out
    (src, _), dist = tree.query_nearest(shapely.points(xs, zs), max_distance=1.5,
                                        return_distance=True, all_matches=False)
    out[src] = bias * np.maximum(0.0, 1 - dist / 1.5)
    return out


def emit_layout(surfaces, hm, meshes, older_curb=None):
    """Meshes the layout's surfaces. `older_curb` (older_curb_region) is where the curb, and so
    the parkway and walk behind it, stands CURB_REVEAL_OLDER above the gutter instead."""
    low = older_curb if older_curb is not None and not older_curb.is_empty else None
    if low is not None:
        shapely.prepare(low)

    def top_bias(xs, zs):
        top = np.full(len(xs), TOP_BIAS)
        if low is not None:
            top[shapely.contains_xy(low, xs, zs)] = ROAD_BIAS + CURB_REVEAL_OLDER
        return top

    material = {"asphalt": "asphalt_road_plowed", "lots": "asphalt_road_plowed",
                "gutter": "sidewalk_concrete", "curb": "curb_concrete",
                "sidewalk": "sidewalk_concrete", "parkway": "grass_lawn", "verge": "grass_lawn",
                "path_concrete": "sidewalk_concrete", "path_asphalt": "asphalt_road_plowed",
                "path_gravel": "gravel_ballast"}
    paved = surfaces["asphalt"].difference(surfaces["gutter"])
    raised = union([surfaces[name] for name in ("curb", "sidewalk", "parkway")])

    def boundary_tree(geometry):
        segments = []
        for polygon in polygon_parts(geometry):
            for ring in (polygon.exterior, *polygon.interiors):
                c = np.asarray(ring.coords)
                segments.append(shapely.linestrings(np.stack([c[:-1], c[1:]], axis=1)))
        return STRtree(np.concatenate(segments) if segments else [])

    raised_tree = boundary_tree(raised)
    road_tree = boundary_tree(surfaces["asphalt"])

    for name, geometry in surfaces.items():
        mesh = meshes.setdefault(material[name], MeshBuild())
        print(f"  meshing {name}: {geometry.area:.1f} m2")
        target = paved if name == "asphalt" else geometry
        tris = surface_triangles(target)
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        cross = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
        emitted_area = float(np.abs(cross).sum() / 2)
        expected_area = target.area
        if abs(emitted_area - expected_area) > max(AREA_TOLERANCE, expected_area * 1e-6):
            raise ValueError(f"transport layout: incomplete {name} mesh "
                             f"({emitted_area:.6f} vs {expected_area:.6f} m2)")
        # wound counter-clockwise in (x, z): reversed where the triangulation left it clockwise
        tris = np.where((cross > 0)[:, None, None], tris, tris[:, ::-1])
        xs, zs = tris[..., 0].ravel(), tris[..., 1].ravel()
        if name in ("curb", "sidewalk", "parkway"):
            bias = top_bias(xs, zs)
        elif name == "gutter":
            bias = np.full(len(xs), ROAD_BIAS + 0.005)
        elif name == "verge":
            bias = np.maximum(_graded_bias(xs, zs, raised_tree, 1.0) * top_bias(xs, zs),
                              _graded_bias(xs, zs, road_tree, ROAD_BIAS))
        elif name.startswith("path_"):
            bias = np.full(len(xs), 0.03)
        else:
            bias = np.full(len(xs), ROAD_BIAS)
        xyz = np.column_stack([xs, hm.sample_many(xs, zs) + bias, zs])
        mesh.add_triangles(xyz, hm.normal_many(xs, zs))

    # Only the exposed asphalt/curb boundary is a vertical curb face: a quad per 2.5 m segment,
    # both sides (gutter level a, b; top b, a), as two triangles each way round
    mesh = meshes.setdefault("curb_concrete", MeshBuild())
    boundary = surfaces["asphalt"].boundary.intersection(surfaces["curb"].boundary)
    lines = [line for line in shapely.get_parts(boundary) if line.geom_type == "LineString"]
    pairs = []
    for line in lines:
        c = np.asarray(line.segmentize(2.5).coords)
        pairs.append(np.stack([c[:-1], c[1:]], axis=1))
    if not pairs:
        return
    pairs = np.concatenate(pairs)
    length = np.linalg.norm(pairs[:, 1] - pairs[:, 0], axis=1)
    pairs, length = pairs[length >= 1e-8], length[length >= 1e-8]
    pa, pb = pairs[:, 0], pairs[:, 1]
    normal = np.column_stack([(pb[:, 1] - pa[:, 1]) / length, np.zeros(len(length)), (pa[:, 0] - pb[:, 0]) / length])
    ya, yb = hm.sample_many(pa[:, 0], pa[:, 1]), hm.sample_many(pb[:, 0], pb[:, 1])
    low_a = np.column_stack([pa[:, 0], ya + ROAD_BIAS + 0.005, pa[:, 1]])
    low_b = np.column_stack([pb[:, 0], yb + ROAD_BIAS + 0.005, pb[:, 1]])
    top_b = np.column_stack([pb[:, 0], yb + top_bias(pb[:, 0], pb[:, 1]), pb[:, 1]])
    top_a = np.column_stack([pa[:, 0], ya + top_bias(pa[:, 0], pa[:, 1]), pa[:, 1]])
    quad = np.stack([low_a, low_b, top_b, top_a], axis=1)            # (n, 4, 3)
    mesh.add_quads_both_sides(quad, normal)
