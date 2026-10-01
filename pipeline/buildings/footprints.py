"""Every building outline the game knows, by id, with Building Composer's
corrections over them.

Sources (game/data/): OSM (buildings.json), hand traces
(buildings_curated.json, each replacing the OSM ids in its `replaces`), and
Microsoft's ML footprints (buildings_ms.json). A correction made in Composer's
footprint editor is game/data/footprint_overrides/<id>.json
(`format: 'dixon-footprint-override'`): its `footprint` replaces that
building's, and its `based_on.hash` is outline_hash() of the outline it was
drawn over, so a source outline that has changed since is noticed.

Microsoft ids are 800000000 + the record's position in ms_footprints.py's
output, so a re-fetch can move an id to another building. An override whose
outline lies well away from the building that now has its id is skipped,
with a warning, rather than moving the wrong building.
"""
import json
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GAME_DATA = os.path.join(ROOT, "game", "data")
OVERRIDES_DIR = os.path.join(GAME_DATA, "footprint_overrides")
# how far an override's outline may sit from its building's before it is taken for another building's
MAX_OVERRIDE_SHIFT = 10.0


def points(footprint):
    """An outline as an open ring of [x, z] (from {"x", "z"} dicts or pairs)."""
    ring = [[float(p["x"]), float(p["z"])] if isinstance(p, dict) else [float(p[0]), float(p[1])] for p in footprint or []]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring


def outline_hash(footprint):
    """A short fingerprint of an outline to the millimeter, the same whatever
    corner it starts at or which way it runs. Matches Building Composer's
    outlineHash (js/import.js), which records it for the outline it imported."""
    ring = [[math.floor(x * 1000 + 0.5), math.floor(z * 1000 + 0.5)] for x, z in points(footprint)]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    signed = sum(x * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * z for i, (x, z) in enumerate(ring))
    if signed < 0:
        ring.reverse()
    first = min(range(len(ring)), key=lambda i: (ring[i][0], ring[i][1])) if ring else 0
    text = ";".join(f"{x},{z}" for x, z in ring[first:] + ring[:first])
    value = 0x811C9DC5
    for ch in text:
        value = ((value ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return f"{len(ring)}-{value:08x}"


def centroid(ring):
    area = cx = cz = 0.0
    for i, (x, z) in enumerate(ring):
        nx, nz = ring[(i + 1) % len(ring)]
        cross = x * nz - nx * z
        area += cross
        cx += (x + nx) * cross
        cz += (z + nz) * cross
    if abs(area) < 1e-9:
        return ring[0] if ring else [0.0, 0.0]
    return [cx / (3 * area), cz / (3 * area)]


def _read(path):
    with open(path) as handle:
        return json.load(handle)


def load_sources(game_data=GAME_DATA):
    """Every source outline, as {"id" (str), "source", "footprint": [[x, z], ...]},
    with curated traces in place of the OSM ids they replace."""
    def records(name):
        path = os.path.join(game_data, name)
        return _read(path).get("buildings", []) if os.path.exists(path) else []

    osm = records("buildings.json")
    curated = records("buildings_curated.json")
    replaced = {str(bid) for record in curated for bid in record.get("replaces", [])}
    out = []
    for source, recs in (("osm", osm), ("curated", curated), ("ms", records("buildings_ms.json"))):
        for record in recs:
            bid = str(record.get("id"))
            if source == "osm" and bid in replaced:
                continue
            ring = points(record.get("footprint"))
            if len(ring) >= 3:
                out.append({"id": bid, "source": source, "footprint": ring})
    return out


def load_overrides(directory=OVERRIDES_DIR):
    """The footprint overrides, by building id (unreadable or foreign files are skipped)."""
    out = {}
    if not os.path.isdir(directory):
        return out
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            data = _read(os.path.join(directory, name))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("format") == "dixon-footprint-override" and len(points(data.get("footprint"))) >= 3:
            out[str(data.get("id"))] = data
    return out


def apply_overrides(records, overrides, warn=print):
    """`records` with each overridden building's footprint replaced (marked
    `override: True`, with the override's `porches`). Warns where the source
    outline changed since the override was drawn; skips an override that lies
    away from its building (see the module notes)."""
    out = []
    for record in records:
        override = overrides.get(record["id"])
        if not override:
            out.append(record)
            continue
        ring = points(override["footprint"])
        shift = math.dist(centroid(ring), centroid(record["footprint"]))
        if shift > MAX_OVERRIDE_SHIFT:
            warn(f"footprint override {record['id']}: its outline is {shift:.0f} m from the building with that id "
                 f"({record['source']}), so it is skipped; the id may have moved to another building")
            out.append(record)
            continue
        drawn_on = (override.get("based_on") or {}).get("hash")
        if drawn_on and drawn_on != outline_hash(record["footprint"]):
            warn(f"footprint override {record['id']}: the {record['source']} outline has changed since it was drawn; "
                 "the override is still used")
        out.append({**record, "footprint": ring, "override": True, "porches": override.get("porches") or []})
    return out


def override_records(records, source, overrides, warn=print):
    """The building plan's own records (footprints as {"x", "z"} rings) with
    Composer's corrections over them, in place, by the same rules as
    apply_overrides: an overridden record gets the override's outline (a
    closed ring), `footprint_override: True`, and its porches as
    `override_porches`. Returns `records`."""
    for record in records:
        bid = str(record.get("id"))
        override = overrides.get(bid)
        if not override:
            continue
        source_record = {"id": bid, "source": source, "footprint": points(record.get("footprint"))}
        if len(source_record["footprint"]) < 3:
            continue
        [applied] = apply_overrides([source_record], {bid: override}, warn)
        if not applied.get("override"):
            continue
        ring = applied["footprint"]
        record["footprint"] = [{"x": x, "z": z} for x, z in ring + ring[:1]]
        record["footprint_override"] = True
        record["override_porches"] = applied["porches"]
    return records


def apply_override_porches(records, template_of, explicit):
    """Porches a footprint override brought (made with Turn into a porch in
    Composer): the template's porch is the first one's kind, unless
    building_overrides.json names one for the building, and every porch's
    legs go in `porch_legs`, built exactly where they are (archetypes.py
    _place_porch) instead of the kind's default edge and size."""
    for record in records:
        porches = record.get("override_porches") or []
        legs = [{**leg, "kind": porch.get("kind")} for porch in porches for leg in porch.get("legs") or []]
        if not legs:
            continue
        bid = record.get("id")
        named = (explicit.get(bid) or explicit.get(str(bid)) or {}).get("porch")
        template = dict(template_of.get(bid) or {})
        template["porch"] = named or porches[0].get("kind") or "shed_full"
        template["porch_legs"] = legs
        template_of[bid] = template
    return template_of


def all_outlines(game_data=GAME_DATA, overrides_dir=OVERRIDES_DIR, warn=print):
    return apply_overrides(load_sources(game_data), load_overrides(overrides_dir), warn)


def in_box(records, x0, z0, x1, z1):
    """The records whose outline's bounds meet the box."""
    out = []
    for record in records:
        xs = [p[0] for p in record["footprint"]]
        zs = [p[1] for p in record["footprint"]]
        if min(xs) <= x1 and max(xs) >= x0 and min(zs) <= z1 and max(zs) >= z0:
            out.append(record)
    return out
