"""Optional AI recommendations. Button-triggered, display only, unverified."""

from .anthropic import AnthropicProvider
from .gemini import GeminiProvider
from .openai import OpenAIProvider

PROVIDERS = {p.id: p for p in (OpenAIProvider, AnthropicProvider, GeminiProvider)}
SECRET_NAMES = {"openai": "openai_api_key", "anthropic": "anthropic_api_key", "gemini": "gemini_api_key"}
