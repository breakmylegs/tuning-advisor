"""Anthropic through the Messages API, version 2026-10-21.

POST /v1/messages with output_config.format json_schema. That version rejects
temperature, top_p and top_k, so none are sent. Models from GET /v1/models,
filtered to those that support structured output.
"""

from __future__ import annotations

from typing import Any

from plugin_core.errors import PluginError

from .base import HINT_TRUNCATED, MAX_OUTPUT_TOKENS, Provider, check, text_or_raise

API_VERSION = "2026-10-21"


class AnthropicProvider(Provider):
    id = "anthropic"
    name = "Anthropic"
    base_url = "https://api.anthropic.com"

    def _headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "anthropic-version": API_VERSION}

    def list_models(self, key: str) -> list[dict[str, str]]:
        data = check(self.client(self._headers(key)).get("v1/models", params={"limit": 1000}))
        out = []
        for item in data.get("data") or []:
            if item.get("lifecycle") not in (None, "active"):
                continue
            support = ((item.get("capabilities") or {}).get("structured_outputs") or {}).get("supported")
            if support is False:
                continue
            model_id = str(item.get("id") or "")
            if model_id:
                out.append({"id": model_id, "label": str(item.get("display_name") or model_id)})
        return out

    def generate(self, key: str, model: str, system: str, user: str, schema: dict[str, Any]) -> str:
        body = {
            "model": model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        data = check(self.client(self._headers(key)).post("v1/messages", json_body=body))
        if data.get("stop_reason") == "max_tokens":
            raise PluginError("bad_response", "max_tokens", hint=HINT_TRUNCATED)
        if data.get("stop_reason") == "refusal":
            raise PluginError("bad_response", "refusal", hint="The model declined to answer. Try another model.")
        text = "".join(block.get("text") or "" for block in data.get("content") or [] if block.get("type") == "text")
        return text_or_raise(text)
