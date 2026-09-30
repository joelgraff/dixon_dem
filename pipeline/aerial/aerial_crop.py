"""An axis-aligned box of the game world cut from the Illinois 2025 orthoimagery
tiles (data/raw/il2025/, fetched by fetch_illinois.py). Building Composer's
footprint editor traces over it (game/tools/composer_server.py GET /game-aerial).

Each tile is placed by its `pixel_from_world` mapping (georef_affine.py), which
follows the projection. A tile without one is placed by its recorded box
(x = world_x0 + px * mpp), which is up to ~15 m off at two of its corners; the
crop is then marked approximate. Where no tile covers the box, the image is
transparent.
"""
import io
import json
import os
from collections import OrderedDict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TILES_DIR = os.path.join(ROOT, "data", "raw", "il2025")
MAX_PIXELS = 4096  # per side of a crop


class Aerial:
    """The tiles in `directory`, with the last few opened kept in memory."""

    def __init__(self, directory=TILES_DIR, keep=6):
        self.directory = directory
        self.keep = keep
        self._open = OrderedDict()
        self._index = None

    def available(self):
        return os.path.exists(os.path.join(self.directory, "index.json"))

    def tiles(self):
        if self._index is None:
            with open(os.path.join(self.directory, "index.json")) as handle:
                self._index = json.load(handle)["tiles"]
        return self._index

    def _image(self, name):
        from PIL import Image

        if name in self._open:
            self._open.move_to_end(name)
            return self._open[name]
        image = Image.open(os.path.join(self.directory, f"{name}.png")).convert("RGBA")
        self._open[name] = image
        while len(self._open) > self.keep:
            self._open.popitem(last=False)
        return image

    def crop(self, x0, z0, x1, z1, mpp=0.25):
        """The box as an RGBA PIL image, `mpp` meters to a pixel; its
        info["approximate"] says whether a tile was placed by its recorded box alone."""
        from PIL import Image

        if not (x1 > x0 and z1 > z0 and mpp > 0):
            raise ValueError("an empty box")
        width = round((x1 - x0) / mpp)
        height = round((z1 - z0) / mpp)
        if width < 1 or height < 1 or width > MAX_PIXELS or height > MAX_PIXELS:
            raise ValueError(f"a {width} x {height} px crop; at most {MAX_PIXELS} a side")
        out = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        approximate = False
        for tile in self.tiles():
            mapping = tile.get("pixel_from_world")
            if mapping:
                self._place(out, tile, mapping, x0, z0, mpp)
                continue
            tx0, tz0, tx1, tz1 = tile["world_x0"], tile["world_z0"], tile["world_x1"], tile["world_z1"]
            ix0, iz0, ix1, iz1 = max(x0, tx0), max(z0, tz0), min(x1, tx1), min(z1, tz1)
            if ix1 <= ix0 or iz1 <= iz0:
                continue
            approximate = True
            tmpp = tile["mpp"]
            source = self._image(tile["tile"]).crop((
                round((ix0 - tx0) / tmpp), round((iz0 - tz0) / tmpp),
                round((ix1 - tx0) / tmpp), round((iz1 - tz0) / tmpp),
            ))
            left, top = round((ix0 - x0) / mpp), round((iz0 - z0) / mpp)
            size = (max(1, round((ix1 - x0) / mpp) - left), max(1, round((iz1 - z0) / mpp) - top))
            out.paste(source.resize(size, Image.BILINEAR), (left, top))
        out.info["approximate"] = approximate
        return out

    def _place(self, out, tile, mapping, x0, z0, mpp):
        """Draws the part of `tile` that falls in the crop, through its pixel_from_world mapping."""
        from PIL import Image

        a, b, c, d, e, f = mapping
        width, height = tile["size_px"]
        det = a * e - b * d
        corners = [((e * (px - c) - b * (py - f)) / det, (a * (py - f) - d * (px - c)) / det)
                   for px, py in ((0, 0), (width, 0), (0, height), (width, height))]
        wx0, wx1 = min(x for x, _ in corners), max(x for x, _ in corners)
        wz0, wz1 = min(z for _, z in corners), max(z for _, z in corners)
        if wx1 <= x0 or wz1 <= z0 or wx0 >= x0 + out.width * mpp or wz0 >= z0 + out.height * mpp:
            return
        # crop pixel (u, v) is world (x0 + u * mpp, z0 + v * mpp): into tile pixels
        affine = (a * mpp, b * mpp, a * x0 + b * z0 + c, d * mpp, e * mpp, d * x0 + e * z0 + f)
        placed = self._image(tile["tile"]).transform(out.size, Image.AFFINE, affine, resample=Image.BILINEAR,
                                                      fillcolor=(0, 0, 0, 0))
        out.alpha_composite(placed)

    def png(self, x0, z0, x1, z1, mpp=0.25):
        """The crop as PNG bytes, and whether it is approximate (see crop)."""
        image = self.crop(x0, z0, x1, z1, mpp)
        buffer = io.BytesIO()
        image.save(buffer, "PNG", optimize=False)
        return buffer.getvalue(), image.info["approximate"]
