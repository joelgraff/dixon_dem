#!/usr/bin/env bash
# Bakes res://roads/roads.tscn from pipeline/roads/build_road_plan.py's JSON
# output (game/roads/_build/). Re-run after regenerating that data.
#   cd pipeline/roads && ../../.venv/bin/python build_road_plan.py
#   game/roads/tools/build_roads.sh
set -euo pipefail
GODOT="${GODOT:-$HOME/AppImage/Godot_v4.6-stable_linux.x86_64}"
PROJ="$(cd "$(dirname "$0")/../.." && pwd)"
"$GODOT" --headless --path "$PROJ" res://roads/tools/build_roads.tscn
