"""Template records for Dixon buildings.

A template is the small set of fields that describe a building's mass: form,
storeys, roof, which way the ridge runs, an ell wing, porch, material family,
and a dressing kit. Mesh builders do not read these yet. This module only
decides the record, so the choice can be reviewed before any geometry changes.

Height counts as evidence only when it was measured or tagged: a Microsoft
footprint height, a curated height, or an OSM height / building:levels value.
The 5.5 m and 10 m guesses written by estimate_height_m are ignored.

Coordinates are Godot local metres: x = east, z = south.
"""
import json
import math
import os

from shapely.geometry import LineString, Polygon
from shapely.strtree import STRtree

from common_buildings import dedupe_ring, polygon_area_2d, polygon_centroid_2d

FORMS = (
    "side_gable",
    "front_gable",
    "gabled_ell",
    "foursquare",
    "bungalow",
    "cross_gable",
    "ranch",
    "party_wall_commercial",
    "one_story_store",
    "civic_block",
    "church_nave",
    "industrial",
    "garage",
)
FIELDS = (
    "form", "storeys", "roof", "roof_axis", "wing", "porch", "material", "dressing",
)
STOREY_STEPS = (1, 1.5, 2, 2.5, 3, 4, 5, 6)

# A detached downtown footprint smaller than this stays a house. Larger ones
# follow the commercial prior. 350 m2 is the same cutoff classify.py already
# uses for "too big to be a house".
LARGE_FOOTPRINT_M2 = 350.0
PARTY_MIN_M = 6.0
PARTY_TOL_M = 1.0
OUTBUILDING_M2 = 40.0
RECT_FILL = 0.82


