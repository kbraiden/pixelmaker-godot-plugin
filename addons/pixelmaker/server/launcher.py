#!/usr/bin/env python3
"""PixelMaker Godot Plugin — Python server launcher.

This script is invoked by the Godot plugin (plugin.gd) when the plugin is
enabled.  It auto-installs any missing pip dependencies from the local
requirements.txt and then starts the FastAPI server on 127.0.0.1:8765
(a non-default port so it does not conflict with the standalone PixelMaker
web app that defaults to port 8000).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))

PORT = 8765


def _ensure_deps() -> None:
    """Install missing dependencies if necessary."""
    missing = []
    for pkg in ("fastapi", "uvicorn", "PIL", "numpy", "dotenv", "multipart"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        req = SERVER_DIR / "requirements.txt"
        print(f"[PixelMaker] Installing dependencies from {req} …")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            check=True,
        )
        print("[PixelMaker] Dependencies installed.")


if __name__ == "__main__":
    _ensure_deps()

    # Re-import after potential install
    import uvicorn  # noqa: E402 (import after conditional install)

    print(f"[PixelMaker] Starting server on http://127.0.0.1:{PORT}")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=PORT,
        log_level="warning",
        reload=False,
    )
