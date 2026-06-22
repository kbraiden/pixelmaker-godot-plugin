"""Pluggable AI image-provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """Raised when image generation fails or is unavailable."""


class ImageProvider(ABC):
    """Abstract base class for text-to-image providers."""

    name: str = "base"

    @abstractmethod
    def generate(self, prompt: str, style: str = "sprite") -> bytes:
        """Generate an image from a text prompt and return raw image bytes."""
        raise NotImplementedError


def get_provider(api_key: str | None = None) -> ImageProvider:
    """Return the configured provider, or raise ProviderError if unavailable."""
    from ..config import settings
    from .openai_provider import OpenAIProvider

    key = api_key or settings.openai_api_key
    if not key:
        raise ProviderError(
            "No API key provided. Enter your own OpenAI API key in the plugin "
            "(see the API Key field), or have the host set OPENAI_API_KEY. "
            "Image upload conversion still works without a key."
        )
    return OpenAIProvider(api_key=key)
