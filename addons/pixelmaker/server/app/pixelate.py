"""Core pixelation engine.

Converts an arbitrary source image into retro pixel-art by:
  1. (optionally) removing a flat background and making it transparent,
  2. (optionally) trimming to the subject and padding to a square so it fills
     the frame edge-to-edge,
  3. downscaling to a small grid (e.g. 32x32),
  4. quantizing colors to a limited palette (adaptive or a fixed retro palette),
  5. upscaling back with NEAREST sampling so the pixels stay crisp.
"""
from __future__ import annotations

import io
from collections import deque
from typing import Optional

import numpy as np
from PIL import Image

from .palettes import NAMED_PALETTES, flatten

VALID_SIZES = (16, 32, 64, 128)
MIN_COLORS = 2
MAX_COLORS = 256
_WORK_MAX = 512  # cap working resolution for background/flood-fill cost

# Background defaults / limits
BG_DEFAULT_W = 1280
BG_DEFAULT_H = 720
BG_MIN_DIM = 256
BG_MAX_DIM = 3840
VALID_PIXEL_SIZES = (4, 6, 8, 12, 16)
VALID_TILE_DIVS = (1, 2, 4)


def _crop_to_square(img: Image.Image) -> Image.Image:
    """Center-crop the image to a square."""
    w, h = img.size
    if w == h:
        return img
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def _fit_working(img: Image.Image) -> Image.Image:
    """Downscale (never upscale) so the longest side is at most _WORK_MAX."""
    w, h = img.size
    longest = max(w, h)
    if longest <= _WORK_MAX:
        return img
    scale = _WORK_MAX / longest
    return img.resize((round(w * scale), round(h * scale)), Image.Resampling.LANCZOS)


def _remove_background(img_rgb: Image.Image, tolerance: int) -> Image.Image:
    """Flood-fill from the borders to make a flat background transparent."""
    arr = np.asarray(img_rgb, dtype=np.int16)
    h, w = arr.shape[:2]

    border = np.concatenate(
        [arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]], axis=0
    )
    bg = np.median(border, axis=0)
    dist = np.sqrt(((arr - bg) ** 2).sum(axis=2))
    candidate = dist <= tolerance

    visited = np.zeros((h, w), dtype=bool)
    dq: deque[tuple[int, int]] = deque()

    def _seed(y: int, x: int) -> None:
        if candidate[y, x] and not visited[y, x]:
            visited[y, x] = True
            dq.append((y, x))

    for x in range(w):
        _seed(0, x)
        _seed(h - 1, x)
    for y in range(h):
        _seed(y, 0)
        _seed(y, w - 1)

    while dq:
        y, x = dq.popleft()
        if y > 0:
            _seed(y - 1, x)
        if y < h - 1:
            _seed(y + 1, x)
        if x > 0:
            _seed(y, x - 1)
        if x < w - 1:
            _seed(y, x + 1)

    alpha = np.where(visited, 0, 255).astype(np.uint8)
    rgba = np.dstack([np.asarray(img_rgb, dtype=np.uint8), alpha])
    return Image.fromarray(rgba, "RGBA")


