"""Hand corrections to OSM road geometry, checked against the 2025 aerial (osm_corrections.json).

Where OSM draws a street off its pavement and the alignment fit cannot recover it (the fit is
held to OSM within a tolerance), the correction belongs in the data every consumer reads.
build_vectors.py applies these when it writes roads.json; running this module applies them to
the roads.json on disk. Both are idempotent: a correction
states where a node or a run of vertices should be, not how far to move it.

  nodes: {node id: {"x", "z", "note"}}                move a node, in every way that uses it
  ways:  {way id: {"between": [node a, node b],        replace the vertices strictly between two
                   "points": [[x, z], ...], "note"}}   of the way's nodes, the points listed from a to b

Coordinates are game metres (x east, z south). A moved node keeps its height (it moves metres
along its street); an inserted vertex takes its height by linear interpolation from the way's
other vertices, so the heights the rest of roads.json carries are untouched. junction_nodes is
updated for moved nodes.

Run: .venv/bin/python pipeline/osm_corrections.py   (applies to game/data/roads.json in place)
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORRECTIONS_PATH = os.path.join(HERE, "osm_corrections.json")
ROADS_PATH = os.path.join(HERE, "..", "game", "data", "roads.json")


def load(path=CORRECTIONS_PATH):
    if not os.path.exists(path):
        return {"nodes": {}, "ways": {}}
    with open(path) as handle:
        data = json.load(handle)
    if data.get("format") != "dixon-osm-corrections":
        raise ValueError(f"{path}: not a dixon-osm-corrections file")
    return data


def _heights(vertices):
    """Interpolates each vertex without a height (y None) from its neighbours by arc length."""
    known = [i for i, v in enumerate(vertices) if v.get("y") is not None]
    if not known:
        return vertices
    cum = [0.0]
    for a, b in zip(vertices, vertices[1:]):
        cum.append(cum[-1] + math.hypot(b["x"] - a["x"], b["z"] - a["z"]))
    for i, v in enumerate(vertices):
        if v.get("y") is not None:
            continue
        lo = max([k for k in known if k < i], default=None)
        hi = min([k for k in known if k > i], default=None)
        if lo is None or hi is None:
            v["y"] = vertices[lo if hi is None else hi]["y"]
        else:
            t = (cum[i] - cum[lo]) / max(cum[hi] - cum[lo], 1e-9)
            v["y"] = round(vertices[lo]["y"] + (vertices[hi]["y"] - vertices[lo]["y"]) * t, 2)
    return vertices


def apply(roads, corrections=None):
    """roads.json's dict with the corrections applied, in place. Returns a list of what was done."""
    corrections = load() if corrections is None else corrections
    done = []
    nodes = {int(k): v for k, v in corrections.get("nodes", {}).items() if not k.startswith("_")}
    ways = {int(k): v for k, v in corrections.get("ways", {}).items() if not k.startswith("_")}
    for w in roads["ways"]:
        vs = w["vertices"]
        changed = False
        rule = ways.get(w["id"])
        if rule:
            ids = [v.get("node_id") for v in vs]
            a, b = rule["between"]
            if a in ids and b in ids:
                i, j = sorted((ids.index(a), ids.index(b)))
                pts = rule["points"] if ids.index(a) < ids.index(b) else rule["points"][::-1]
                vs[i + 1:j] = [{"x": float(x), "y": None, "z": float(z), "node_id": None} for x, z in pts]
                changed = True
                done.append(f"way {w['id']}: {len(pts)} vertices between nodes {a} and {b}")
            else:
                done.append(f"way {w['id']}: nodes {a}, {b} not found; skipped")
        for v in vs:
            move = nodes.get(v.get("node_id"))
            if move and (v["x"], v["z"]) != (move["x"], move["z"]):
                v["x"], v["z"] = float(move["x"]), float(move["z"])
                changed = True
        if changed:
            _heights(vs)
            w.setdefault("corrected", True)
    for j in roads.get("junction_nodes", []):
        move = nodes.get(j.get("node_id"))
        if move:
            j["x"], j["z"] = float(move["x"]), float(move["z"])
    for nid in nodes:
        done.append(f"node {nid} moved")
    return done


def main():
    with open(ROADS_PATH) as handle:
        roads = json.load(handle)
    for line in apply(roads):
        print(" ", line)
    with open(ROADS_PATH, "w") as handle:
        json.dump(roads, handle)
    print(f"wrote {os.path.normpath(ROADS_PATH)}")


if __name__ == "__main__":
    sys.exit(main())
