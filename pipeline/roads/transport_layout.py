"""Authoritative, non-overlapping transportation polygons in local (x, z) metres."""
import json
import hashlib
import math
from pathlib import Path

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
             for name in ("roads.json", "buildings.json", "water.json", "aerial_paved.json")]
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


def build_layout(plans, nodes, aerial, obstacles, overrides, path_ways=()):
    obstacles = set_precision(checked(obstacles, "obstacles"), OVERLAY_GRID_M)
    aerial = set_precision(checked(aerial, "aerial candidates"), OVERLAY_GRID_M)
    corridors = []
    curbed_regions = []
    downtown_regions = []
    for plan in plans:
        line = LineString(plan.full_centerline)
        corridors.append(line.buffer(plan.half_w, cap_style="flat", join_style="round"))
        if plan.has_curb:
            region = line.buffer(plan.half_w + 8.0)
            curbed_regions.append(region)
            if plan.downtown:
                downtown_regions.append(region)
    raw = checked(union(corridors), "road corridors")
    settings = {record["node_id"]: record for record in overrides.get("junctions", [])}
    missing = set(settings) - set(nodes)
    if missing:
        raise ValueError(f"junction overrides reference missing nodes: {sorted(missing)}")

    returns = []
    applied = []
    residential_regions = []
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
            if record.get("profile") == "downtown":
                downtown_regions.append(zone)
            elif record.get("profile") == "residential":
                residential_regions.append(zone)
    asphalt = checked(union(polygon_parts(raw.union(union(returns)))).simplify(
        BOUNDARY_SIMPLIFY_M, preserve_topology=True), "connected asphalt")
    curbed_region = union(curbed_regions)
    downtown_region = union(downtown_regions).difference(union(residential_regions))
    curb_outer = asphalt.buffer(CURB_WIDTH, quad_segs=16)
    curb = curb_outer.difference(asphalt).intersection(curbed_region)
    gutter = asphalt.difference(asphalt.buffer(-GUTTER_WIDTH, quad_segs=16)).intersection(curbed_region)
    residential_inner = asphalt.buffer(CURB_WIDTH + PARKWAY_GAP, quad_segs=16)
    residential_outer = asphalt.buffer(CURB_WIDTH + PARKWAY_GAP + SIDEWALK_W_RESIDENTIAL, quad_segs=16)
    downtown_outer = asphalt.buffer(CURB_WIDTH + SIDEWALK_W_DOWNTOWN, quad_segs=16)
    parkway = residential_inner.difference(curb_outer).intersection(
        curbed_region).difference(downtown_region)
    sidewalk = residential_outer.difference(residential_inner).intersection(
        curbed_region).difference(downtown_region).union(
            downtown_outer.difference(curb_outer).intersection(downtown_region).intersection(curbed_region))
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
    report.update({"applied_junction_overrides": applied, "rejected_lot_fragments": rejected})
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


def surface_triangles(geometry):
    """Constrained triangulation preserves holes; local cells bound terrain spans."""
    if geometry.is_empty:
        return
    min_x, min_z, max_x, max_z = geometry.bounds
    for x in range(math.floor(min_x / 64), math.floor(max_x / 64) + 1):
        for z in range(math.floor(min_z / 64), math.floor(max_z / 64) + 1):
            chunk = geometry.intersection(box(x * 64, z * 64, (x + 1) * 64, (z + 1) * 64))
            if chunk.is_empty or chunk.area < AREA_TOLERANCE:
                continue
            for cx in range(8):
                for cz in range(8):
                    cell = box(x * 64 + cx * MESH_CELL_M, z * 64 + cz * MESH_CELL_M,
                               x * 64 + (cx + 1) * MESH_CELL_M, z * 64 + (cz + 1) * MESH_CELL_M)
                    clipped = chunk.intersection(cell)
                    for polygon in polygon_parts(clipped):
                        if polygon.area < AREA_TOLERANCE:
                            continue
                        triangles = constrained_delaunay_triangles(polygon)
                        if abs(triangles.area - polygon.area) > AREA_TOLERANCE:
                            raise ValueError("transport layout: incomplete surface triangulation")
                        for triangle in triangles.geoms:
                            yield list(triangle.exterior.coords)[:3]


def emit_layout(surfaces, hm, meshes):
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
                segments.extend(LineString([a, b]) for a, b in zip(ring.coords, list(ring.coords)[1:]))
        return STRtree(segments)

    raised_tree = boundary_tree(raised)
    road_tree = boundary_tree(surfaces["asphalt"])

    def graded_bias(point, tree, bias):
        if len(tree) == 0:
            return 0.0
        distance = point.distance(tree.geometries[tree.nearest(point)])
        return bias * max(0.0, 1 - distance / 1.5)

    for name, geometry in surfaces.items():
        mesh = meshes.setdefault(material[name], MeshBuild())
        print(f"  meshing {name}: {geometry.area:.1f} m2")
        expected_area = (paved if name == "asphalt" else geometry).area
        emitted_area = 0.0
        for points in surface_triangles(paved if name == "asphalt" else geometry):
            indices = []
            for x, z in points:
                bias = TOP_BIAS if name in ("curb", "sidewalk", "parkway") else ROAD_BIAS
                if name == "gutter":
                    bias += 0.005
                elif name == "verge":
                    point = Point(x, z)
                    bias = max(graded_bias(point, raised_tree, TOP_BIAS),
                               graded_bias(point, road_tree, ROAD_BIAS))
                elif name.startswith("path_"):
                    bias = 0.03
                indices.append(mesh.add_vertex(x, hm.sample(x, z) + bias, z, hm.normal(x, z)))
            a, b, c = points
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            emitted_area += abs(cross) / 2
            mesh.add_tri(*(indices if cross > 0 else indices[::-1]))
        if abs(emitted_area - expected_area) > max(AREA_TOLERANCE, expected_area * 1e-6):
            raise ValueError(f"transport layout: incomplete {name} mesh "
                             f"({emitted_area:.6f} vs {expected_area:.6f} m2)")

    # Only the exposed asphalt/curb boundary is a vertical curb face.
    mesh = meshes.setdefault("curb_concrete", MeshBuild())
    boundary = surfaces["asphalt"].boundary.intersection(surfaces["curb"].boundary)
    lines = [boundary] if boundary.geom_type == "LineString" else getattr(boundary, "geoms", [])
    for line in lines:
        if line.geom_type != "LineString":
            continue
        points = list(line.segmentize(2.5).coords)
        for a, b in zip(points, points[1:]):
            length = math.dist(a, b)
            if length < 1e-8:
                continue
            normal = [(b[1] - a[1]) / length, 0.0, (a[0] - b[0]) / length]
            indices = [mesh.add_vertex(x, hm.sample(x, z) + bias, z, normal)
                       for (x, z), bias in ((a, ROAD_BIAS + 0.005), (b, ROAD_BIAS + 0.005),
                                           (b, TOP_BIAS), (a, TOP_BIAS))]
            mesh.add_quad(*indices)
            mesh.add_quad(*indices[::-1])
