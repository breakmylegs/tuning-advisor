"""OpenAI through the Responses API, the surface OpenAI recommends for new work.

POST /v1/responses with text.format json_schema (strict). Models from GET /v1/models.
"""

from __future__ import annotations

import re
from typing import Any

from plugin_core.errors import PluginError

from .base import HINT_TRUNCATED, MAX_OUTPUT_TOKENS, Provider, check, text_or_raise

# Model families that do not generate text from a prompt.
NOT_TEXT = re.compile(r"(embedding|whisper|tts|dall-e|image|audio|realtime|transcribe|moderation|search|sora|codex-mini)", re.I)
TEXT = re.compile(r"^(gpt-|o\d|chatgpt-)", re.I)


class OpenAIProvider(Provider):
    id = "openai"
    name = "OpenAI"
    base_url = "https://api.openai.com"

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}"}

    def list_models(self, key: str) -> list[dict[str, str]]:
        data = check(self.client(self._headers(key)).get("v1/models"))
        out = []
        for item in data.get("data") or []:
            model_id = str(item.get("id") or "")
            if TEXT.match(model_id) and not NOT_TEXT.search(model_id):
                out.append({"id": model_id, "label": model_id})
        return sorted(out, key=lambda m: m["id"])

    def generate(self, key: str, model: str, system: str, user: str, schema: dict[str, Any]) -> str:
        body = {
            "model": model,
            "instructions": system,
            "input": user,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "text": {"format": {"type": "json_schema", "name": "recommendation", "schema": schema, "strict": True}},
        }
        data = check(self.client(self._headers(key)).post("v1/responses", json_body=body))
        if data.get("status") == "incomplete":
            raise PluginError("bad_response", "incomplete", hint=HINT_TRUNCATED)
        parts = []
        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if content.get("type") == "refusal":
                    raise PluginError("bad_response", "refusal", hint="The model declined to answer. Try another model.")
                if content.get("type") == "output_text":
                    parts.append(content.get("text") or "")
        return text_or_raise("".join(parts) or data.get("output_text"))
