extends Node3D
## Standalone player-controller test scene: instances atmosphere.tscn
## (lighting/sky/weather rig) + terrain.tscn (something to walk on) +
## player.tscn, so the FPS controller can be driven and reviewed in
## isolation. Captured via game/tools/capture.sh like any other scene --
## the capture harness adds/overrides its own Camera3D and sets
## capture_mode, which player.gd already respects (see player.gd's
## capture-mode contract docstring).

func _ready() -> void:
	if ResourceLoader.exists("res://atmosphere/atmosphere.tscn"):
		add_child((load("res://atmosphere/atmosphere.tscn") as PackedScene).instantiate())

	add_child((load("res://terrain/terrain.tscn") as PackedScene).instantiate())
	add_child((load("res://player/player.tscn") as PackedScene).instantiate())
