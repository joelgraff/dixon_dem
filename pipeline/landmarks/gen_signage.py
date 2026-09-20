#!/usr/bin/env python3
"""Landmarks workstream: generate small signage/decal textures with Pillow.

Per BUILDER_PROTOCOL/brief: "Signage/lettering can be texture or simple
extruded geometry." Rather than extrude readable letterforms (expensive,
fiddly at mid-poly), these are baked once here as transparent-background
PNGs and applied as unshaded/emissive quads by the Godot builder tool
(game/landmarks/tools/build_landmarks.gd). Re-run whenever text/colors need
to change:

    cd pipeline/landmarks && ../../.venv/bin/python gen_signage.py

Outputs -> game/landmarks/textures/*.png (this workstream's own folder).
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "game", "landmarks", "textures")
os.makedirs(OUT_DIR, exist_ok=True)

SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"
if not os.path.exists(SANS_BOLD):
    SANS_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def font(path, size):
    return ImageFont.truetype(path, size)


def centered_text(draw, xy_box, text, fnt, fill, stroke_width=0, stroke_fill=None, letter_spacing=0):
    """Draw text centered in xy_box=(x0,y0,x1,y1), optional manual letter spacing."""
    x0, y0, x1, y1 = xy_box
    if letter_spacing:
        widths = [draw.textlength(ch, font=fnt) for ch in text]
        total = sum(widths) + letter_spacing * (len(text) - 1)
        cx = x0 + (x1 - x0 - total) / 2
        bbox = fnt.getbbox("Hg")
        cy = y0 + (y1 - y0 - (bbox[3] - bbox[1])) / 2 - bbox[1]
        for ch, w in zip(text, widths):
            draw.text((cx, cy), ch, font=fnt, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
            cx += w + letter_spacing
    else:
        bbox = draw.textbbox((0, 0), text, font=fnt, stroke_width=stroke_width)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        cx = x0 + (x1 - x0 - w) / 2 - bbox[0]
        cy = y0 + (y1 - y0 - h) / 2 - bbox[1]
        draw.text((cx, cy), text, font=fnt, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)


def save(img, name):
    path = os.path.join(OUT_DIR, name)
    img.save(path)
    print("wrote", path, img.size)


# --- 1. Dixon Arch crown sign: "DIXON", dark maroon face + red neon outline ---
# Wide aspect (crown signboard reads across the arch width).
W, H = 1024, 320
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
f = font(SERIF_BOLD, 220)
# neon outline glow (soft, wider stroke, additive-looking bright red)
centered_text(d, (0, 0, W, H), "DIXON", f, fill=(107, 31, 31, 255),
              stroke_width=10, stroke_fill=(255, 42, 42, 255), letter_spacing=14)
save(img, "dixon_arch_sign.png")

# --- 2. Theatre marquee: "HISTORIC DIXON THEATRE", white on maroon ---
W, H = 1024, 256
img = Image.new("RGBA", (W, H), (107, 31, 42, 255))
d = ImageDraw.Draw(img)
# thin light border
d.rectangle([6, 6, W - 7, H - 7], outline=(230, 220, 200, 255), width=4)
f1 = font(SANS_BOLD, 46)
f2 = font(SANS_BOLD, 96)
centered_text(d, (20, 18, W - 20, 100), "HISTORIC", f1, fill=(245, 242, 234, 255), letter_spacing=6)
centered_text(d, (20, 95, W - 20, 256), "DIXON THEATRE", f2, fill=(245, 242, 234, 255), letter_spacing=4)
save(img, "theatre_marquee.png")

# --- 3. Lincoln pedestal: "LINCOLN" carved-look text, transparent bg ---
W, H = 640, 200
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
f = font(SERIF_BOLD, 96)
# carved effect: dark recessed shadow offset down-right is wrong for engraving (light
# comes from above) -- highlight above-left, shadow below-right, on a mid-gray fill.
centered_text(d, (2, 2, W + 2, H + 2), "LINCOLN", f, fill=(60, 60, 58, 255), letter_spacing=6)
centered_text(d, (-2, -2, W - 2, H - 2), "LINCOLN", f, fill=(150, 150, 144, 200), letter_spacing=6)
centered_text(d, (0, 0, W, H), "LINCOLN", f, fill=(96, 96, 90, 255), letter_spacing=6)
save(img, "lincoln_text.png")

# --- 4. Courthouse entablature: "LEE COUNTY COURTHOUSE", carved stone look ---
W, H = 1536, 160
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
f = font(SERIF_BOLD, 78)
centered_text(d, (2, 2, W + 2, H + 2), "LEE COUNTY COURTHOUSE", f, fill=(150, 145, 128, 220), letter_spacing=10)
centered_text(d, (0, 0, W, H), "LEE COUNTY COURTHOUSE", f, fill=(90, 85, 72, 255), letter_spacing=10)
save(img, "courthouse_entablature.png")

# --- 5. Galena Ave bridge sidewalk stamp: "LINCOLN HIGHWAY" ---
W, H = 1024, 256
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
f = font(SANS_BOLD, 90)
centered_text(d, (2, 2, W + 2, H + 2), "LINCOLN HIGHWAY", f, fill=(120, 116, 106, 200), letter_spacing=6)
centered_text(d, (0, 0, W, H), "LINCOLN HIGHWAY", f, fill=(150, 146, 136, 230), letter_spacing=6)
save(img, "lincoln_highway_stamp.png")

print("done")
