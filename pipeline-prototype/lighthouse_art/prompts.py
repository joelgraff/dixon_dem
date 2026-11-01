"""Generate concise, scene-specific prompts for external image-generation tools."""

from __future__ import annotations

from .palette import DEFAULT_PALETTE, PALETTES, TARGET_SIZE, hex_color
from lighthouse_parser.scene_card import SceneCard

STYLE_PROMPT = (
    "Create an original, hand-crafted 1980s-era PC adventure-game background "
    f"as low-resolution pixel art. Compose for a {TARGET_SIZE[0]}x{TARGET_SIZE[1]} "
    "(16:10) screen and "
    "a fixed, straight-on room view. Use chunky, intentional pixel clusters, "
    "hard pixel edges, strong silhouettes, and restrained checkerboard and "
    "cluster dithering for value transitions. Limit the image to the "
    "{palette_label} palette listed below; prioritize readable shapes over tiny detail. "
    "Use a moody night-time palette with deep blue shadows, cool grays, and "
    "small warm lantern highlights. No characters."
)

EXTENDED_PALETTE_NOTE = (
    "The extra mid-tones let you build smooth sky, water, and lamplight "
    "gradients from adjacent palette colors with light dithering; do not "
    "use any color outside the list."
)

NEGATIVE_PROMPT = (
    "photorealism, 3D render, modern smooth vector art, anti-aliased edges, "
    "soft focus, gradients without dithering, high-frequency noise, tiny "
    "indistinct objects, text, letters, logos, interface, frame, border, "
    "character, modern equipment, extra furniture, duplicated objects"
)


def build_prompt(scene: SceneCard, palette_key: str = DEFAULT_PALETTE) -> str:
    selected = PALETTES[palette_key]
    colors = ", ".join(
        f"{name} {hex_color(rgb)}" for name, rgb in selected.colors
    )
    note = f"{EXTENDED_PALETTE_NOTE}\n" if len(selected.colors) > 16 else ""
    return (
        f"{STYLE_PROMPT.format(palette_label=selected.label)}\n\n"
        f"Scene: {scene.location}\n"
        f"Composition: {scene.background_description}\n"
        f"Palette ({len(selected.colors)} exact target colors): {colors}\n"
        f"{note}\n"
        "Negative prompt:\n"
        f"{NEGATIVE_PROMPT}\n\n"
        "The prompt guides generation; the local processing step will resize "
        "and enforce the exact palette."
    )
