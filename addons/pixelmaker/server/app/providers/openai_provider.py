"""OpenAI image-generation provider."""
from __future__ import annotations

import base64

from ..config import settings
from .base import ImageProvider, ProviderError

_TEMPLATES = {
    "sprite": (
        "{subject}, retro 8-bit pixel art video game sprite, "
        "limited color palette, crisp pixels, centered, flat solid background"
    ),
    "background": (
        "{subject}, simple retro 16-bit pixel art video game background scene, "
        "side-scroller backdrop, wide landscape, limited color palette, "
        "smooth simple shapes with minimal clutter, no characters, no text, "
        "even left-to-right composition suitable for seamless horizontal tiling"
    ),
    "texture": (
        "{subject}, seamless top-down flat pixel-art material texture, "
        "repeating tileable pattern viewed straight from above, no perspective, "
        "no objects, no shadows, even flat lighting, limited color palette, "
        "fills the entire frame edge to edge"
    ),
}
_SHAPES = {
    "sprite": "1024x1024",
    "background": "1536x1024",
    "texture": "1024x1024",
}


class OpenAIProvider(ImageProvider):
    name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.openai_api_key
        if not key:
            raise ProviderError("No OpenAI API key provided.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError(
                "The 'openai' package is not installed. Run 'pip install openai'."
            ) from exc
        self._client = OpenAI(api_key=key)
        self._model = settings.openai_image_model

    def generate(self, prompt: str, style: str = "sprite") -> bytes:
        clean = prompt.strip()
        if not clean:
            raise ProviderError("Prompt must not be empty.")
        template = _TEMPLATES.get(style, _TEMPLATES["sprite"])
        shape = _SHAPES.get(style, _SHAPES["sprite"])
        full_prompt = template.format(subject=clean)
        try:
            result = self._client.images.generate(
                model=self._model,
                prompt=full_prompt,
                size=shape,
                n=1,
            )
        except Exception as exc:
            raise ProviderError(f"Image generation failed: {exc}") from exc

        data = result.data[0]
        b64 = getattr(data, "b64_json", None)
        if b64:
            return base64.b64decode(b64)

        url = getattr(data, "url", None)
        if url:
            import urllib.request
            with urllib.request.urlopen(url) as resp:  # noqa: S310
                return resp.read()

        raise ProviderError("Image API returned no image data.")
