"""Server side of Bridge Composer's Alignments mode: routes, pinned geometry, the review queue.

composer_server.py serves these (plain Python: the system python3 that runs it has no numpy).

  routes        game/data/alignments.json (build_alignments.py) and templates.json, read as they are
  pins          pipeline/roads/alignment_overrides.json `horizontal` (horizontal_overrides.py)
  review queue  a seeded random sample of surveyed street blocks, plus the flagged places the
                audits already list (alignment_report.json off_centre_blocks, the footprint audit's
                roofless_review.json and street_overlaps.json)
  review store  docs/review/alignment_review.json, tracked: what the reviewer decided at each place
"""
import datetime
import json
import math
import os
import random
import re
import tempfile

import alignment_geom as geom
import horizontal_overrides as ho

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ALIGNMENTS_PATH = os.path.join(ROOT, "game", "data", "alignments.json")
TEMPLATES_PATH = os.path.join(ROOT, "game", "data", "templates.json")
REPORT_PATH = os.path.join(ROOT, "game", "roads", "_build", "alignment_report.json")
AUDIT_DIR = os.path.join(ROOT, "docs", "footprint_aerial_audit")
REVIEW_PATH = os.path.join(ROOT, "docs", "review", "alignment_review.json")

REVIEW_ID = re.compile(r"^[0-9A-Za-z_.:+-]{1,80}$")
REVIEW_STATUS = ("ok", "wrong", "fixed")
REVIEW_KINDS = ("sample", "off_centre", "roofless", "street_overlap")
MAX_REVIEW_NOTE = 1000


class _Cached:
    """A JSON file read again when it changes."""

    def __init__(self, path):
        self.path = path
        self._stamp = None
        self._data = None

    def get(self):
        try:
            stamp = os.stat(self.path).st_mtime_ns
        except OSError:
            self._stamp = self._data = None
            return None
        if stamp != self._stamp:
            with open(self.path) as handle:
                self._data = json.load(handle)
            self._stamp = stamp
            self._prepare()
        return self._data

    def _prepare(self):
        pass


class Routes(_Cached):
    """alignments.json by route, with each route's bounding box."""

    def __init__(self, path=ALIGNMENTS_PATH, templates_path=TEMPLATES_PATH, overrides_path=ho.OVERRIDES_PATH):
        super().__init__(path)
        self.templates = _Cached(templates_path)
        self.overrides_path = overrides_path
        self.by_id = {}
        self.bbox = {}

    def _prepare(self):
        self.by_id = {r["id"]: r for r in self._data["routes"]}
        self.junction_stas = {}
        for j in self._data.get("junctions", []):
            for leg in j["legs"]:
                self.junction_stas.setdefault(leg["route"], set()).add(round(leg["sta"], 1))
        self.bbox = {}
        for r in self._data["routes"]:
            pts = r["pis"] + r.get("osm", [])
            xs, zs = [p[0] for p in pts], [p[1] for p in pts]
            self.bbox[r["id"]] = (min(xs), min(zs), max(xs), max(zs))

    def _overrides(self):
        try:
            return ho.pins_by_route(ho.load(self.overrides_path))
        except (OSError, ValueError, KeyError):
            return {}

    def summaries(self):
        """One short record per route, for the picker."""
        if self.get() is None:
            raise FileNotFoundError("no alignments.json (run pipeline/roads/build_alignments.py)")
        pins = self._overrides()
        out = []
        for r in self._data["routes"]:
            out.append({"id": r["id"], "name": r.get("name"), "class": r["class"], "highway": r["highway"],
                        "length": r["length"], "bbox": [round(v, 1) for v in self.bbox[r["id"]]],
                        "pinned": bool(r.get("pinned")), "override": r["id"] in pins,
                        "deviation_max_m": r["deviation"]["max_m"]})
        return out

    def unpublished(self):
        """Whether alignment_overrides.json was saved after alignments.json was last built."""
        try:
            return os.path.getmtime(self.overrides_path) > os.path.getmtime(self.path)
        except OSError:
            return False

    def view(self, rid, pins=None):
        """The editor's record of one route (None if unknown)."""
        if self.get() is None:
            raise FileNotFoundError("no alignments.json (run pipeline/roads/build_alignments.py)")
        r = self.by_id.get(rid)
        if r is None:
            return None
        pins = self._overrides() if pins is None else pins
        templ = (self.templates.get() or {}).get("routes", {}).get(rid, [])
        out = {k: r[k] for k in ("id", "name", "class", "highway", "oneway", "closed", "length", "pis", "radii",
                                 "elements", "deviation") if k in r}
        out["osm"] = r.get("osm", [])
        out["pinned"] = r.get("pinned", [])
        out["ranges"] = [{"sta": t["sta"], "curb_to_curb_m": t["curb_to_curb_m"], "section": t["section"],
                          "bridge": t["bridge"]} for t in templ]
        out["bridges"] = r.get("bridges", [])
        out["junctions"] = sorted(self.junction_stas.get(rid, ()))     # stations where other streets meet it
        out["width"] = {k: v for k, v in r.get("width", {}).items() if k != "block_detail"}
        try:
            out["width_pins"] = ho.width_pins(ho.load(self.overrides_path), rid)
        except (OSError, ValueError):
            out["width_pins"] = []
        saved = pins.get(rid)
        if saved:    # written to alignment_overrides.json since the last build_alignments run
            out["override"] = saved[-1]
        return out

    def in_box(self, x0, z0, x1, z1):
        if self.get() is None:
            raise FileNotFoundError("no alignments.json (run pipeline/roads/build_alignments.py)")
        pins = self._overrides()
        ids = [rid for rid, (a, b, c, d) in self.bbox.items() if a <= x1 and c >= x0 and b <= z1 and d >= z0]
        return [self.view(rid, pins) for rid in sorted(ids)]

    def nearest(self, x, z, within=40.0):
        """The id of the route whose OSM line or alignment passes closest to (x, z), or None."""
        best = None
        if self.get() is None:
            return None
        for rid, r in self.by_id.items():
            a, b, c, d = self.bbox[rid]
            if x < a - within or x > c + within or z < b - within or z > d + within:
                continue
            pts = r.get("osm") or r["pis"]
            for p, q in zip(pts, pts[1:]):
                dist = _seg_dist(x, z, p, q)
                if best is None or dist < best[0]:
                    best = (dist, rid)
        return best[1] if best and best[0] <= within else None


