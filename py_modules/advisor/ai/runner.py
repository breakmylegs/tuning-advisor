"""Run one AI recommendation: cap, cache, call, check, validate.

Triggered only by the Generate button. The result is labelled AI generated
and unverified, shown next to the source reports, and never acted on.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

from plugin_core.errors import PluginError, classify
from plugin_core.secrets import SecretStore
from plugin_core.settings import atomic_write_json, read_json

from .. import compat, recommend
from ..cache import SourceCache
from ..registry import Registry
from . import PROVIDERS, SECRET_NAMES
from .base import RECOMMENDATION_SCHEMA, Provider
from .prompt import SYSTEM, build, parse_reply, to_recommendation

LABEL = "AI generated, unverified"
CACHE_SOURCE = "ai"


class AiRunner:
    def __init__(self, secrets: SecretStore, cache: SourceCache, runtime_dir: str,
                 providers: dict[str, Provider] | None = None, now: Callable[[], float] = time.time):
        self.secrets = secrets
        self.cache = cache
        self.usage_path = os.path.join(runtime_dir, "ai_usage.json")
        self.providers = providers or {pid: cls() for pid, cls in PROVIDERS.items()}
        self._now = now

    # Keys and models

    def provider(self, provider_id: str) -> Provider:
        found = self.providers.get(provider_id)
        if not found:
            raise PluginError("bad_response", "provider", hint="Pick a provider first.")
        return found

    def key(self, provider_id: str) -> str:
        key = self.secrets.get(SECRET_NAMES.get(provider_id, ""))
        if not key:
            name = self.provider(provider_id).name
            raise PluginError("auth", "no key", hint=f"Add your {name} API key in settings first.")
        return key

    def providers_view(self) -> list[dict[str, Any]]:
        view = self.secrets.public_view()
        return [{"id": pid, "name": p.name, "key": view.get(SECRET_NAMES[pid], {"set": False, "masked": ""})}
                for pid, p in self.providers.items()]

    def list_models(self, provider_id: str) -> list[dict[str, str]]:
        """Blocking."""
        return self.provider(provider_id).list_models(self.key(provider_id))

    # Daily cap

    def _today(self) -> str:
        return datetime.fromtimestamp(self._now(), timezone.utc).strftime("%Y-%m-%d")

    def used_today(self) -> int:
        raw = read_json(self.usage_path)
        if isinstance(raw, dict) and raw.get("date") == self._today() and isinstance(raw.get("count"), int):
            return raw["count"]
        return 0

    def _count(self) -> None:
        atomic_write_json(self.usage_path, {"date": self._today(), "count": self.used_today() + 1})

    # Generate

    @staticmethod
    def cache_key(game: dict[str, Any], device: dict[str, Any], selected: dict[str, str], provider_id: str, model: str) -> str:
        ident = {"app": game.get("appid") or f"name:{(game.get('name') or '').casefold()}", "build": game.get("build_id"),
                 "device": device.get("id"), "stack": dict(sorted(selected.items())), "provider": provider_id, "model": model}
        return hashlib.sha256(json.dumps(ident, sort_keys=True).encode("utf-8")).hexdigest()

    def generate(self, provider_id: str, model: str, daily_cap: int, game: dict[str, Any], device: dict[str, Any],
                 selected: dict[str, str], registry: Registry, reports: list[dict[str, Any]],
                 current_compat: dict[str, str]) -> dict[str, Any]:
        """Blocking. Never raises. Returns a result for the panel."""
        base = {"label": LABEL, "provider": provider_id, "model": model, "cached": False, "rec": None,
                "discarded": [], "error": None, "generated_at": None}
        try:
            if not model:
                raise PluginError("bad_response", "model", hint="Load the model list and pick a model first.")
            provider = self.provider(provider_id)
            key = self.key(provider_id)
            cache_key = self.cache_key(game, device, selected, provider_id, model)
            hit = self.cache.get(CACHE_SOURCE, cache_key)
            if hit and self.cache.fresh(hit[1]):
                text, stored = hit[0], hit[1]
                base["cached"] = True
            else:
                if daily_cap and self.used_today() >= daily_cap:
                    raise PluginError("http_error", "cap",
                                      hint=f"Daily limit of {daily_cap} AI requests reached. Raise it in settings or try tomorrow.")
                names = {t["id"]: t["name"] for t in registry.tools}
                user = build(game, device, selected, names, reports)
                self._count()
                text = provider.generate(key, model, SYSTEM, user, RECOMMENDATION_SCHEMA)
                stored = self._now()
            data = parse_reply(text)
            rec, discarded = to_recommendation(data, device)
            if not base["cached"]:
                self.cache.put(CACHE_SOURCE, cache_key, text)
            checked = recommend.validate(rec, device, selected)
            final = recommend.translate(checked, registry, device, selected)
            final["compat_section"] = compat.section(final, current_compat, selected, bool(game.get("shortcut")))
            base.update(rec=final, discarded=discarded, generated_at=stored)
        except ValueError as err:
            base["error"] = {"kind": "bad_response", "message": f"{err} Try again or pick another model."}
        except Exception as exc:  # noqa: BLE001, classified
            base["error"] = classify(exc).to_dict()
        return base
