"""Pinned horizontal geometry: alignment_overrides.json's `horizontal` section (no numpy).

Each entry pins a route's PIs and radii, over the whole route or a stretch of it:

  {"route": "R21838771",
   "pis": [[x, z], ...], "radii": [0, R, ..., 0],      # game metres, one radius per PI
   "sta": [from, to],                                   # optional: metres along the route's OSM line
   "note": "why"}

Without `sta` the entry is the route's alignment (build_alignments.py does not fit it). With `sta`
the pinned PIs replace the fitted ones over that stretch of the OSM line (0 and the line's length
reach the route's ends); the PIs outside it are fitted as before and join the pinned ones by
being PIs of the same chain. The first and last pinned PIs are interior PIs of the route and
keep their radii, so a curve there joins the pinned stretch to the fitted line tangentially (a
radius of 0 is a deliberate angle point, reported). The pinned radii are never changed; a fitted
neighbour's radius is reduced if its curve would overlap a pinned one.

This module reads and writes the file for composer_server.py and the build, so it needs no
numpy; the geometry checks are alignment_geom's.
"""
import json
import math
import os
import re
import tempfile

import alignment_geom as geom

HERE = os.path.dirname(os.path.abspath(__file__))
OVERRIDES_PATH = os.path.join(HERE, "alignment_overrides.json")
ROUTE_ID = re.compile(r"^R[0-9]{1,12}(_[0-9]{1,3})?$")
MAX_NOTE = 600


def load(path=OVERRIDES_PATH):
    with open(path) as handle:
        return json.load(handle)


def entries(doc):
    return doc.get("horizontal", [])


def pins_by_route(doc):
    """{route id: [entry, ...]} of the pinned horizontal geometry."""
    out = {}
    for e in entries(doc):
        out.setdefault(e["route"], []).append(e)
    return out


def clean_entry(body):
    """A validated, normalised entry from a request body (dict), else ValueError."""
    if not isinstance(body, dict):
        raise ValueError("expected an object")
    route = body.get("route")
    if not isinstance(route, str) or not ROUTE_ID.match(route):
        raise ValueError("bad route id")
    partial = body.get("sta") is not None
    pis, radii = geom.validate(body.get("pis"), body.get("radii"), keep_ends=partial)
    note = body.get("note")
    if not isinstance(note, str) or not note.strip():
        raise ValueError("a pinned alignment needs a note saying why")
    if len(note) > MAX_NOTE:
        raise ValueError("the note is too long")
    out = {"route": route, "pis": [[round(x, 3), round(z, 3)] for x, z in pis],
           "radii": [round(r, 3) for r in radii], "note": note.strip()}
    sta = body.get("sta")
    if sta is not None:
        if (not isinstance(sta, list) or len(sta) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in sta)
                or sta[1] <= sta[0]):
            raise ValueError("sta is [from, to] metres along the route, from < to")
        out["sta"] = [round(float(sta[0]), 2), round(float(sta[1]), 2)]
    return out


def _write(doc, path):
    handle, temp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(handle, "w") as out:
        json.dump(doc, out, indent=2)
        out.write("\n")
    os.chmod(temp, 0o644)
    os.replace(temp, path)


def _placed(doc, rows):
    """doc with `horizontal` set to rows, the section kept ahead of `profile` in the file."""
    out = {}
    for k, v in doc.items():
        if k == "horizontal":
            continue
        if k == "profile":
            out["horizontal"] = rows
        out[k] = v
    out.setdefault("horizontal", rows)
    return out


def save(body, path=OVERRIDES_PATH):
    """Pins a route: writes the entry, replacing the route's earlier ones. Returns the entry."""
    entry = clean_entry(body)
    doc = load(path)
    rows = [e for e in entries(doc) if e["route"] != entry["route"]] + [entry]
    _write(_placed(doc, rows), path)
    return entry


def remove(route, path=OVERRIDES_PATH):
    """Unpins a route (back to the fit). Returns how many entries were removed."""
    if not isinstance(route, str) or not ROUTE_ID.match(route):
        raise ValueError("bad route id")
    doc = load(path)
    keep = [e for e in entries(doc) if e["route"] != route]
    removed = len(entries(doc)) - len(keep)
    if removed:
        _write(_placed(doc, keep), path)
    return removed


# -- cross-section width pins: alignment_overrides.json `templates` entries made in the editor ----------------
WIDTH_FT = (8.0, 100.0)


def save_width(body, path=OVERRIDES_PATH):
    """Pins the curb-to-curb width of a route's station range (a `templates` entry with a note).
    An entry for exactly that range is replaced; others are left (a later entry wins where they overlap)."""
    if not isinstance(body, dict):
        raise ValueError("expected an object")
    route, sta, ft, note = body.get("route"), body.get("sta"), body.get("curb_to_curb_ft"), body.get("note")
    if not isinstance(route, str) or not ROUTE_ID.match(route):
        raise ValueError("bad route id")
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    if not (isinstance(sta, list) and len(sta) == 2 and all(num(v) for v in sta) and 0 <= sta[0] < sta[1]):
        raise ValueError("sta is [from, to] metres along the route")
    if not num(ft) or not WIDTH_FT[0] <= ft <= WIDTH_FT[1]:
        raise ValueError("curb to curb must be %g to %g ft" % WIDTH_FT)
    if not isinstance(note, str) or not note.strip() or len(note) > MAX_NOTE:
        raise ValueError("a width pin needs a note saying why")
    entry = {"route": route, "sta": [round(float(sta[0]), 1), round(float(sta[1]), 1)],
             "curb_to_curb_ft": round(float(ft), 1), "note": note.strip()}
    doc = load(path)
    rows = [t for t in doc.get("templates", []) if not (t.get("route") == route and t.get("sta") == entry["sta"]
                                                         and t.get("source") is None)] + [entry]
    doc["templates"] = rows
    _write(doc, path)
    return entry


def width_pins(doc, route):
    return [t for t in doc.get("templates", []) if t.get("route") == route and t.get("source") is None and "curb_to_curb_ft" in t]
