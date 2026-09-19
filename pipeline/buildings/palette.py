"""Material palette + approximate linear-ish preview colors (for HLOD vertex
tint and awning/sign colors) for the buildings workstream. Resource paths are
embedded in the build-plan manifest so game/buildings/tools/build_buildings.gd
never needs its own hardcoded material list. See docs/buildings_notes.md.
"""

MATERIALS = {
    "brick_red": "res://materials/lib/brick_red.tres",
    "brick_buff": "res://materials/lib/brick_buff.tres",
    "brick_rose": "res://buildings/materials/brick_rose.tres",
    "brick_dark": "res://buildings/materials/brick_dark.tres",
    "brick_cream": "res://buildings/materials/brick_cream.tres",
    "siding_white": "res://materials/lib/siding_white.tres",
    "siding_sage": "res://materials/lib/siding_sage.tres",
    "siding_blue": "res://buildings/materials/siding_blue.tres",
    "siding_butter": "res://buildings/materials/siding_butter.tres",
    "siding_gray": "res://buildings/materials/siding_gray.tres",
    "limestone": "res://materials/lib/limestone.tres",
    "stone_foundation": "res://materials/lib/stone_foundation.tres",
    "roof_metal": "res://materials/lib/roof_metal.tres",
    "roof_membrane": "res://materials/lib/roof_membrane.tres",
    "shingles_dark": "res://materials/lib/shingles_dark.tres",
    "shingles_brown": "res://buildings/materials/shingles_brown.tres",
    "steel_rusted": "res://materials/lib/steel_rusted.tres",
    "trim_dark": "res://buildings/materials/trim_dark.tres",
    "window_lit": "res://buildings/materials/window_lit.tres",
    "awning": "res://buildings/materials/awning.tres",
}

# HLOD far-mesh / prop tint approximations (linear-ish 0-1 RGB), also used to
# pick plausible awning/sign accent colors per building.
APPROX_COLOR = {
    "brick_red": (0.60, 0.36, 0.27),
    "brick_rose": (0.63, 0.40, 0.32),
    "brick_dark": (0.47, 0.36, 0.30),
    "brick_buff": (0.77, 0.66, 0.47),
    "brick_cream": (0.80, 0.71, 0.55),
    "siding_white": (0.90, 0.88, 0.83),
    "siding_sage": (0.60, 0.65, 0.56),
    "siding_blue": (0.75, 0.80, 0.82),
    "siding_butter": (0.82, 0.78, 0.70),
    "siding_gray": (0.75, 0.75, 0.75),
    "limestone": (0.80, 0.78, 0.70),
    "stone_foundation": (0.55, 0.53, 0.48),
    "roof_metal": (0.55, 0.55, 0.58),
    "roof_membrane": (0.55, 0.50, 0.42),
    "shingles_dark": (0.40, 0.38, 0.36),
    "shingles_brown": (0.50, 0.41, 0.34),
    "steel_rusted": (0.45, 0.32, 0.26),
    "trim_dark": (0.16, 0.14, 0.12),
}

# Weighted toward the real Midwest vernacular (docs/references/dixon_vernacular.md):
# red-brown/buff brick dominates downtown, white/muted-gray siding dominates
# residential streets -- pastel accents (blue/butter/sage) stay rare accents,
# not a random rainbow (coordinator composed-frame review, 2026-09-19: pastel
# blue/yellow/pink variety was reading too saturated/random at distance).
BRICK_KEYS = ["brick_red", "brick_red", "brick_red", "brick_buff", "brick_buff",
              "brick_dark", "brick_rose", "brick_cream"]
CIVIC_BRICK_KEYS = ["brick_buff", "brick_buff", "brick_cream", "brick_red"]
SIDING_KEYS = ["siding_white", "siding_white", "siding_white", "siding_white",
               "siding_gray", "siding_gray", "siding_sage", "siding_blue", "siding_butter"]
SHINGLE_KEYS = ["shingles_dark", "shingles_dark", "shingles_brown"]

AWNING_COLORS = [
    (0.16, 0.35, 0.20),  # green
    (0.55, 0.10, 0.10),  # deep red
    (0.55, 0.42, 0.10),  # mustard
    (0.15, 0.20, 0.42),  # navy
    (0.35, 0.35, 0.35),  # charcoal
]
