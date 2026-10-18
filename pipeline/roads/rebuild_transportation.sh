#!/usr/bin/env bash
# Rebuild the shared layout and every consumer, then bake the live road scene.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
"$PYTHON" -u "$ROOT/pipeline/roads/build_road_plan.py"
"$PYTHON" -u "$ROOT/pipeline/terrain/bake_splat.py"
"$PYTHON" -u "$ROOT/pipeline/vegetation/place_vegetation.py"
"${GODOT:-$HOME/AppImage/Godot_v4.6-stable_linux.x86_64}" --headless --editor --path "$ROOT/game" --import
bash "$ROOT/game/roads/tools/build_roads.sh"
