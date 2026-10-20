#!/usr/bin/env bash
# Rebuild what a change in Bridge Composer needs, so the game shows it.
#   rebuild_bridges.sh fast   bridges only, ~15 seconds: a change to a deck, railing, pier, span,
#                             cross-section, material, a removed or restored bridge, a drawn bridge.
#   rebuild_bridges.sh full   (default) ~5 minutes: also the heightmap and the road plan, needed when
#                             a deck's END heights change (the roads and the ground under the
#                             approaches follow them), or the bridge has roads ending at it.
#   rebuild_bridges.sh alignments   after a change to alignment_overrides.json's `horizontal` (the
#                             Alignments mode of Bridge Composer): build_alignments.py (about 3 minutes, with the
#                             aerial width survey), then pipeline/roads/rebuild_transportation.sh (templates,
#                             heightmap, road plan, splat, vegetation, import, bake), then the bridge bake.
#                             About 15 minutes in all.
# The server runs this for the editor's rebuild buttons (game/tools/composer_server.py).
# Neither mode refreshes the terrain splat or vegetation: pipeline/roads/rebuild_transportation.sh does.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
MODE="${1:-full}"
if [ "$MODE" = "alignments" ]; then
  echo "== 1/3 alignments (about 3 minutes)"
  (cd "$ROOT/pipeline/roads" && "$PYTHON" -u build_alignments.py)
  echo "== 2/3 transportation (templates, heightmap, road plan, splat, vegetation, bake)"
  bash "$ROOT/pipeline/roads/rebuild_transportation.sh"
  echo "== 3/3 bake bridges"
  bash "$ROOT/game/roads/tools/build_roads.sh" --bridges
elif [ "$MODE" = "fast" ]; then
  echo "== 1/2 bridges"
  (cd "$ROOT/pipeline/roads" && "$PYTHON" -u build_bridges_only.py)
  echo "== 2/2 bake bridges"
  bash "$ROOT/game/roads/tools/build_roads.sh" --bridges
else
  echo "== 1/4 heightmap"
  (cd "$ROOT/pipeline" && "$PYTHON" -u build_heightmap.py)
  echo "== 2/4 road plan (about 3 minutes)"
  (cd "$ROOT/pipeline/roads" && "$PYTHON" -u build_road_plan.py)
  echo "== 3/4 bake roads"
  bash "$ROOT/game/roads/tools/build_roads.sh"
  echo "== 4/4 bake bridges"
  bash "$ROOT/game/roads/tools/build_roads.sh" --bridges
fi
echo "== done"
