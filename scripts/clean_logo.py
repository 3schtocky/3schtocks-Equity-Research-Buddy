"""Upscale and clean the Conscious Investments logo (assets/logo.png, 114x123 source).

Produces:
  assets/logo_hires.png        ink on a flat paper tone (6x, ~684x738)
  assets/logo_transparent.png  ink only with alpha, for placing on white pages

Method: Lanczos 6x upscale, light denoise, then a contrast curve on "inkness"
(distance from the paper tone) so the stone texture drops out and the linework
and lettering stay solid. Upscaling cannot add detail; a vector original is better.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SCALE = 6
INK = np.array([0x2E, 0x2C, 0x29])     # slightly deeper than the sampled #43413e for print
PAPER = np.array([0xEC, 0xEA, 0xE1])   # sampled background tone

src = Image.open(ROOT / "assets/logo.png").convert("L")
big = src.resize((src.width * SCALE, src.height * SCALE), Image.LANCZOS)
big = big.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(1.2))
lum = np.asarray(big).astype(float)

# inkness: 0 at paper (texture ~ 200-240), 1 at ink (< ~110)
lo, hi = 115.0, 195.0
t = np.clip((hi - lum) / (hi - lo), 0, 1)
t = t * t * (3 - 2 * t)  # smoothstep for crisp but anti-aliased edges

rgb = (PAPER[None, None, :] * (1 - t[..., None]) + INK[None, None, :] * t[..., None]).astype(np.uint8)
Image.fromarray(rgb).filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=2)).save(
    ROOT / "assets/logo_hires.png", dpi=(300, 300))

alpha = (t * 255).astype(np.uint8)
ink_rgba = np.dstack([np.broadcast_to(INK, t.shape + (3,)).astype(np.uint8), alpha])
Image.fromarray(ink_rgba, "RGBA").save(ROOT / "assets/logo_transparent.png", dpi=(300, 300))
print("wrote assets/logo_hires.png and assets/logo_transparent.png", rgb.shape[1::-1])