def _seg_dist(x, z, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dz * dz
    t = 0.0 if l2 < 1e-12 else min(1.0, max(0.0, ((x - a[0]) * dx + (z - a[1]) * dz) / l2))
    return math.hypot(x - a[0] - t * dx, z - a[1] - t * dz)


# ---------------------------------------------------------------------------------------------
# Review queue and store
# ---------------------------------------------------------------------------------------------
def _read(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def load_review(path=REVIEW_PATH):
    doc = _read(path)
    if not isinstance(doc, dict) or doc.get("format") != "dixon-alignment-review":
        return {"format": "dixon-alignment-review", "version": 1, "items": {}}
    doc.setdefault("items", {})
    return doc


def save_review(body, path=REVIEW_PATH, today=None):
    """Records (or, with status "", clears) the reviewer's verdict on one place. Returns the item."""
    try:
        data = json.loads(body) if isinstance(body, (bytes, str)) else body
    except ValueError:
        raise ValueError("not JSON")
    if not isinstance(data, dict):
        raise ValueError("expected an object")
    rid = data.get("id")
    if not isinstance(rid, str) or not REVIEW_ID.match(rid):
        raise ValueError("bad id")
    status = data.get("status", "")
    if status not in REVIEW_STATUS + ("",):
        raise ValueError("status is ok, wrong or fixed")
    note = data.get("note", "")
    if not isinstance(note, str) or len(note) > MAX_REVIEW_NOTE:
        raise ValueError("bad note")
    doc = load_review(path)
    if status == "":
        doc["items"].pop(rid, None)
        item = None
    else:
        item = {"status": status, "note": note.strip()}
        kind = data.get("kind")
        if kind is not None:
            if kind not in REVIEW_KINDS:
                raise ValueError("bad kind")
            item["kind"] = kind
        if isinstance(data.get("route"), str) and ho.ROUTE_ID.match(data["route"]):
            item["route"] = data["route"]
        at = data.get("at")
        if at is not None:
            if not (isinstance(at, list) and len(at) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in at)):
                raise ValueError("at is [x, z]")
            item["at"] = [round(float(at[0]), 1), round(float(at[1]), 1)]
        sta = data.get("sta")
        if sta is not None:
            if not (isinstance(sta, list) and len(sta) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in sta)):
                raise ValueError("sta is [from, to]")
            item["sta"] = [round(float(sta[0]), 1), round(float(sta[1]), 1)]
        item["reviewed"] = (today or datetime.date.today()).isoformat()
        doc["items"][rid] = item
    doc["items"] = dict(sorted(doc["items"].items()))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(handle, "w") as out:
        json.dump(doc, out, indent=1)
        out.write("\n")
    os.chmod(temp, 0o644)
    os.replace(temp, path)
    return item


