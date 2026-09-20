"""Archetype classification for buildings.json footprints. Heuristic: explicit
OSM tags first, then location (inside the downtown core bounds -> commercial
block) and footprint size, matching the brief's archetype list. See
docs/buildings_notes.md.
"""

# Downtown commercial core bounding box (Godot local x,z), matches the
# Galena/1st/2nd/Hennepin/Peoria blocks around the courthouse/theatre/arch --
# independently eyeballed from the landmark coordinates in
# docs/pipeline_notes.md (courthouse 1691,-1233; theatre 1610,-1381; arch
# 1631,-1214; nachusa 1601,-1220), padded to cover the surrounding blocks.
DOWNTOWN_BOUNDS = (1280.0, -1830.0, 1980.0, -1000.0)

CHURCH_AMENITY = {"place_of_worship"}
INSTITUTIONAL_BUILDING = {"school", "hospital", "public"}
INSTITUTIONAL_AMENITY = {"school", "hospital", "library", "townhall", "community_centre",
                          "post_office", "courthouse"}
COMMERCIAL_BUILDING = {"retail", "commercial"}
COMMERCIAL_AMENITY = {"fast_food", "restaurant", "fuel", "car_wash", "bank", "cafe", "dentist"}


# --- Aerial reference frame (docs/STATUS.md, 2026-09-20) --------------------------------
# The user's Google Earth aerial (screenshots/dixon_downtown_aerial.png, 1795x900) is
# rotated so that Galena Avenue's bearing (344 deg) runs left->right (north/river = RIGHT,
# east = DOWN). Fitted against OSM roads + footprints: 3.0 px per metre, Dixon Memorial Arch
# footprint centroid (1631.3, -1214.2) at pixel (758, 450). Verified visually: OSM footprints
# land within ~1-2 m of the roofs in the image wherever OSM has them.
import math as _math
AERIAL_SIZE = (1795, 900)
AERIAL_SCALE = 3.0
AERIAL_ANCHOR_WORLD = (1631.3, -1214.2)
AERIAL_ANCHOR_PX = (758.0, 450.0)
AERIAL_BEARING_DEG = 344.0


def world_to_aerial_px(x, z):
    b = _math.radians(AERIAL_BEARING_DEG)
    dE, dN = _math.sin(b), _math.cos(b)
    e = x - AERIAL_ANCHOR_WORLD[0]
    n = -(z - AERIAL_ANCHOR_WORLD[1])
    u = e * dE + n * dN
    v = e * dN - n * dE
    return (AERIAL_ANCHOR_PX[0] + u * AERIAL_SCALE, AERIAL_ANCHOR_PX[1] + v * AERIAL_SCALE)


def aerial_px_to_world(px, py):
    b = _math.radians(AERIAL_BEARING_DEG)
    dE, dN = _math.sin(b), _math.cos(b)
    u = (px - AERIAL_ANCHOR_PX[0]) / AERIAL_SCALE
    v = (py - AERIAL_ANCHOR_PX[1]) / AERIAL_SCALE
    e = u * dE + v * dN
    n = u * dN - v * dE
    return (AERIAL_ANCHOR_WORLD[0] + e, AERIAL_ANCHOR_WORLD[1] - n)


def in_aerial(x, z):
    px, py = world_to_aerial_px(x, z)
    return 0.0 <= px <= AERIAL_SIZE[0] and 0.0 <= py <= AERIAL_SIZE[1]


# West of this pixel column (i.e. away from the river, beyond the Hennepin/Peoria government
# blocks) the aerial shows ordinary houses, churches and parking - NOT the commercial core.
AERIAL_HOUSE_ZONE_PX_X = 690.0


def in_house_zone(x, z):
    px, py = world_to_aerial_px(x, z)
    return 0.0 <= py <= AERIAL_SIZE[1] and px < AERIAL_HOUSE_ZONE_PX_X and px > -400.0


def in_downtown(cx, cz):
    x0, z0, x1, z1 = DOWNTOWN_BOUNDS
    if not (x0 <= cx <= x1 and z0 <= cz <= z1):
        return False
    return not in_house_zone(cx, cz)


def classify(tags, cx, cz, area_m2):
    b = tags.get("building") or "yes"
    amenity = tags.get("amenity")
    name = (tags.get("name") or "").lower()

    if amenity in CHURCH_AMENITY or b == "church":
        return "church"
    if b in INSTITUTIONAL_BUILDING or amenity in INSTITUTIONAL_AMENITY:
        return "institutional"
    if b == "industrial" or "industrial" in name or tags.get("man_made"):
        return "industrial"
    if b in ("garage", "roof"):
        return "garage"
    if area_m2 > 1400 and b in ("retail", "yes", "commercial", "industrial"):
        return "bigbox_retail"
    downtown = in_downtown(cx, cz)
    if downtown and area_m2 < 1400:
        return "downtown_commercial"
    if b in COMMERCIAL_BUILDING or amenity in COMMERCIAL_AMENITY:
        return "strip_commercial"
    # Too big to be a house (offices, clinics, apartment slabs that OSM tags only building=yes):
    # give them a flat-roofed boxy massing instead of a pitched-roof "house".
    if area_m2 >= 350 and b in ("yes", "office", "public", "civic", "government", "commercial"):
        return "strip_commercial"
    return "residential_house"
