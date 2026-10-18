#!/usr/bin/env bash
# Rebuild what a change in Bridge Composer needs, then bake the road scene the game loads:
#   the heightmap (roads that end at a composed bridge are conformed to its deck),
#   the road plan (builds the composed bridges, leaves out removed ones),
#   the baked scene (roads.tscn / roads.scn).
# The server runs this for the editor's "Rebuild game" button (game/tools/composer_server.py).
# It does not refresh the terrain splat or vegetation: pipeline/roads/rebuild_transportation.sh does.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
echo "== 1/3 heightmap"
(cd "$ROOT/pipeline" && "$PYTHON" -u build_heightmap.py)
echo "== 2/3 road plan (about 3 minutes)"
(cd "$ROOT/pipeline/roads" && "$PYTHON" -u build_road_plan.py)
echo "== 3/3 bake roads"
bash "$ROOT/game/roads/tools/build_roads.sh"
echo "== done"
