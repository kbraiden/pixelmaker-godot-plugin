"""Isometric tile generator — builds clean 2:1 isometric tiles with Godot 4 export."""
from __future__ import annotations

import io
import zipfile
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

from .pixelate import _quantize_rgba

VALID_ISO_WIDTHS = (32, 64, 128)
DEFAULT_ISO_WIDTH = 64
HEIGHT_VARIANTS = ("full", "half", "quarter", "slab")
_DEPTH_FRACTION = {"full": 1.0, "half": 0.5, "quarter": 0.25, "slab": 0.0}

OUTLINE = (24, 28, 26, 255)
_LEFT_SHADE = 0.55
_RIGHT_SHADE = 0.72
_RIM_SHADE = 0.82


def _load_rgb(data: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(data)).convert("RGB"))


def _depth_for(width: int, variant: str) -> int:
    full = width // 2
    if variant == "slab":
        return max(2, width // 16)
    return max(2, round(full * _DEPTH_FRACTION[variant]))


def _in_diamond(x: float, y: float, cx: float, cyc: float, w: int, htop: int) -> bool:
    return abs(x - cx) / (w / 2) + abs(y - cyc) / (htop / 2) <= 1.0 + 1e-9


def project_top(texture: np.ndarray, width: int) -> Tuple[np.ndarray, List[int]]:
    htop = width // 2
    th, tw = texture.shape[:2]
    out = np.zeros((htop, width, 4), dtype=np.uint8)
    bottom_row = [-1] * width
    cx = (width - 1) / 2.0
    cyc = (htop - 1) / 2.0
    for y in range(htop):
        for x in range(width):
            if not _in_diamond(x, y, cx, cyc, width, htop):
                continue
            sx = (x - cx) / (width / 2.0)
            sy = (y - cyc) / (htop / 2.0) + 1.0
            u = max(0.0, min(1.0, (sy + sx) / 2.0))
            v = max(0.0, min(1.0, (sy - sx) / 2.0))
            tx = min(tw - 1, int(u * tw))
            ty = min(th - 1, int(v * th))
            r, g, b = texture[ty, tx]
            out[y, x] = (int(r), int(g), int(b), 255)
            bottom_row[x] = y
    return out, bottom_row


def _shade(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in color)


def _representative_color(top: np.ndarray) -> Tuple[int, int, int]:
    mask = top[:, :, 3] > 0
    px = top[:, :, :3][mask]
    if px.size == 0:
        return (120, 120, 120)
    return tuple(int(v) for v in np.median(px, axis=0))


def _rim_height(width: int, depth: int) -> int:
    rim = max(2, round(width / 20))
    return max(1, min(rim, depth - 1)) if depth >= 2 else 0


def build_tile(top: np.ndarray, bottom_row: List[int], width: int, depth: int,
               side_color: Tuple[int, int, int], rim: bool = True) -> np.ndarray:
    htop = width // 2
    H = htop + depth + 1
    img = np.zeros((H, width, 4), dtype=np.uint8)
    img[:htop] = top

    cx = (width - 1) / 2.0
    left_col = _shade(side_color, _LEFT_SHADE)
    right_col = _shade(side_color, _RIGHT_SHADE)
    rim_h = _rim_height(width, depth) if rim else 0
    for x in range(width):
        b = bottom_row[x]
        if b < 0:
            continue
        face = left_col if x < cx else right_col
        rim_col = _shade(tuple(int(v) for v in top[b, x, :3]), _RIM_SHADE)
        for k in range(1, depth + 1):
            y = b + k
            if y >= H:
                continue
            img[y, x] = (*(rim_col if k <= rim_h else face), 255)
    _outline(img)
    return img


def _outline(img: np.ndarray) -> None:
    H, W = img.shape[:2]
    alpha = img[:, :, 3] > 0
    for y in range(H):
        for x in range(W):
            if alpha[y, x]:
                continue
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < H and 0 <= nx < W and alpha[ny, nx]:
                    img[y, x] = OUTLINE
                    break


def _png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def _quantize_texture(texture: np.ndarray, palette: str, colors: int) -> np.ndarray:
    img = Image.fromarray(texture, "RGB").resize((96, 96), Image.Resampling.LANCZOS)
    img = img.convert("RGBA")
    q = _quantize_rgba(img, palette, colors)
    return np.array(q.convert("RGB"))


def _build_atlas(tiles: Dict[str, np.ndarray], width: int) -> Tuple[bytes, int, List[str], int]:
    names = [n for n in HEIGHT_VARIANTS if n in tiles]
    cell_h = max(tiles[n].shape[0] for n in names)
    n = len(names)
    atlas = Image.new("RGBA", (width * n, cell_h), (0, 0, 0, 0))
    for i, name in enumerate(names):
        t = tiles[name]
        th = t.shape[0]
        atlas.paste(Image.fromarray(t, "RGBA"), (i * width, cell_h - th))
    buf = io.BytesIO()
    atlas.save(buf, format="PNG")
    return buf.getvalue(), cell_h, names, n


def _godot_tres(width: int, cell_h: int, names: List[str], atlas_name: str,
                folder: str) -> str:
    htop = width // 2
    lines = [
        '[gd_resource type="TileSet" load_steps=3 format=3]',
        "",
        f'[ext_resource type="Texture2D" path="res://{folder}/{atlas_name}" id="1_atlas"]',
        "",
        '[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_iso"]',
        'texture = ExtResource("1_atlas")',
        f"texture_region_size = Vector2i({width}, {cell_h})",
    ]
    origin_y = (cell_h - htop) // 2
    for col, _name in enumerate(names):
        lines.append(f"{col}:0/0 = 0")
        lines.append(f"{col}:0/0/texture_origin = Vector2i(0, {origin_y})")
    lines += [
        "",
        "[resource]",
        "tile_shape = 1",
        "tile_layout = 0",
        "tile_offset_axis = 0",
        f"tile_size = Vector2i({width}, {htop})",
        'sources/0 = SubResource("TileSetAtlasSource_iso")',
        "",
    ]
    return "\n".join(lines)


def _import_notes(width: int, cell_h: int, names: List[str], atlas_name: str,
                  tres_name: str, folder: str) -> str:
    htop = width // 2
    return (
        "Godot 4 isometric tileset import\n"
        "================================\n\n"
        f"Folder      : {folder}/\n"
        f"Atlas image : {atlas_name}\n"
        f"TileSet     : {tres_name}\n\n"
        "Quick path (recommended):\n"
        f"  1. Unzip and copy the whole '{folder}' folder into your Godot project\n"
        f"     root, so the files live at res://{folder}/ .\n"
        f"  2. Add a TileMapLayer node and assign {folder}/{tres_name} as its Tile Set.\n"
        "  3. Enable Y-Sort on the layer for correct depth ordering.\n\n"
        f"  (If you place the folder somewhere other than the project root, open\n"
        f"   {tres_name} and fix the atlas path on the ext_resource line.)\n\n"
        "Manual setup (if you build the TileSet yourself):\n"
        f"  - Tile Shape         : Isometric\n"
        f"  - Tile Size          : {width} x {htop}   (2:1 diamond base)\n"
        f"  - Atlas region size  : {width} x {cell_h}\n"
        f"  - Texture origin      : bottom-centre (the diamond's 'feet')\n"
        f"  - Tiles, left->right : {', '.join(names)}\n\n"
        "All height variants share the same diamond base, so taller blocks rise\n"
        "above the cell while their base stays on the grid.\n"
    )


def make_isometric_tiles(texture_bytes: bytes, width: int = DEFAULT_ISO_WIDTH,
                         variants: Tuple[str, ...] = HEIGHT_VARIANTS,
                         palette: str = "adaptive", colors: int = 16,
                         side_texture_bytes: bytes | None = None,
                         rim: bool = True,
                         basename: str = "iso") -> dict:
    if width not in VALID_ISO_WIDTHS:
        raise ValueError(f"width must be one of {list(VALID_ISO_WIDTHS)}")
    chosen = [v for v in HEIGHT_VARIANTS if v in variants]
    if not chosen:
        raise ValueError("at least one height variant is required")

    tex_q = _quantize_texture(_load_rgb(texture_bytes), palette, colors)
    top, bottom_row = project_top(tex_q, width)

    if side_texture_bytes:
        side_q = _quantize_texture(_load_rgb(side_texture_bytes), palette, colors)
        side_base = _representative_color(
            np.dstack([side_q, np.full(side_q.shape[:2], 255, np.uint8)]))
    else:
        side_base = _representative_color(top)

    tiles = {v: build_tile(top, bottom_row, width, _depth_for(width, v), side_base, rim=rim)
             for v in chosen}

    folder = basename
    atlas_png, cell_h, names, _ = _build_atlas(tiles, width)
    atlas_name = f"{basename}_atlas.png"
    tres_name = f"{basename}_tileset.tres"
    notes_name = f"{basename}_godot_notes.txt"
    tres = _godot_tres(width, cell_h, names, atlas_name, folder)
    notes = _import_notes(width, cell_h, names, atlas_name, tres_name, folder)
    tile_pngs = {name: _png(tiles[name]) for name in names}

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{folder}/{atlas_name}", atlas_png)
        zf.writestr(f"{folder}/{tres_name}", tres)
        zf.writestr(f"{folder}/{notes_name}", notes)
        for name, png in tile_pngs.items():
            zf.writestr(f"{folder}/{basename}_{name}.png", png)
    zip_bytes = zbuf.getvalue()

    scale = max(1, 256 // (width // 2 + max(t.shape[0] for t in tiles.values())))
    prev_cell_w = width * scale
    prev_h = cell_h * scale
    preview = Image.new("RGBA", (prev_cell_w * len(names), prev_h), (34, 34, 44, 255))
    for i, name in enumerate(names):
        t = tiles[name]
        im = Image.fromarray(t, "RGBA").resize(
            (t.shape[1] * scale, t.shape[0] * scale), Image.NEAREST)
        preview.alpha_composite(im, (i * prev_cell_w, prev_h - im.height))
    pbuf = io.BytesIO()
    preview.save(pbuf, format="PNG")

    return {
        "width": width,
        "tile_size": [width, width // 2],
        "cell_size": [width, cell_h],
        "variants": names,
        "tiles": tile_pngs,
        "atlas_png": atlas_png,
        "atlas_name": atlas_name,
        "tres_text": tres,
        "tres_name": tres_name,
        "notes_text": notes,
        "preview_png": pbuf.getvalue(),
        "zip_bytes": zip_bytes,
        "zip_name": f"{folder}.zip",
    }