def _trim_to_content(rgba: Image.Image) -> Image.Image:
    """Crop to the bounding box of non-transparent pixels."""
    alpha = np.asarray(rgba)[:, :, 3]
    ys, xs = np.where(alpha > 0)
    if xs.size == 0:
        return rgba
    return rgba.crop(
        (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    )


def _pad_square(rgba: Image.Image) -> Image.Image:
    """Center the subject on a transparent square canvas (aspect preserved)."""
    w, h = rgba.size
    side = max(w, h)
    if w == h:
        return rgba
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(rgba, ((side - w) // 2, (side - h) // 2))
    return canvas


def _quantize(small: Image.Image, palette_name: str, colors: int) -> Image.Image:
    """Reduce the small image to a limited palette. Returns an RGB image."""
    if palette_name in NAMED_PALETTES:
        pal = NAMED_PALETTES[palette_name]
        pal_img = Image.new("P", (1, 1))
        flat = flatten(pal)
        flat = flat + [0] * (768 - len(flat))
        pal_img.putpalette(flat)
        quantized = small.convert("RGB").quantize(
            palette=pal_img, dither=Image.Dither.NONE
        )
    else:  # adaptive
        n = max(MIN_COLORS, min(MAX_COLORS, colors))
        quantized = small.convert("RGB").quantize(
            colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        )
    return quantized.convert("RGB")


def _quantize_rgba(small: Image.Image, palette_name: str, colors: int) -> Image.Image:
    """Quantize the RGB channels while preserving a binary alpha mask."""
    alpha = small.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    quantized = _quantize(small.convert("RGB"), palette_name, colors).convert("RGBA")
    quantized.putalpha(alpha)
    return quantized


def pixelate(
    image_bytes: bytes,
    size: int = 32,
    palette: str = "adaptive",
    colors: int = 16,
    upscale_to: Optional[int] = 512,
    remove_bg: bool = False,
    fill: bool = False,
    bg_tolerance: int = 30,
    crop_square: bool = False,
) -> tuple[bytes, bytes]:
    """Pixelate an image."""
    if size not in VALID_SIZES:
        raise ValueError(f"size must be one of {VALID_SIZES}, got {size}")

    src = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    use_alpha = remove_bg or fill
    if use_alpha:
        work = _fit_working(src)
        rgba = _remove_background(work, bg_tolerance)
        if fill:
            rgba = _trim_to_content(rgba)
            rgba = _pad_square(rgba)
        small = rgba.resize((size, size), Image.Resampling.LANCZOS)
        small = _quantize_rgba(small, palette, colors)
    else:
        if crop_square:
            src = _crop_to_square(src)
        small = src.resize((size, size), Image.Resampling.LANCZOS)
        small = _quantize(small, palette, colors)

    grid_buf = io.BytesIO()
    small.save(grid_buf, format="PNG")

    if upscale_to:
        large = small.resize((upscale_to, upscale_to), Image.Resampling.NEAREST)
    else:
        large = small
    large_buf = io.BytesIO()
    large.save(large_buf, format="PNG")

    return large_buf.getvalue(), grid_buf.getvalue()


def _cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Center-crop the image to the target aspect ratio (cover, no distortion)."""
    w, h = img.size
    target_ratio = target_w / target_h
    ratio = w / h
    if ratio > target_ratio:
        new_w = max(1, int(round(h * target_ratio)))
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    new_h = max(1, int(round(w / target_ratio)))
    top = (h - new_h) // 2
    return img.crop((0, top, w, top + new_h))


def _make_h_seamless(arr: np.ndarray) -> np.ndarray:
    """Return a horizontally tileable version of a small RGB grid."""
    gh, gw, _ = arr.shape
    doubled = np.concatenate([arr, arr], axis=1)
    start = gw // 2
    mid = doubled[:, start:start + gw].astype(np.float32)

    center = gw // 2
    band = max(2, gw // 6)
    lo = max(1, center - band)
    hi = min(gw - 1, center + band)
    left_col = mid[:, lo - 1]
    right_col = mid[:, hi]
    span = hi - lo
    for i in range(span):
        a = (i + 1) / (span + 1)
        mid[:, lo + i] = left_col * (1 - a) + right_col * a

    return np.clip(mid, 0, 255).astype(np.uint8)


def make_background(
    image_bytes: bytes,
    width: int = BG_DEFAULT_W,
    height: int = BG_DEFAULT_H,
    palette: str = "adaptive",
    colors: int = 24,
    pixel_size: int = 8,
    tileable: bool = True,
    tile_div: int = 1,
) -> tuple[bytes, Optional[bytes]]:
    """Turn a source image into a pixel-art background."""
    width = max(BG_MIN_DIM, min(BG_MAX_DIM, int(width)))
    height = max(BG_MIN_DIM, min(BG_MAX_DIM, int(height)))
    pixel_size = max(2, int(pixel_size))
    if tile_div not in VALID_TILE_DIVS:
        tile_div = 1
    if not tileable:
        tile_div = 1

    src = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    gh = max(8, round(height / pixel_size))
    tile_w = width // tile_div
    gw = max(8, round(tile_w / pixel_size))

    crop = _cover_crop(src, tile_w, height)
    small = crop.resize((gw, gh), Image.Resampling.LANCZOS)

    if tileable:
        small = Image.fromarray(_make_h_seamless(np.asarray(small)), "RGB")

    tile_q = _quantize(small, palette, colors)

    if tile_div > 1:
        full_grid = Image.new("RGB", (gw * tile_div, gh))
        for i in range(tile_div):
            full_grid.paste(tile_q, (i * gw, 0))
    else:
        full_grid = tile_q

    bg = full_grid.resize((width, height), Image.Resampling.NEAREST)
    bg_buf = io.BytesIO()
    bg.save(bg_buf, format="PNG")

    tile_bytes: Optional[bytes] = None
    if tileable and tile_div > 1:
        tile_img = tile_q.resize((tile_w, height), Image.Resampling.NEAREST)
        tbuf = io.BytesIO()
        tile_img.save(tbuf, format="PNG")
        tile_bytes = tbuf.getvalue()

    return bg_buf.getvalue(), tile_bytes