def _num(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = "".join(ch for ch in str(value) if ch.isdigit() or ch in ".-")
    if not text or text in (".", "-", "-."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _storeys(value):
    """Snap to the storey steps the mesh builders will understand."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    best = min(STOREY_STEPS, key=lambda step: abs(step - value))
    if abs(best - round(best)) < 1e-6:
        return int(round(best))
    return best


def measured_height(record):
    """Return (metres, reason) or (None, None) when the height is a guess."""
    tags = record.get("tags") or {}
    tagged = _num(tags.get("height") or tags.get("building:height"))
    if tagged and tagged > 2.0:
        return tagged, "tag_height"
    levels = _num(tags.get("levels") or tags.get("building:levels"))
    if levels and levels > 0:
        # Levels are the evidence. Metres are only so the storey bin can run.
        per = 3.2
        return levels * per, "levels"
    if record.get("source") == "ms":
        height = _num(record.get("height_m"))
        if height and height > 2.0:
            return height, "ms_height"
    if record.get("curated"):
        height = _num(record.get("height_m"))
        if height and height > 2.0:
            return height, "curated_height"
    return None, None


def storeys_from_height(height_m, commercial):
    if height_m < 4.5:
        return _storeys(1)
    if height_m < 6.5:
        return _storeys(1.5)
    if height_m < 9.5:
        return _storeys(2)
    if height_m < 12.5:
        return _storeys(3 if commercial else 2.5)
    return _storeys(3)


def storeys_from_levels(levels):
    return _storeys(min(6.0, max(1.0, levels)))


def _as_poly(coords):
    ring = dedupe_ring([(float(p[0]), float(p[1])) for p in coords])
    if len(ring) < 3:
        return None
    poly = Polygon(ring)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    return poly


def _unit(vec):
    if not vec:
        return None
    x, z = float(vec[0]), float(vec[1])
    length = math.hypot(x, z)
    if length < 1e-9:
        return None
    return (x / length, z / length)


def _street_axes(front_hint):
    """front_hint points from the building toward the road.

    Returns (into_lot, street_right). street_right is the viewer's right when
    standing in the street facing the building. x is east and z is south, so a
    person looking north (0, -1) has east, (1, 0), on their right:
    right = forward × up = (-fz, fx).
    """
    hint = _unit(front_hint)
    if hint is None:
        return None
    hx, hz = hint
    fx, fz = -hx, -hz
    return (fx, fz), (-fz, fx)


def _extent(coords, direction):
    dots = [p[0] * direction[0] + p[1] * direction[1] for p in coords]
    return max(dots) - min(dots)


def _bar_axes(corners, front_hint):
    """Width along the street, depth into the lot. Without a street, the long
    side of the rectangle is treated as the frontage."""
    axes = _street_axes(front_hint)
    if axes is None:
        e0 = math.hypot(corners[1][0] - corners[0][0], corners[1][1] - corners[0][1])
        e1 = math.hypot(corners[2][0] - corners[1][0], corners[2][1] - corners[1][1])
        if e0 >= e1:
            along = (corners[1][0] - corners[0][0], corners[1][1] - corners[0][1])
            across = (corners[2][0] - corners[1][0], corners[2][1] - corners[1][1])
        else:
            along = (corners[2][0] - corners[1][0], corners[2][1] - corners[1][1])
            across = (corners[1][0] - corners[0][0], corners[1][1] - corners[0][1])
        along = _unit(along)
        across = _unit(across)
        return _extent(corners, along), _extent(corners, across)
    into, right = axes
    return _extent(corners, right), _extent(corners, into)


def shared_boundary_length(poly, neighbors, tol=PARTY_TOL_M):
    """Longest single edge that runs alongside one neighbor.

    Measured along this building's own edges. A buffer around the neighbor
    would add round caps and turn a 5 m contact into more than 6 m, and
    adding every neighbor would turn two short contacts into a party wall.
    """
    if poly is None or not neighbors:
        return 0.0
    coords = list(poly.exterior.coords)
    best = 0.0
    for other in neighbors:
        other_poly = other if isinstance(other, Polygon) else _as_poly(other)
        if other_poly is None or other_poly.is_empty:
            continue
        overlap = poly.intersection(other_poly).area
        if overlap > 0.8 * min(poly.area, other_poly.area):
            continue
        zone = other_poly.buffer(tol)
        for index in range(len(coords) - 1):
            edge = LineString([coords[index], coords[index + 1]])
            if edge.length < 4.0:
                continue
            covered = edge.intersection(zone).length
            if covered >= 0.6 * edge.length and covered >= PARTY_MIN_M:
                best = max(best, covered)
    return best


def party_edges(poly, neighbors, tol=PARTY_TOL_M):
    """Edges of `poly` that run alongside another building. Each entry is
    ((x, z), (x, z)), using this ring's own vertices."""
    if poly is None or not neighbors:
        return []
    coords = list(poly.exterior.coords)
    found = []
    for other in neighbors:
        other_poly = other if isinstance(other, Polygon) else _as_poly(other)
        if other_poly is None or other_poly.is_empty:
            continue
        overlap = poly.intersection(other_poly).area
        if overlap > 0.8 * min(poly.area, other_poly.area):
            continue
        zone = other_poly.buffer(tol)
        for index in range(len(coords) - 1):
            a, b = coords[index], coords[index + 1]
            edge = LineString([a, b])
            if edge.length < 4.0:
                continue
            covered = edge.intersection(zone).length
            if covered >= 0.6 * edge.length and covered >= PARTY_MIN_M:
                found.append((
                    (round(a[0], 2), round(a[1], 2)),
                    (round(b[0], 2), round(b[1], 2)),
                ))
    return found


def _notches(poly):
    rect = poly.minimum_rotated_rectangle
    if rect.is_empty or rect.area < 1.0:
        return rect, []
    diff = rect.difference(poly)
    if diff.is_empty:
        return rect, []
    geoms = list(diff.geoms) if diff.geom_type == "MultiPolygon" else [diff]
    parts = []
    for geom in geoms:
        if geom.geom_type != "Polygon" or geom.area < rect.area * 0.05:
            continue
        box = geom.minimum_rotated_rectangle
        fill = geom.area / box.area if box.area else 0.0
        parts.append((geom, fill))
    return rect, parts


def _notch_is_corner(rect, notch):
    """A gabled ell is a corner missing from the rectangle. A bite out of the
    middle of one side (a front court) is not."""
    coords = list(rect.exterior.coords)
    grown = notch.buffer(0.2)
    touches = 0
    for index in range(len(coords) - 1):
        edge = LineString([coords[index], coords[index + 1]])
        if edge.intersection(grown).length > 0.4:
            touches += 1
    return touches >= 2


def _wing_side(poly, rect, notch, front_hint):
    """Which side of the front the ell occupies, as seen from the street."""
    axes = _street_axes(front_hint)
    if axes is None:
        return "left"
    _into, right = axes
    origin = polygon_centroid_2d(list(rect.exterior.coords)[:-1])
    center = polygon_centroid_2d(list(notch.exterior.coords)[:-1])
    offset = (center[0] - origin[0], center[1] - origin[1])
    lateral = offset[0] * right[0] + offset[1] * right[1]
    # The notch is the missing corner, so the wing is the other side. A front
    # corner is still a side wing: the usual gabled ell is missing the front
    # yard on one side. "rear" is only a notch centered on the back.
    hint = _unit(front_hint)
    toward_street = offset[0] * hint[0] + offset[1] * hint[1]
    if abs(lateral) < 0.75 and toward_street < 0.0:
        return "rear"
    return "left" if lateral > 0.0 else "right"


def _defaults(form, width, depth, in_downtown):
    roof, axis = "gable", "side"
    porch = "none"
    material = "clapboard"
    dressing = "plain"
    storeys = 1.5
    if form == "front_gable":
        axis = "front"
        porch = "stoop"
    elif form == "side_gable":
        porch = "stoop"
    elif form == "gabled_ell":
        porch = "ell_corner"
        dressing = "folk_victorian"
    elif form == "foursquare":
        roof, axis = "pyramidal", "side"
        porch = "shed_full"
        storeys = 2
    elif form == "bungalow":
        axis = "front" if depth > width else "side"
        porch = "gable_full"
        dressing = "craftsman"
    elif form == "cross_gable":
        axis = "front"
        porch = "wrap"
        dressing = "folk_victorian"
        storeys = 2
    elif form == "ranch":
        roof = "hip"
        porch = "stoop"
        dressing = "midcentury"
        storeys = 1
    elif form == "party_wall_commercial":
        roof = "flat_parapet"
        porch = "none"
        material = "brick"
        dressing = "italianate" if in_downtown else "commercial_1900"
        storeys = 2
    elif form == "one_story_store":
        roof = "flat_parapet"
        material = "brick"
        dressing = "commercial_1900"
        storeys = 1
    elif form == "civic_block":
        roof = "flat_parapet"
        material = "brick"
        porch = "stoop"
        storeys = 2
    elif form == "church_nave":
        axis = "front"
        material = "brick"
        porch = "stoop"
        storeys = 1
    elif form == "industrial":
        material = "brick"
        storeys = 1
    elif form == "garage":
        axis = "front"
        storeys = 1
    return {
        "roof": roof,
        "roof_axis": axis,
        "porch": porch,
        "material": material,
        "dressing": dressing,
        "storeys": _storeys(storeys),
        "wing": "none",
    }


def _finish(form, reason, confidence, width, depth, in_downtown, storeys, wing, height_reason):
    record = _defaults(form, width, depth, in_downtown)
    record["form"] = form
    record["wing"] = wing if form == "gabled_ell" else "none"
    if storeys is not None:
        record["storeys"] = _storeys(storeys)
        if form == "party_wall_commercial" and record["storeys"] == 1:
            record = _defaults("one_story_store", width, depth, in_downtown)
            record["form"] = "one_story_store"
            record["wing"] = "none"
            form = "one_story_store"
            reason = "party_wall"
    elif form == "one_story_store":
        record["storeys"] = 1
    record["reason"] = reason
    record["form_confidence"] = confidence
    record["height_reason"] = height_reason
    record["source"] = "auto"
    return record


def _form_for_bar(width, depth, storeys, residential_edge):
    aspect = max(width, depth) / max(min(width, depth), 0.5)
    street_long = width > depth * 1.15
    # A few percent of extra depth is not a narrow lot. Front-gable only once
    # the plan is outside the nearly-square band (aspect >= 1.35) and the
    # long axis runs away from the street.
    clearly_deep = depth > width and aspect >= 1.35
    nearly_square = aspect < 1.35
    if storeys is not None and storeys <= 1 and street_long and width >= 14.0:
        return "ranch", "long_bar", "high"
    if storeys is None and street_long and width >= 16.0 and width > depth * 1.6:
        return "ranch", "long_bar", "high"
    if nearly_square and storeys is not None and storeys >= 2:
        return "foursquare", "square", "high"
    if nearly_square and storeys is None and residential_edge:
        return "foursquare", "square", "high"
    if clearly_deep:
        return "front_gable", "deep_bar", "high"
    if (storeys is None or storeys <= 1.5) and street_long and width >= 7.5:
        return "bungalow", "wide_low", "high"
    return "side_gable", "default_bar", "high"


def _house_from_shape(poly, front_hint, storeys, residential_edge):
    rect, parts = _notches(poly)
    fill = poly.area / rect.area if rect is not None and rect.area else 1.0
    corners = list(rect.exterior.coords)[:-1] if rect is not None else list(poly.exterior.coords)[:-1]
    width, depth = _bar_axes(corners, front_hint)
    clean_notches = [
        geom for geom, notch_fill in parts
        if notch_fill >= 0.65 and _notch_is_corner(rect, geom)
    ]
    if len(clean_notches) == 1 and 0.50 <= fill <= RECT_FILL:
        wing = _wing_side(poly, rect, clean_notches[0], front_hint)
        return "gabled_ell", "ell", "high", width, depth, wing
    if fill < RECT_FILL:
        form, reason, _confidence = _form_for_bar(width, depth, storeys, residential_edge)
        return form, "irregular", "low", width, depth, "none"
    form, reason, confidence = _form_for_bar(width, depth, storeys, residential_edge)
    return form, reason, confidence, width, depth, "none"


def _tagged_form(tags):
    building = (tags.get("building") or "yes")
    if isinstance(building, str):
        building = building.lower()
    amenity = (tags.get("amenity") or "")
    if isinstance(amenity, str):
        amenity = amenity.lower()
    if amenity == "place_of_worship" or building == "church":
        return "church_nave", "tag_church"
    if building in ("garage", "garages", "shed", "carport", "roof"):
        return "garage", "tag_garage"
    if building == "industrial" or tags.get("man_made"):
        return "industrial", "tag_industrial"
    if building in ("school", "hospital", "public", "civic", "government", "office") or amenity in (
        "school", "hospital", "library", "townhall", "community_centre", "post_office", "courthouse",
    ):
        return "civic_block", "tag_civic"
    if building in ("retail", "commercial") or amenity in (
        "fast_food", "restaurant", "fuel", "car_wash", "bank", "cafe", "dentist",
    ):
        return "party_wall_commercial", "tag_commercial"
    return None, None


def _apply_roof_tag(record, tags):
    shape = (tags.get("roof_shape") or tags.get("roof:shape") or "")
    if isinstance(shape, str):
        shape = shape.lower()
    mapped = {
        "gabled": ("gable", None),
        "gable": ("gable", None),
        "hipped": ("hip", None),
        "hip": ("hip", None),
        "pyramidal": ("pyramidal", None),
        "flat": ("flat_parapet", None),
        "skillion": ("flat_parapet", None),
        "gambrel": ("gambrel", None),
        "mansard": ("gambrel", None),
        "round": ("hip", None),
    }.get(shape)
    if mapped:
        record["roof"] = mapped[0]
        record["reason"] = record["reason"] + "+roof_tag"


def _apply_override(auto, override, width, depth, in_downtown):
    if not override:
        return auto
    out = dict(auto)
    form = override.get("form") or auto["form"]
    if form not in FORMS:
        form = auto["form"]
    if form != auto["form"]:
        fresh = _defaults(form, width, depth, in_downtown)
        fresh["form"] = form
        fresh["wing"] = "none"
        for key in FIELDS:
            if key not in override or override.get(key) in (None, ""):
                if key == "storeys" and auto.get("height_reason"):
                    fresh["storeys"] = auto["storeys"]
                    continue
                out[key] = fresh[key]
        out["form"] = form
    for key in FIELDS:
        if override.get(key) not in (None, ""):
            value = override[key]
            if key == "form" and value not in FORMS:
                continue
            if key == "storeys":
                value = _storeys(value)
                if value is None:
                    continue
            out[key] = value
    out["source"] = "override"
    out["reason"] = "user"
    out["form_confidence"] = "high"
    out["height_reason"] = auto.get("height_reason")
    return out


def resolve_template(coords, tags=None, bid=None, height_m=None, source=None, curated=False,
                     infill=False, neighbors=None, front_hint=None, in_downtown=False,
                     residential_edge=False, override=None):
    """Decide one template. `override` replaces fields; it does not have to be complete."""
    tags = tags or {}
    record_in = {
        "id": bid,
        "tags": tags,
        "height_m": height_m,
        "source": source,
        "curated": curated,
        "infill": infill,
    }
    poly = _as_poly(coords)
    if poly is None:
        empty = _defaults("garage", 4.0, 6.0, False)
        empty.update({
            "form": "garage", "reason": "degenerate", "form_confidence": "low",
            "height_reason": None, "source": "auto", "id": bid,
        })
        return empty

    height, height_reason = measured_height(record_in)
    # A levels tag names the storeys directly. A metre height is binned.
    level_count = _num(tags.get("levels") or tags.get("building:levels"))
    tagged_building = tags.get("building") or ""
    commercial_hint = tagged_building in (
        "retail", "commercial", "office", "public", "civic", "government", "industrial",
    )
    if level_count:
        storeys = storeys_from_levels(level_count)
        height_reason = "levels"
    elif height is not None:
        storeys = storeys_from_height(height, commercial_hint)
    else:
        storeys = None

    tagged, tag_reason = _tagged_form(tags)
    width, depth = _bar_axes(list(poly.minimum_rotated_rectangle.exterior.coords)[:-1], front_hint)
    wing = "none"
    if tagged:
        form, reason, confidence = tagged, tag_reason, "high"
    elif poly.area < OUTBUILDING_M2:
        form, reason, confidence = "garage", "small_outbuilding", "high"
    else:
        form, reason, confidence, width, depth, wing = _house_from_shape(
            poly, front_hint, storeys, residential_edge)
        shared = shared_boundary_length(poly, neighbors)
        attached = shared >= PARTY_MIN_M and poly.area >= 70.0
        clear_ell = form == "gabled_ell" and confidence == "high"
        # A measured ell stays a house even on a large downtown lot. Attachment
        # and the big-box prior apply to everything that did not resolve as one.
        if clear_ell and not attached:
            pass
        elif attached or (in_downtown and poly.area >= LARGE_FOOTPRINT_M2):
            form = "party_wall_commercial"
            reason = "party_wall" if attached else "downtown_large"
            confidence = "high"
            wing = "none"
        elif poly.area >= 600.0:
            form, reason, confidence, wing = "civic_block", "large_footprint", "high", "none"
    if height is not None and height >= 12.5 and form in (
        "side_gable", "front_gable", "gabled_ell", "foursquare", "bungalow", "cross_gable", "ranch",
    ):
        form, reason, confidence, wing = "civic_block", "tall", "high", "none"

    resolved = _finish(form, reason, confidence, width, depth, in_downtown, storeys, wing, height_reason)
    resolved["id"] = bid
    _apply_roof_tag(resolved, tags)
    resolved = _apply_override(resolved, override, width, depth, in_downtown)
    resolved["party_edges"] = party_edges(poly, neighbors)
    resolved["flip_normals"] = bool(override and override.get("flip_normals"))
    resolved["tower"] = bool(override and override.get("tower"))
    if override and override.get("ground") in ("normal", "double"):
        resolved["ground"] = override["ground"]
    if override and override.get("awnings") in ("none", "some", "row"):
        resolved["awnings"] = override["awnings"]
    if override and override.get("color") in (
        "brick_red", "brick_buff", "brick_rose", "brick_dark", "brick_cream",
        "limestone", "siding_white", "siding_gray", "siding_sage", "siding_blue", "siding_butter",
    ):
        resolved["color"] = override["color"]
    if override and isinstance(override.get("compose"), dict):
        resolved["compose"] = override["compose"]
    return resolved


def front_from_road(center, road_index):
    """Direction from a building center toward the nearest road, or south."""
    if road_index is None:
        return (0.0, 1.0)
    segment, _distance = road_index.nearest(center[0], center[1], 250.0)
    if not segment:
        return (0.0, 1.0)
    ax, az, bx, bz = segment[0], segment[1], segment[2], segment[3]
    length2 = (bx - ax) ** 2 + (bz - az) ** 2
    if length2 < 1e-9:
        return (0.0, 1.0)
    t = ((center[0] - ax) * (bx - ax) + (center[1] - az) * (bz - az)) / length2
    t = max(0.0, min(1.0, t))
    return (ax + t * (bx - ax) - center[0], az + t * (bz - az) - center[1])


def resolve_batch(records, road_index, overrides=None):
    """Template for every record, keyed by id. Infill included. Same front and
    neighbor rules as the report, so a mesh and a count cannot disagree."""
    import classify

    overrides = overrides or {}
    polys = []
    for record in records:
        coords = []
        for point in record.get("footprint") or []:
            if isinstance(point, dict):
                coords.append((point["x"], point["z"]))
            else:
                coords.append((point[0], point[1]))
        polys.append(_as_poly(coords))
    tree_polys = [poly for poly in polys if poly is not None]
    tree = STRtree(tree_polys) if tree_polys else None
    out = {}
    for record, poly in zip(records, polys):
        if poly is None:
            continue
        center = polygon_centroid_2d(list(poly.exterior.coords)[:-1])
        neighbors = []
        if tree is not None:
            probe = poly.buffer(PARTY_TOL_M + 0.5)
            for hit in tree.query(probe):
                other = tree_polys[int(hit)]
                if other is poly:
                    continue
                neighbors.append(other)
        bid = record.get("id")
        out[bid] = resolve_record(
            record,
            neighbors=neighbors,
            front_hint=front_from_road(center, road_index),
            in_downtown=classify.in_downtown(center[0], center[1]),
            residential_edge=classify.in_house_zone(center[0], center[1]),
            override=overrides.get(bid),
        )
    return out


def resolve_record(record, neighbors=None, front_hint=None, in_downtown=False,
                   residential_edge=False, override=None):
    footprint = record.get("footprint") or []
    coords = []
    for point in footprint:
        if isinstance(point, dict):
            coords.append((point["x"], point["z"]))
        else:
            coords.append((point[0], point[1]))
    return resolve_template(
        coords,
        tags=record.get("tags") or {},
        bid=record.get("id"),
        height_m=record.get("height_m"),
        source=record.get("source"),
        curated=bool(record.get("curated")),
        infill=bool(record.get("infill")),
        neighbors=neighbors,
        front_hint=front_hint,
        in_downtown=in_downtown,
        residential_edge=residential_edge,
        override=override,
    )


def load_overrides(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path) as handle:
        data = json.load(handle)
    buildings = data.get("buildings", data)
    out = {}
    for key, value in buildings.items():
        try:
            out[int(key)] = value
        except (TypeError, ValueError):
            out[key] = value
    return out


def _load_json(path):
    with open(path) as handle:
        return json.load(handle)


def iter_real_records(root):
    """OSM, curated, and Microsoft footprints. Not procedural infill."""
    game_data = os.path.join(root, "game", "data")
    buildings = _load_json(os.path.join(game_data, "buildings.json"))["buildings"]
    curated_path = os.path.join(game_data, "buildings_curated.json")
    curated = []
    replaced = set()
    if os.path.exists(curated_path):
        for record in _load_json(curated_path).get("buildings", []):
            replaced.update(record.get("replaces") or [])
            record = dict(record)
            record["curated"] = True
            curated.append(record)
    if replaced:
        buildings = [record for record in buildings if record.get("id") not in replaced]
    ms_path = os.path.join(game_data, "buildings_ms.json")
    ms_records = _load_json(ms_path).get("buildings", []) if os.path.exists(ms_path) else []
    return buildings + curated + ms_records


def report(root):
    """Count templates for the real footprints and print the low-confidence ids."""
    from common_buildings import SegmentIndex
    from build_building_plan import LANDMARK_OWNED_IDS

    records = [record for record in iter_real_records(root) if record.get("id") not in LANDMARK_OWNED_IDS]
    game_data = os.path.join(root, "game", "data")
    roads = _load_json(os.path.join(game_data, "roads.json"))
    road_index = SegmentIndex(cell=100.0)
    for way in roads["ways"]:
        verts = way["vertices"]
        for index in range(len(verts) - 1):
            a, b = verts[index], verts[index + 1]
            road_index.add(a["x"], a["z"], b["x"], b["z"])

    overrides = load_overrides(os.path.join(game_data, "building_overrides.json"))
    resolved_by_id = resolve_batch(records, road_index, overrides)
    counts = {}
    low = []
    for record in records:
        bid = record.get("id")
        resolved = resolved_by_id.get(bid)
        if resolved is None:
            continue
        counts[resolved["form"]] = counts.get(resolved["form"], 0) + 1
        if resolved["form_confidence"] == "low":
            low.append(bid)

    print(f"templates: {sum(counts.values())}")
    for form, count in sorted(counts.items(), key=lambda item: -item[1]):
        print(f"  {form:24} {count}")
    print(f"low confidence: {len(low)}")
    if low:
        print("low ids:", ", ".join(str(item) for item in low[:25]))
    return counts, low


if __name__ == "__main__":
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    report(ROOT)
