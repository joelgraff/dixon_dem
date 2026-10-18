#!/usr/bin/env python3
"""Rebuilds just the bridges: the fast path for an edit in Bridge Composer.

  cd pipeline/roads && ../../.venv/bin/python build_bridges_only.py
  game/roads/tools/build_roads.sh --bridges

Bridges are their own baked layer (game/roads/_build_bridges -> res://roads/bridges.scn), apart from
the roads, so a change to a deck, railing, pier or cross-section does not need the road layout
rebuilt (about 3 minutes). It does when approach heights change: the roads and the ground under
them follow the deck's ends, so then run pipeline/roads/rebuild_bridges.sh (full).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_road_plan as brp  # noqa: E402


def main():
    t0 = time.time()
    bridges = brp.load_json("bridges.json")["bridges"]
    hm = brp.Heightmap()
    mb_by_mat, furniture = {}, {}
    brp.build_bridges(bridges, hm, mb_by_mat, furniture)
    brp.write_output(mb_by_mat, furniture, brp.BRIDGE_OUT_DIR)
    print(f"bridges rebuilt in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