def _block_places(routes):
    """Every surveyed street block: (route id, name, [s0, s1], centre point, counted)."""
    out = []
    for r in routes:
        for b in r.get("width", {}).get("block_detail", []):
            s0, s1 = b["sta"]
            x, z, _ = geom.point_at(geom.load_elements(r["elements"]), r["length"], r["pis"][-1], 0.5 * (s0 + s1))
            out.append((r["id"], r.get("name"), [s0, s1], (x, z), bool(b.get("counts"))))
    return out


def build_queue(routes_doc, report=None, audit_dir=AUDIT_DIR, sample=25, seed=1, kinds=REVIEW_KINDS,
                review_path=REVIEW_PATH):
    """The places to check: [{id, kind, at, route?, sta?, label, why, result?}, ...] and notes.

    `sample` surveyed street blocks drawn at random with `seed` (the same seed draws the same
    blocks while alignments.json is unchanged), then every flagged place of the kinds asked for."""
    items, notes = [], []
    if "sample" in kinds and sample > 0:
        blocks = sorted(_block_places(routes_doc["routes"]), key=lambda b: (b[0], b[2][0]))
        for rid, name, sta, at, counted in random.Random(seed).sample(blocks, min(sample, len(blocks))):
            items.append({"id": "block:%s:%d-%d" % (rid, round(sta[0]), round(sta[1])), "kind": "sample",
                          "route": rid, "sta": sta, "at": [round(at[0], 1), round(at[1], 1)],
                          "label": "%s, block %d-%d m" % (name or rid, round(sta[0]), round(sta[1])),
                          "why": "random street block" + ("" if counted else " (aerial width not counted here)")})
    if "off_centre" in kinds:
        flagged = routes_doc.get("off_centre_blocks")
        if flagged is None:
            flagged = (report or {}).get("off_centre_blocks")
        if flagged is None:
            notes.append("no off-centre list (run build_alignments.py): off-centre blocks not listed")
        for b in flagged or []:
            items.append({"id": "offc:%s:%d" % (b["route"], round(b["sta"][0])), "kind": "off_centre",
                          "route": b["route"], "sta": b["sta"], "at": b["at"],
                          "label": "%s, block %d-%d m" % (b.get("name") or b["route"], round(b["sta"][0]), round(b["sta"][1])),
                          "why": "pavement centre %+.1f m off the alignment" % b["centre_m"]})
    if "roofless" in kinds:
        doc = _read(os.path.join(audit_dir, "roofless_review.json"))
        if doc is None:
            notes.append("no roofless_review.json")
        for b in (doc or {}).get("flagged", []):
            items.append({"id": "roofless:%s" % b["id"], "kind": "roofless", "at": b["at"],
                          "label": "building %s (%s)" % (b["id"], b["source"]),
                          "why": "footprint looks %s on the aerial (%.0f m²)" % (b.get("why", "roofless"), b.get("area_m2", 0))})
    if "street_overlap" in kinds:
        doc = _read(os.path.join(audit_dir, "street_overlaps.json"))
        if doc is None:
            notes.append("no street_overlaps.json")
        for b in (doc or {}).get("manual_review", []) + (doc or {}).get("buildings", []):
            street = b.get("street") or {}
            items.append({"id": "overlap:%s" % b["id"], "kind": "street_overlap", "at": b["at"],
                          **({"route": street["route"]} if street.get("route") else {}),
                          "label": "building %s on %s" % (b["id"], street.get("name") or "a street"),
                          "why": b.get("look_at") or "footprint meets the carriageway (%.1f m²)" % b.get("on_carriageway_m2", 0)})
    seen = set()
    items = [i for i in items if not (i["id"] in seen or seen.add(i["id"]))]
    done = load_review(review_path)["items"]
    for i in items:
        if i["id"] in done:
            i["result"] = done[i["id"]]
    return items, notes
