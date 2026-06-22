"""Pluggable procedural animation system (walk, idle, jump, attack)."""
from __future__ import annotations

from typing import Callable, Dict, List

import numpy as np
from PIL import Image

from .walkcycle import (
    DEFAULT_FPS_MS,
    DEFAULT_FRAMES,
    MAX_FPS_MS,
    MIN_FPS_MS,
    _gif_bytes,
    _load_rgba,
    _paste,
    _png_bytes,
    _sheet_bytes,
    build_frames as _walk_frames,
    detect_regions,
)

ACTIONS = ("walk", "idle", "jump", "attack")
DEFAULT_ACTION = "walk"


def _pad(base: np.ndarray, top: int = 0, bottom: int = 0,
         left: int = 0, right: int = 0) -> np.ndarray:
    H, W = base.shape[:2]
    out = np.zeros((H + top + bottom, W + left + right, 4), dtype=base.dtype)
    out[top:top + H, left:left + W] = base
    return out


def _vscale_anchored(layer: np.ndarray, factor: float, anchor_row: int) -> np.ndarray:
    if abs(factor - 1.0) < 1e-3:
        return layer.copy()
    H, W = layer.shape[:2]
    img = Image.fromarray(layer, "RGBA")
    new_h = max(1, round(H * factor))
    scaled = np.array(img.resize((W, new_h), Image.NEAREST))
    out = np.zeros_like(layer)
    shift = anchor_row - round(anchor_row * factor)
    for y in range(new_h):
        ty = y + shift
        if 0 <= ty < H:
            row = scaled[y]
            mask = row[:, 3] > 0
            out[ty][mask] = row[mask]
    return out


def _shear_top(layer: np.ndarray, max_dx: int, pivot_row: int, top_row: int) -> np.ndarray:
    H, W = layer.shape[:2]
    out = np.zeros_like(layer)
    span = max(1, pivot_row - top_row)
    for y in range(H):
        if y >= pivot_row:
            dx = 0
        else:
            dx = round(max_dx * (pivot_row - y) / span)
        row = layer[y]
        mask = row[:, 3] > 0
        xs = np.where(mask)[0]
        for x in xs:
            tx = x + dx
            if 0 <= tx < W:
                out[y, tx] = row[x]
    return out


def _gen_idle(base: np.ndarray, R: dict) -> List[np.ndarray]:
    H, W = base.shape[:2]
    pad_top = max(0, 1 - R["top"])
    canvas_base = _pad(base, top=pad_top)
    foot_top = R["foot_top"] + pad_top
    foot_bottom = R["foot_bottom"] + pad_top
    body_bottom = R["body_bottom"] + pad_top

    body = canvas_base.copy()
    body[foot_top:foot_bottom + 1] = 0
    feet = np.zeros_like(canvas_base)
    feet[foot_top:foot_bottom + 1] = canvas_base[foot_top:foot_bottom + 1]
    seam = np.zeros_like(canvas_base)
    if 0 <= body_bottom < canvas_base.shape[0]:
        seam[body_bottom] = canvas_base[body_bottom]

    body_dys = [0, -1, 0, -1]
    frames: List[np.ndarray] = []
    for dy in body_dys:
        c = np.zeros_like(canvas_base)
        _paste(c, body, dy=dy)
        if dy < 0:
            for k in range(-dy):
                _paste(c, seam, dy=-k)
        _paste(c, feet)
        frames.append(c)
    return frames


def _gen_jump(base: np.ndarray, R: dict) -> List[np.ndarray]:
    H, W = base.shape[:2]
    rise = max(3, R["bbox_h"] // 4)
    pad_top = rise + max(0, 1 - R["top"])
    canvas_base = _pad(base, top=pad_top)
    foot_top = R["foot_top"] + pad_top
    foot_bottom = R["foot_bottom"] + pad_top
    anchor = foot_bottom

    def split(layer):
        body = layer.copy()
        body[foot_top:foot_bottom + 1] = 0
        feet = np.zeros_like(layer)
        feet[foot_top:foot_bottom + 1] = layer[foot_top:foot_bottom + 1]
        return body, feet

    body, feet = split(canvas_base)
    tuck = max(1, R["bbox_h"] // 8)

    specs = [
        (0.85, 0, 0),
        (1.10, -1, 0),
        (1.0, -rise, -tuck),
        (1.0, -rise, -tuck),
        (1.0, -rise // 2, -tuck // 2),
        (0.85, 0, 0),
    ]
    frames: List[np.ndarray] = []
    for factor, whole_dy, feet_dy in specs:
        c = np.zeros_like(canvas_base)
        b = _vscale_anchored(body, factor, anchor) if factor != 1.0 else body
        _paste(c, b, dy=whole_dy)
        _paste(c, feet, dy=whole_dy + feet_dy)
        frames.append(c)
    return frames


def _gen_attack(base: np.ndarray, R: dict) -> List[np.ndarray]:
    H, W = base.shape[:2]
    reach = max(2, R["bbox_w"] // 8)
    pad = reach + 1
    pad_top = max(0, 1 - R["top"])
    canvas_base = _pad(base, top=pad_top, left=pad, right=pad)
    top_row = R["top"] + pad_top
    pivot_row = R["top"] + pad_top + (R["bbox_h"] * 2) // 3

    specs = [
        (-1, -1),
        (reach, reach),
        (reach - 1, 1),
        (1, 0),
        (0, 0),
    ]
    frames: List[np.ndarray] = []
    for whole_dx, shear_dx in specs:
        layer = canvas_base
        if shear_dx:
            layer = _shear_top(layer, shear_dx, pivot_row, top_row)
        c = np.zeros_like(canvas_base)
        _paste(c, layer, dx=whole_dx)
        frames.append(c)
    return frames


_GENERATORS: Dict[str, Callable] = {
    "idle": _gen_idle,
    "jump": _gen_jump,
    "attack": _gen_attack,
}


def make_animation(data: bytes, action: str = DEFAULT_ACTION,
                   frames: int = DEFAULT_FRAMES, fps_ms: int = DEFAULT_FPS_MS) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {list(ACTIONS)}")
    fps_ms = max(MIN_FPS_MS, min(MAX_FPS_MS, int(fps_ms)))

    if action == "walk":
        arrs = _walk_frames(data, frames=frames)
    else:
        base = _load_rgba(data)
        R = detect_regions(base)
        arrs = _GENERATORS[action](base, R)

    h, w = arrs[0].shape[:2]
    return {
        "action": action,
        "width": w,
        "height": h,
        "frame_count": len(arrs),
        "frames": [_png_bytes(a) for a in arrs],
        "sheet_png": _sheet_bytes(arrs),
        "gif_png": _gif_bytes(arrs, fps_ms),
    }
