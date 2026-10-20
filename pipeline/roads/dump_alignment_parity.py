#!/usr/bin/env python3
"""Fixtures holding Bridge Composer's js/alignment.js to alignment_geom.py (the construction).

Writes ../../../bridge-composer/tests/fixtures/alignment_parity.json (or the path given): a
few hand-made and many seeded random PI chains with the elements, stations and points the
Python makes. Regenerate whenever alignment_geom.py's maths changes.
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import alignment_geom as geom  # noqa: E402

DEFAULT = os.path.join(HERE, "..", "..", "..", "bridge-composer", "tests", "fixtures", "alignment_parity.json")


def case(name, pis, radii):
    pis = [[float(x), float(z)] for x, z in pis]
    radii = [float(r) for r in radii]
    radii[0] = radii[-1] = 0.0
    els, overlaps, length, pi_sta = geom.build([tuple(p) for p in pis], radii)
    stas = [length * k / 12 for k in range(13)]
    pts = [list(geom.point_at(els, length, tuple(pis[-1]), s)[:2]) for s in stas]
    out_els = []
    for e in els:
        row = {"type": e["type"], "sta": list(e["sta"]), "start": list(e["start"]), "end": list(e["end"])}
        if e["type"] == "arc":
            row.update(center=list(e["center"]), radius=e["radius"], delta=e["delta"], pi=e["pi"])
        out_els.append(row)
    return {"name": name, "pis": pis, "radii": radii, "elements": out_els, "overlaps": overlaps, "length": length,
            "pi_sta": [list(s) for s in pi_sta], "stations": stas, "points": pts}


def main(path):
    cases = [case("one right curve", [(0, 0), (100, 0), (100, 100)], [0, 30, 0]),
             case("one left curve", [(0, 0), (100, 0), (100, -100)], [0, 30, 0]),
             case("s-bend", [(0, 0), (100, 0), (150, 80), (250, 80)], [0, 40, 40, 0]),
             case("angle point", [(0, 0), (50, 0), (50, 50)], [0, 0, 0]),
             case("overlap", [(0, 0), (100, 0), (100, 20), (200, 20)], [0, 40, 40, 0]),
             case("two points", [(3, 4), (30, -40)], [0, 0])]
    rng = random.Random(11)
    for k in range(40):
        n = rng.randint(3, 7)
        pis = [(rng.uniform(0, 300), rng.uniform(0, 300)) for _ in range(n)]
        radii = [0] + [rng.choice([0, 8, 25, 60, 150]) for _ in range(n - 2)] + [0]
        cases.append(case("random %d" % k, pis, radii))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as handle:
        json.dump({"cases": cases}, handle)
    print("wrote %d cases to %s" % (len(cases), os.path.normpath(path)))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
