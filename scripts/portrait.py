"""One-off: turn a photo into a dot-matrix grid at assets/portraits/<preset>.json.

    uv run --with pillow python scripts/portrait.py <preset> <path-to-image>

Each cell stores a tone (0-9) and whether it sits on an edge; build.py draws
tone as dot size and edges as the bright "lightning" dots. Source images stay
out of the repo. Crop boxes are in source pixels; the head ellipse and body
polygon that mask out the background are fractions of the crop.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

PRESETS = {
    # GitHub avatar (manga grin): line art, so invert to make the ink the light.
    # levels crush the paper texture to black and clip the ink to full; 80 cells
    # keep individual teeth apart.
    "avatar": dict(crop=(10, 6, 267, 240), invert=True, n=80, levels=(70, 220, 0.8),
                   sharpen=120, edge_cut=0.55),
    # devqilin's default identicon (420px fetch: 35px margin, 70px blocks), so
    # n=60 lands every block on exactly 10x10 cells
    "identicon": dict(crop=(0, 0, 420, 420), invert=True, n=60, levels=(60, 120, 1.0),
                      edge_cut=0.5),
    # LinkedIn MUJ blazer photo
    "linkedin": dict(crop=(1225, 2060, 1725, 2560), head=(.18, .16, .69, .82),
                     body=[(.27, .76), (.6, .76), (.69, .86), (1, .98), (1, 1), (0, 1), (0, .98),
                           (.19, .86)]),
    # Instagram go-kart shot (source: 1280x575 screenshot of the full-size post image)
    "helmet": dict(crop=(450, 100, 730, 380), head=(.29, .09, .59, .50),
                   body=[(.25, .45), (.6, .45), (1, .65), (1, 1), (.15, 1), (.15, .6)]),
}

name, path = sys.argv[1], sys.argv[2]
p = PRESETS[name]
n = p.get("n", 64)
im = ImageOps.exif_transpose(Image.open(path)).convert("L").crop(p["crop"])
w, h = im.size

mask = None
if "head" in p:
    mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(mask)
    x0, y0, x1, y1 = p["head"]
    d.ellipse((x0 * w, y0 * h, x1 * w, y1 * h), fill=255)
    d.polygon([(x * w, y * h) for x, y in p["body"]], fill=255)

im = ImageOps.equalize(im, mask=mask) if mask else ImageOps.autocontrast(im, cutoff=1)
if p.get("invert"):
    im = ImageOps.invert(im)
if p.get("sharpen"):
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=p["sharpen"], threshold=1))
if p.get("levels"):
    lo, hi, gamma = p["levels"]
    im = im.point(lambda v: 0 if v < lo else 255 if v > hi else int(255 * ((v - lo) / (hi - lo)) ** gamma))
edges = im.filter(ImageFilter.GaussianBlur(w / 400)).filter(ImageFilter.FIND_EDGES)
if mask:
    black = Image.new("L", im.size, 0)
    im = Image.composite(im, black, mask.filter(ImageFilter.GaussianBlur(w / 250)))
    # shrink the mask for edges so the hand-drawn outline itself doesn't glow
    edges = Image.composite(edges, black, mask.filter(ImageFilter.MinFilter(2 * (w // 110) + 1)))

tone = im.resize((n, n), Image.LANCZOS)
edge = ImageOps.autocontrast(edges.resize((n, n), Image.BOX), cutoff=2)
cut = 255 * p.get("edge_cut", 0.5)
grid = {
    # photos print as a negative on a light page unless their tones flip there
    "flip_on_light": not p.get("invert", False),
    "tone": ["".join(str(min(9, tone.getpixel((x, y)) * 10 // 256)) for x in range(n)) for y in range(n)],
    "edge": ["".join("1" if edge.getpixel((x, y)) > cut else "0" for x in range(n)) for y in range(n)],
}
out = Path(__file__).resolve().parent.parent / "assets" / "portraits" / f"{name}.json"
out.write_text(json.dumps(grid, indent=0), encoding="utf-8")
print(f"{out}: {n}x{n}, {sum(r.count('1') for r in grid['edge'])} edge cells")
