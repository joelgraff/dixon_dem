class_name LandmarkMaterials
extends RefCounted
## Material helpers for the landmarks builder. Everything here either (a)
## duplicates a FROZEN shared-library ShaderMaterial (game/materials/lib/*.tres)
## and tweaks shader_parameter/* -- same pattern materials_notes.md documents
## ("duplicate the .tres, edit albedo_tint") except done in-memory at build
## time instead of as checked-in .tres files, since each landmark instance
## needs its own `ground_level` (world-space Y of local grade) for the
## grime/wear response to land in the right place -- or (b) builds a small
## unshaded/emissive StandardMaterial3D for a baked signage texture (see
## pipeline/landmarks/gen_signage.py), or (c) a tiny custom foam shader for
## the dam spillway (own shader budget, per buildings' precedent -- materials/
## atmosphere themselves are untouched).

const LIB := "res://materials/lib/"
const TEX := "res://landmarks/textures/"

static var _cache: Dictionary = {}

static func _load(path: String) -> Resource:
	if not _cache.has(path):
		_cache[path] = load(path)
	return _cache[path]

## Duplicate a shared-library material and override common params. `overrides`
## is a Dictionary of shader_parameter name (without the prefix) -> value.
static func tinted(base_name: String, ground_y: float, overrides: Dictionary = {}) -> ShaderMaterial:
	var base: ShaderMaterial = _load(LIB + base_name + ".tres")
	var mat: ShaderMaterial = base.duplicate(true)
	mat.set_shader_parameter("ground_level", ground_y)
	for k in overrides.keys():
		mat.set_shader_parameter(k, overrides[k])
	return mat

## Convenience for a small-pattern "flat color" surface (statue bronze,
## granite, dark iron, painted trim) -- picks a fine-grained base texture and
## shrinks uv_scale so the source photo's pattern all but disappears, while
## still getting real PBR response + snow/wet/grime for free from the shared
## shader. `uv_scale` stays a Vector2 param on the base material.
static func flat_color(base_name: String, tint: Color, ground_y: float, mult: float = 1.0, ov: Dictionary = {}) -> ShaderMaterial:
	var merged := {"albedo_tint": tint, "albedo_multiplier": mult, "uv_scale": Vector2(0.12, 0.12), "macro_variation_strength": 0.05}
	for k in ov.keys():
		merged[k] = ov[k]
	return tinted(base_name, ground_y, merged)

## Unshaded/emissive quad material for a baked signage texture.
static func signage(tex_name: String, emissive: bool = false, emission_color: Color = Color(1, 1, 1), energy: float = 1.0) -> StandardMaterial3D:
	var mat := StandardMaterial3D.new()
	var tex: Texture2D = _load(TEX + tex_name)
	mat.albedo_texture = tex
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	if emissive:
		mat.emission_enabled = true
		mat.emission = emission_color
		mat.emission_texture = tex
		mat.emission_energy_multiplier = energy
	return mat

## Plain unshaded flat-color StandardMaterial3D (glass panes' dark frame trim,
## small props where the full surface.gdshader machinery is overkill).
static func flat_unshaded(color: Color, roughness: float = 0.6) -> StandardMaterial3D:
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	mat.roughness = roughness
	return mat

static var _foam_shader: Shader

## Cheap scrolling-noise unlit white foam plane for the dam spillway curtain
## (per docs/references/dixon_dam.md: "use a scrolling/foam shader rather
## than complex geometry"). Reuses materials' own noise include per
## materials_notes.md ("reusing the includes elsewhere").
static func foam() -> ShaderMaterial:
	if _foam_shader == null:
		_foam_shader = load("res://landmarks/shaders/foam.gdshader")
	var mat := ShaderMaterial.new()
	mat.shader = _foam_shader
	return mat

static func window_glass(ground_y: float, pane_scale: Vector2 = Vector2(1, 1)) -> ShaderMaterial:
	return tinted("window_glass", ground_y, {"pane_scale": pane_scale})
