"""PixelMaker FastAPI application — Godot Plugin edition.

Identical to the standalone app but without the static-file web UI mount
(the Godot editor dock is the UI instead).  Runs on 127.0.0.1:8765 by default
so it does not collide with the standalone server on port 8000.
"""
from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from .config import settings
from .palettes import palette_names
from .pixelate import (
    BG_MAX_DIM,
    BG_MIN_DIM,
    MAX_COLORS,
    MIN_COLORS,
    VALID_PIXEL_SIZES,
    VALID_SIZES,
    VALID_TILE_DIVS,
    make_background,
    pixelate,
)
from .providers import ProviderError, get_provider
from .walkcycle import (
    DEFAULT_FPS_MS,
    DEFAULT_FRAMES,
    VALID_FRAME_COUNTS,
)
from .animations import ACTIONS, DEFAULT_ACTION, make_animation
from .isometric import (
    DEFAULT_ISO_WIDTH,
    HEIGHT_VARIANTS,
    VALID_ISO_WIDTHS,
    make_isometric_tiles,
)

app = FastAPI(title="PixelMaker (Godot Plugin)", version="1.0.0")


def _validate_params(size: int, palette: str, colors: int) -> None:
    if size not in VALID_SIZES:
        raise HTTPException(400, f"size must be one of {list(VALID_SIZES)}")
    if palette not in palette_names():
        raise HTTPException(400, f"palette must be one of {palette_names()}")
    if not (MIN_COLORS <= colors <= MAX_COLORS):
        raise HTTPException(400, f"colors must be between {MIN_COLORS} and {MAX_COLORS}")


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "ai_enabled": settings.ai_enabled,
            "sizes": list(VALID_SIZES),
            "palettes": palette_names(),
        }
    )


@app.post("/api/usage")
def get_usage(api_key: str = Form(...)) -> JSONResponse:
    """Return OpenAI billing usage for the current month."""
    import json
    import urllib.error
    import urllib.request
    from datetime import date, timedelta

    if not api_key:
        raise HTTPException(400, "api_key is required")

    today = date.today()
    start_date = today.replace(day=1).isoformat()
    end_date = (today + timedelta(days=1)).isoformat()
    headers = {"Authorization": f"Bearer {api_key}"}
    result: dict = {}

    # Current-month usage (returns total_usage in cents)
    try:
        url = (
            f"https://api.openai.com/dashboard/billing/usage"
            f"?start_date={start_date}&end_date={end_date}"
        )
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        result["month_usage_usd"] = round(data.get("total_usage", 0) / 100, 4)
        result["period"] = f"{start_date} \u2013 {today.isoformat()}"
    except urllib.error.HTTPError as exc:
        result["usage_error"] = f"HTTP {exc.code}"
    except Exception as exc:
        result["usage_error"] = str(exc)

    # Credit balance (total_granted / total_used / total_available)
    try:
        req = urllib.request.Request(
            "https://api.openai.com/dashboard/billing/credit_grants",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        result["total_granted"]   = round(float(data.get("total_granted",   0)), 2)
        result["total_used"]      = round(float(data.get("total_used",      0)), 2)
        result["total_available"] = round(float(data.get("total_available", 0)), 2)
    except urllib.error.HTTPError as exc:
        result["grants_error"] = f"HTTP {exc.code}"
    except Exception as exc:
        result["grants_error"] = str(exc)

    if "usage_error" in result and "grants_error" in result:
        return JSONResponse(
            {"error": "Could not fetch usage. The key may lack billing access."},
            status_code=400,
        )
    return JSONResponse(result)

(large_png: bytes, grid_png: bytes, size: int) -> JSONResponse:
    return JSONResponse(
        {
            "size": size,
            "preview_png": base64.b64encode(large_png).decode("ascii"),
            "sprite_png": base64.b64encode(grid_png).decode("ascii"),
        }
    )


@app.post("/api/generate")
def generate(
    prompt: str = Form(...),
    size: int = Form(32),
    palette: str = Form("adaptive"),
    colors: int = Form(16),
    remove_bg: bool = Form(True),
    fill: bool = Form(True),
    api_key: str = Form(""),
) -> JSONResponse:
    """Text -> pixel art via the configured AI provider."""
    _validate_params(size, palette, colors)
    if not prompt.strip():
        raise HTTPException(400, "prompt must not be empty")
    try:
        provider = get_provider(api_key.strip() or None)
        source = provider.generate(prompt)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc

    large_png, grid_png = pixelate(
        source,
        size=size,
        palette=palette,
        colors=colors,
        remove_bg=remove_bg,
        fill=fill,
    )
    return _result_json(large_png, grid_png, size)


@app.post("/api/convert")
async def convert(
    file: UploadFile = File(...),
    size: int = Form(32),
    palette: str = Form("adaptive"),
    colors: int = Form(16),
    remove_bg: bool = Form(True),
    fill: bool = Form(True),
) -> JSONResponse:
    """Uploaded image -> pixel art (fully local, no AI)."""
    _validate_params(size, palette, colors)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "uploaded file is empty")
    try:
        large_png, grid_png = pixelate(
            raw,
            size=size,
            palette=palette,
            colors=colors,
            remove_bg=remove_bg,
            fill=fill,
        )
    except Exception as exc:
        raise HTTPException(400, f"could not process image: {exc}") from exc
    return _result_json(large_png, grid_png, size)


