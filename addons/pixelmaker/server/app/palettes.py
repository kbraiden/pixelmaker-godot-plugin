"""Retro color palettes for pixel-art quantization.

Each palette is a flat list of RGB triples expressed as a list of ints,
suitable for building a Pillow palette image.
"""
from __future__ import annotations

from typing import Dict, List

# Classic NES-ish selection (subset, 16 colors).
NES: List[tuple[int, int, int]] = [
    (0, 0, 0),
    (255, 255, 255),
    (136, 20, 0),
    (168, 16, 32),
    (48, 96, 128),
    (32, 56, 236),
    (0, 168, 0),
    (88, 216, 84),
    (228, 92, 16),
    (252, 152, 56),
    (172, 124, 0),
    (252, 224, 168),
    (136, 20, 176),
    (200, 76, 200),
    (116, 116, 116),
    (188, 188, 188),
]

# Original Game Boy 4-shade green palette.
GAMEBOY: List[tuple[int, int, int]] = [
    (15, 56, 15),
    (48, 98, 48),
    (139, 172, 15),
    (155, 188, 15),
]

# CGA mode 4 palette (cyan/magenta/white on black).
CGA: List[tuple[int, int, int]] = [
    (0, 0, 0),
    (85, 255, 255),
    (255, 85, 255),
    (255, 255, 255),
]

# A general 16-color "pico"-style palette for colorful retro art.
PICO8: List[tuple[int, int, int]] = [
    (0, 0, 0),
    (29, 43, 83),
    (126, 37, 83),
    (0, 135, 81),
    (171, 82, 54),
    (95, 87, 79),
    (194, 195, 199),
    (255, 241, 232),
    (255, 0, 77),
    (255, 163, 0),
    (255, 236, 39),
    (0, 228, 54),
    (41, 173, 255),
    (131, 118, 156),
    (255, 119, 168),
    (255, 204, 170),
]

NAMED_PALETTES: Dict[str, List[tuple[int, int, int]]] = {
    "nes": NES,
    "gameboy": GAMEBOY,
    "cga": CGA,
    "pico8": PICO8,
}


def palette_names() -> List[str]:
    """Return the list of available named palette identifiers."""
    return ["adaptive", *NAMED_PALETTES.keys()]


def flatten(palette: List[tuple[int, int, int]]) -> List[int]:
    """Flatten a list of RGB triples into a flat [r, g, b, r, g, b, ...] list."""
    return [c for rgb in palette for c in rgb]
