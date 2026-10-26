"""Google Gemini through generateContent.

generationConfig.responseFormat carries the JSON schema. responseSchema is
deprecated. If a model rejects responseFormat with HTTP 400, retry once with
responseMimeType and responseJsonSchema. Models from GET /v1beta/models.
"""

from __future__ import annotations

import re
from typing import Any

from plugin_core.errors import PluginError

from .base import HINT_TRUNCATED, MAX_OUTPUT_TOKENS, Provider, check, text_or_raise

NOT_TEXT = re.compile(r"(embedding|aqa|imagen|veo|tts|image|audio|live|robotics)", re.I)


class GeminiProvider(Provider):
    id = "gemini"
    name = "Google Gemini"
    base_url = "https://generativelanguage.googleapis.com"

    def _headers(self, key: str) -> dict[str, str]:
        return {"x-goog-api-key": key}

    def list_models(self, key: str) -> list[dict[str, str]]:
        data = check(self.client(self._headers(key)).get("v1beta/models", params={"pageSize": 1000}))
        out = []
        for item in data.get("models") or []:
            name = str(item.get("name") or "")
            model_id = name.split("/", 1)[1] if name.startswith("models/") else name
            methods = item.get("supportedGenerationMethods") or []
            if model_id and "generateContent" in methods and not NOT_TEXT.search(model_id):
                out.append({"id": model_id, "label": str(item.get("displayName") or model_id)})
        return out

    def _body(self, system: str, user: str, schema: dict[str, Any], legacy: bool) -> dict[str, Any]:
        config: dict[str, Any] = {"maxOutputTokens": MAX_OUTPUT_TOKENS}
        if legacy:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = schema
        else:
            config["responseFormat"] = {"text": {"mimeType": "APPLICATION_JSON", "schema": schema}}
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }

    def generate(self, key: str, model: str, system: str, user: str, schema: dict[str, Any]) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
            raise PluginError("bad_response", "model id", hint="That model name is not valid. Load the model list again.")
        client = self.client(self._headers(key))
        path = f"v1beta/models/{model}:generateContent"
        res = client.post(path, json_body=self._body(system, user, schema, legacy=False))
        if res.status == 400:
            res = client.post(path, json_body=self._body(system, user, schema, legacy=True))
        data = check(res)
        candidates = data.get("candidates") or []
        if not candidates:
            raise PluginError("bad_response", "no candidates",
                              hint="The provider returned no answer, possibly blocked by its safety filter. Try another model.")
        first = candidates[0]
        if first.get("finishReason") == "MAX_TOKENS":
            raise PluginError("bad_response", "max_tokens", hint=HINT_TRUNCATED)
        text = "".join(p.get("text") or "" for p in (first.get("content") or {}).get("parts") or [])
        return text_or_raise(text)
