"""Build one composed building without loading the rest of the city.

    python compose_one.py spec.json out.json

spec.json: {"id", "ground_y", "compose" or "preset", "op": {"key", "dir"}}
out.json: {"compose", "summary", "near", "far"}
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import composer  # noqa: E402

GAME_DATA = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "game", "data"))


def _footprint(bid):
    wanted = str(bid)
    names = ("buildings.json", "buildings_ms.json", "buildings_curated.json")
    for name in names:
        path = os.path.join(GAME_DATA, name)
        if not os.path.exists(path):
            continue
        payload = json.load(open(path))
        rows = payload.get("buildings", payload if isinstance(payload, list) else [])
        for row in rows:
            if str(row.get("id")) != wanted:
                continue
            ring = row.get("footprint") or row.get("coords") or []
            return [(p["x"], p["z"]) if isinstance(p, dict) else (p[0], p[1]) for p in ring]
    return None


def main():
    spec = json.load(open(sys.argv[1]))
    record = spec.get("compose") or composer.preset(spec.get("preset") or "block")
    op = spec.get("op") or {}
    if op.get("key"):
        record = composer.mutate(record, op["key"], int(op.get("dir") or 1))
    ring = _footprint(spec["id"])
    if not ring or len(ring) < 3:
        print("no footprint for %s" % spec.get("id"), file=sys.stderr)
        return 2
    from common_buildings import MeshBuild
    near, far = MeshBuild(), MeshBuild()
    if spec.get("flip_normals"):
        near.set_flip_outward(True)
        far.set_flip_outward(True)
    composer.build(near, far, ring, float(spec.get("ground_y") or 0.0), record)
    json.dump({
        "compose": record,
        "summary": composer.summary(record),
        "near": near.to_json(),
        "far": far.to_json(),
    }, open(sys.argv[2], "w"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
