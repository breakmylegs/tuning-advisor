"""One interface for the AI providers. urllib only, no SDKs.

Every call runs in the plugin's Python backend, so API keys never reach the
Steam client's JavaScript. Output is display only and can never trigger an
action. No sampling parameters are sent: Anthropic's 2026-10-21 API version
rejects them and Gemini ignores them.
"""

from __future__ import annotations

from typing import Any

from plugin_core.errors import AUTH, BAD_RESPONSE, HTTP_ERROR, PluginError
from plugin_core.http import HttpClient, Response, parse_base_url

TIMEOUT = 60.0
# Current models think before they answer, and OpenAI and Gemini count that
# against this limit. 1500 ran out before the JSON was finished on most
# replies. The prompt still asks for a short answer, so cost stays small.
MAX_OUTPUT_TOKENS = 8192

HINT_401 = "The provider rejected the API key. Check it in settings, or create a new one."
HINT_403 = "The provider refused this request. Check the key's permissions and that the model is enabled for it."
HINT_404 = "The provider does not know this model. Load the model list again and pick another."
HINT_429 = "Rate or spending limit reached. Wait a while, or raise the limit in your provider account."
HINT_5XX = "The provider is having problems. Try again later."
HINT_TRUNCATED = "The reply was cut off before it finished. Try again, or pick a faster model such as a Flash or mini one."


def check(res: Response) -> Any:
    """Map provider failures to plain-language errors. Never includes the key."""
    if res.status == 401:
        raise PluginError(AUTH, "401", 401, hint=HINT_401)
    if res.status == 403:
        raise PluginError(AUTH, "403", 403, hint=HINT_403)
    if res.status == 404:
        raise PluginError(HTTP_ERROR, "404", 404, hint=HINT_404)
    if res.status == 429:
        raise PluginError(HTTP_ERROR, "429", 429, hint=HINT_429)
    if res.status >= 500:
        raise PluginError(HTTP_ERROR, str(res.status), res.status, hint=HINT_5XX)
    if res.status >= 400:
        raise PluginError(HTTP_ERROR, str(res.status), res.status,
                          hint=f"The provider returned HTTP {res.status}. Try another model.")
    return res.json()


class Provider:
    id = ""
    name = ""
    base_url = ""

    def __init__(self, base_url: str | None = None):
        # Tests point base_url at a local server with recorded replies.
        self.base = parse_base_url(base_url or self.base_url)

    def client(self, headers: dict[str, str]) -> HttpClient:
        return HttpClient(self.base, timeout=TIMEOUT, headers=headers)

    def list_models(self, key: str) -> list[dict[str, str]]:
        raise NotImplementedError

    def generate(self, key: str, model: str, system: str, user: str, schema: dict[str, Any]) -> str:
        """Return the model's text reply. Blocking. Call through asyncio.to_thread."""
        raise NotImplementedError


def nullable(kind: str) -> dict[str, Any]:
    return {"type": [kind, "null"]}


def obj(props: dict[str, Any]) -> dict[str, Any]:
    # Strict structured output needs every property required and nothing extra.
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


RECOMMENDATION_SCHEMA = obj({
    "power": obj({"tdp_w": nullable("integer"), "gpu_clock_mhz": nullable("integer")}),
    "display": obj({"refresh_hz": nullable("integer"), "fps_cap": nullable("integer"), "vrr": nullable("boolean")}),
    "scaling": obj({"steam_filter": nullable("string"), "game_resolution": nullable("string")}),
    "upscaler": obj({"name": nullable("string"), "mode": nullable("string")}),
    "frame_gen": obj({"tool": nullable("string"), "mode": nullable("string")}),
    "in_game": obj({
        "preset": nullable("string"),
        "settings": {"type": "array", "items": obj({"name": {"type": "string"}, "value": {"type": "string"}})},
    }),
    "compat": obj({"proton": nullable("string"), "launch_options": nullable("string")}),
    "notes": {"type": "string"},
})


def text_or_raise(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        raise PluginError(BAD_RESPONSE, "empty", hint="The provider returned no text. Try again or pick another model.")
    return text