@app.post("/api/background")
def background(
    prompt: str = Form(...),
    width: int = Form(1280),
    height: int = Form(720),
    palette: str = Form("adaptive"),
    colors: int = Form(24),
    pixel_size: int = Form(8),
    tileable: bool = Form(True),
    tile_div: int = Form(1),
    api_key: str = Form(""),
) -> JSONResponse:
    """Text -> simple pixel-art background via the configured AI provider."""
    if palette not in palette_names():
        raise HTTPException(400, f"palette must be one of {palette_names()}")
    if not (MIN_COLORS <= colors <= MAX_COLORS):
        raise HTTPException(400, f"colors must be between {MIN_COLORS} and {MAX_COLORS}")
    if not (BG_MIN_DIM <= width <= BG_MAX_DIM and BG_MIN_DIM <= height <= BG_MAX_DIM):
        raise HTTPException(400, f"width/height must be {BG_MIN_DIM}-{BG_MAX_DIM}")
    if pixel_size not in VALID_PIXEL_SIZES:
        raise HTTPException(400, f"pixel_size must be one of {list(VALID_PIXEL_SIZES)}")
    if tile_div not in VALID_TILE_DIVS:
        raise HTTPException(400, f"tile_div must be one of {list(VALID_TILE_DIVS)}")
    if not prompt.strip():
        raise HTTPException(400, "prompt must not be empty")

    try:
        provider = get_provider(api_key.strip() or None)
        source = provider.generate(prompt, style="background")
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc

    bg_png, tile_png = make_background(
        source,
        width=width,
        height=height,
        palette=palette,
        colors=colors,
        pixel_size=pixel_size,
        tileable=tileable,
        tile_div=tile_div,
    )
    payload = {
        "width": width,
        "height": height,
        "background_png": base64.b64encode(bg_png).decode("ascii"),
        "tile_png": base64.b64encode(tile_png).decode("ascii") if tile_png else None,
    }
    return JSONResponse(payload)


@app.post("/api/walk")
async def walk(
    file: UploadFile = File(...),
    action: str = Form(DEFAULT_ACTION),
    frames: int = Form(DEFAULT_FRAMES),
    fps_ms: int = Form(DEFAULT_FPS_MS),
) -> JSONResponse:
    """Uploaded sprite -> procedural animation (walk/idle/jump/attack), fully local."""
    if action not in ACTIONS:
        raise HTTPException(400, f"action must be one of {list(ACTIONS)}")
    if action == "walk" and frames not in VALID_FRAME_COUNTS:
        raise HTTPException(400, f"frames must be one of {list(VALID_FRAME_COUNTS)}")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "uploaded file is empty")
    try:
        result = make_animation(raw, action=action, frames=frames, fps_ms=fps_ms)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"could not animate sprite: {exc}") from exc
    return JSONResponse(
        {
            "action": result["action"],
            "width": result["width"],
            "height": result["height"],
            "frame_count": result["frame_count"],
            "frames": [base64.b64encode(f).decode("ascii") for f in result["frames"]],
            "sheet_png": base64.b64encode(result["sheet_png"]).decode("ascii"),
            "gif_png": base64.b64encode(result["gif_png"]).decode("ascii"),
        }
    )


@app.post("/api/isometric")
def isometric(
    prompt: str = Form(...),
    side_prompt: str = Form(""),
    width: int = Form(DEFAULT_ISO_WIDTH),
    palette: str = Form("adaptive"),
    colors: int = Form(16),
    variants: str = Form("full,half,quarter,slab"),
    rim: bool = Form(True),
    name: str = Form("iso"),
    api_key: str = Form(""),
) -> JSONResponse:
    """Text -> clean 2:1 isometric tileset (top texture snapped onto geometry)."""
    if width not in VALID_ISO_WIDTHS:
        raise HTTPException(400, f"width must be one of {list(VALID_ISO_WIDTHS)}")
    if palette not in palette_names():
        raise HTTPException(400, f"palette must be one of {palette_names()}")
    if not (MIN_COLORS <= colors <= MAX_COLORS):
        raise HTTPException(400, f"colors must be between {MIN_COLORS} and {MAX_COLORS}")
    chosen = tuple(v.strip() for v in variants.split(",") if v.strip() in HEIGHT_VARIANTS)
    if not chosen:
        raise HTTPException(400, f"variants must include some of {list(HEIGHT_VARIANTS)}")
    if not prompt.strip():
        raise HTTPException(400, "prompt must not be empty")

    basename = "".join(c if (c.isalnum() or c in "-_") else "-" for c in name.strip())
    basename = basename.strip("-_") or "iso"

    try:
        provider = get_provider(api_key.strip() or None)
        top_texture = provider.generate(prompt, style="texture")
        side_texture = (
            provider.generate(side_prompt, style="texture")
            if side_prompt.strip() else None
        )
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc

    try:
        result = make_isometric_tiles(
            top_texture,
            width=width,
            variants=chosen,
            palette=palette,
            colors=colors,
            side_texture_bytes=side_texture,
            rim=rim,
            basename=basename,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return JSONResponse(
        {
            "tile_size": result["tile_size"],
            "cell_size": result["cell_size"],
            "variants": result["variants"],
            "preview_png": base64.b64encode(result["preview_png"]).decode("ascii"),
            "zip": base64.b64encode(result["zip_bytes"]).decode("ascii"),
            "zip_name": result["zip_name"],
        }
    )


@app.get("/")
def index() -> JSONResponse:
    return JSONResponse({
        "service": "PixelMaker Godot Plugin API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health",
    })
