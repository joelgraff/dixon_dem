#!/bin/sh
# Template resolver, the building pipeline's Composer round trip, and the
# in-game help and building-editor functions.
#
# Sets itself up: creates .venv/ from requirements.txt when it is missing, or
# reinstalls when requirements.txt has changed since. Godot comes from $GODOT,
# then godot4 or godot on PATH, then ~/AppImage/Godot_v4.6-stable_linux.x86_64;
# without one the in-game checks are skipped (REQUIRE_GODOT=1 makes that fail).
set -e
root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
venv="$root/.venv"
python="$venv/bin/python"
stamp="$venv/.requirements.sha256"
want=$(sha256sum "$root/requirements.txt" | cut -d' ' -f1)

if [ ! -x "$python" ] || [ "$(cat "$stamp" 2>/dev/null)" != "$want" ]; then
	echo "Setting up $venv from requirements.txt..."
	[ -x "$python" ] || python3 -m venv "$venv"
	"$python" -m pip install --quiet --upgrade pip
	"$python" -m pip install --quiet -r "$root/requirements.txt"
	echo "$want" > "$stamp"
fi

for test in test_templates test_composer test_composed test_palette test_footprints test_porch_legs; do
	echo "== $test"
	"$python" "$root/pipeline/buildings/$test.py"
done

godot=${GODOT:-}
if [ -z "$godot" ]; then
	for candidate in godot4 godot "$HOME/AppImage/Godot_v4.6-stable_linux.x86_64"; do
		if command -v "$candidate" >/dev/null 2>&1; then
			godot=$(command -v "$candidate")
			break
		fi
	done
fi
if [ -z "$godot" ]; then
	echo "== tools_selftest: SKIPPED, no Godot (set GODOT to its binary)"
	[ "${REQUIRE_GODOT:-0}" = "1" ] && exit 1
	exit 0
fi
echo "== tools_selftest ($godot)"
"$godot" --headless --path "$root/game" res://tools/tools_selftest.tscn
