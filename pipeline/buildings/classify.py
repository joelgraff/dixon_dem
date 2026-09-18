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


def in_downtown(cx, cz):
    x0, z0, x1, z1 = DOWNTOWN_BOUNDS
    return x0 <= cx <= x1 and z0 <= cz <= z1


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
    return "residential_house"
