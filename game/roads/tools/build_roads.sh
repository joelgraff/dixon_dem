#!/usr/bin/env bash
# Bakes res://roads/roads.tscn and roads.scn from pipeline/roads/build_road_plan.py's JSON
# output (game/roads/_build/). Re-run after regenerating that data.
#   cd pipeline/roads && ../../.venv/bin/python build_road_plan.py
#   game/roads/tools/build_roads.sh            # the roads
#   game/roads/tools/build_roads.sh --bridges  # the bridges, a separate layer
set -euo pipefail
GODOT="${GODOT:-$HOME/AppImage/Godot_v4.6-stable_linux.x86_64}"
PROJ="$(cd "$(dirname "$0")/../.." && pwd)"
# --bridges bakes the bridge layer (res://roads/bridges.scn) alone, in seconds
if [ "${1:-}" = "--bridges" ]; then
  "$GODOT" --headless --path "$PROJ" res://roads/tools/build_roads.tscn -- --bridges
else
  "$GODOT" --headless --path "$PROJ" res://roads/tools/build_roads.tscn
fi
