"""Tuning advisor backend.

Read only. It detects the device and tools, fetches community reports, and
returns recommendations. It never writes to Steam, other plugins, system
services or game files. Its own settings and cache are the only files it writes.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping

from plugin_core.errors import classify
from plugin_core.http import fetch_json
from plugin_core.settings import JsonStore
from plugin_core.update_check import UpdateChecker, load_build_info

from . import compat, deckverified, device as devmod, recommend, registry as regmod, stack as stackmod
from .cache import SourceCache

Emit = Callable[..., Awaitable[None]]

DEFAULTS: dict[str, Any] = {
    "device_override": "",
    "stack_overrides": {},
    "source_deckverified": True,
    "workload": "medium",
    "update_check": True,
    "remove_data_on_uninstall": False,
}

# Non-Steam shortcuts carry app IDs above this. Their reports are matched by name.
SHORTCUT_APPID_MIN = 2 ** 31


class AdvisorService:
    plugin_id = "tuning-advisor"

    def __init__(self, settings_dir: str, runtime_dir: str, plugin_dir: str, decky_home: str, user_home: str,
                 user: str, version: str, emit: Emit, logger: Any, root: str = "/",
                 fetch_reports: Callable[[int | None, str | None], dict] = deckverified.fetch):
        self.settings = JsonStore(os.path.join(settings_dir, "settings.json"), DEFAULTS)
        self.registry = regmod.load(os.path.join(plugin_dir, "registry"))
        self.cache = SourceCache(runtime_dir)
        self.decky_home = decky_home
        self.user_home = user_home
        self.user = user
        self.root = root
        self.version = version
        self._emit = emit
        self.log = logger
        self._fetch_reports = fetch_reports
        self.updates = UpdateChecker(load_build_info(plugin_dir), version, os.path.join(runtime_dir, "update.json"), fetch_json)
        self.update_info: dict[str, Any] | None = None
        self._update_task: asyncio.Task | None = None
        self.facts: dict[str, Any] = {}
        self.device: dict[str, Any] = devmod.generic_profile({})
        self.device_how = "generic"
        self.detected: dict[str, Any] = {"tools": [], "os": {"id": "other", "pretty": "", "version": ""}}
        self.game: dict[str, Any] | None = None
        # Read from the Steam client by the frontend, for display and merging only.
        self.current_compat: dict[str, str] = {"launch_options": "", "compat_tool": ""}
        self.reports: list[dict[str, Any]] = []
        self.source_state: dict[str, Any] = {"cached": False, "error": None, "fetched_at": None, "enabled": True}
        self._lock = asyncio.Lock()

    # Lifecycle

    async def start(self) -> None:
        await asyncio.to_thread(self.detect)
        self._update_task = asyncio.get_event_loop().create_task(self._update_loop())

    async def stop(self) -> None:
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
            self._update_task = None

    async def uninstall(self) -> None:
        if self.settings.get("remove_data_on_uninstall"):
            self.settings.delete_file()
            self.cache.clear()

    async def _update_loop(self) -> None:
        while True:
            await self.check_update()
            await asyncio.sleep(60 * 60)

    async def check_update(self, force: bool = False) -> dict[str, Any] | None:
        if not self.settings.get("update_check") and not force:
            self.update_info = None
            return None
        self.update_info = await asyncio.to_thread(self.updates.check, force)
        await self._emit("update", self.update_info)
        return self.update_info

    # Detection

    def detect(self) -> None:
        """Blocking. Reads DMI, cpuinfo, os-release and plugin manifests."""
        self.facts = devmod.read_facts(self.root)
        self.device, self.device_how = devmod.resolve(self.registry, self.facts, self.settings.get("device_override"))
        self.detected = stackmod.detect(self.registry, self.decky_home, self.user_home, self.user, self.device, self.root)
        self.log.info("device %s (%s), %d tools", self.device["id"], self.device_how, len(self.detected["tools"]))

    def selected(self) -> dict[str, str]:
        return stackmod.select(self.registry, self.detected, self.settings.get("stack_overrides"))

    # Game and reports

    async def set_game(self, appid: int | None, name: str, build_id: int | None = None, shortcut: bool = False,
                       launch_options: str = "", compat_tool: str = "") -> dict[str, Any]:
        appid = int(appid) if appid else None
        self.set_current_compat(launch_options, compat_tool)
        if appid and appid >= SHORTCUT_APPID_MIN:
            shortcut = True
        self.game = {"appid": None if shortcut else appid, "shortcut_appid": appid if shortcut else None,
                     "name": str(name or "")[:200], "build_id": int(build_id) if build_id else None,
                     "shortcut": bool(shortcut)}
        await self.load_reports(force=False)
        return self.view()

    def _cache_key(self) -> str:
        game = self.game or {}
        ident = f"app:{game['appid']}" if game.get("appid") else f"name:{game.get('name', '').casefold()}"
        return f"{ident}:build:{game.get('build_id') or ''}"

    async def load_reports(self, force: bool) -> None:
        async with self._lock:
            self.reports = []
            enabled = bool(self.settings.get("source_deckverified"))
            self.source_state = {"cached": False, "error": None, "fetched_at": None, "enabled": enabled}
            if not self.game or not enabled:
                return
            game = self.game
            if not game.get("appid") and not game.get("name"):
                return
            key = self._cache_key()
            cached = self.cache.get(deckverified.SOURCE, key)
            if cached and not force and self.cache.fresh(cached[1]):
                self._use(cached[0], cached[1], from_cache=True)
                return
            try:
                raw = await asyncio.to_thread(self._fetch_reports, game.get("appid"), None if game.get("appid") else game.get("name"))
            except Exception as exc:  # noqa: BLE001, classified
                err = classify(exc)
                self.log.warning("deck verified fetch failed: %s", err.kind)
                if cached:
                    self._use(cached[0], cached[1], from_cache=True)
                    self.source_state["error"] = err.to_dict()
                else:
                    self.source_state["error"] = err.to_dict()
                return
            self.cache.put(deckverified.SOURCE, key, raw)
            self._use(raw, datetime.now(timezone.utc).timestamp(), from_cache=False)

    def _use(self, raw: Any, stored_at: float, from_cache: bool) -> None:
        reports = raw.get("reports") if isinstance(raw, dict) else None
        self.reports = [deckverified.normalise(r) for r in reports or [] if isinstance(r, dict)]
        self.source_state["cached"] = from_cache
        self.source_state["fetched_at"] = stored_at

    def set_current_compat(self, launch_options: str = "", compat_tool: str = "") -> None:
        self.current_compat = {"launch_options": compat.clean(launch_options), "compat_tool": compat.clean(compat_tool)}

    def recommendations(self) -> list[dict[str, Any]]:
        low = bool(self.game and self.game.get("shortcut"))
        selected = self.selected()
        recs = recommend.build(self.reports, self.registry, self.device, selected, self.settings.get("workload"), low)
        for rec in recs:
            rec["compat_section"] = compat.section(rec, self.current_compat, selected, low)
        return recs

    # Frontend API

    def view(self) -> dict[str, Any]:
        selected = self.selected()
        names = {t["id"]: t["name"] for t in self.registry.tools}
        return {
            "version": self.version,
            "settings": self.settings.snapshot(),
            "device": {
                "id": self.device["id"],
                "name": f"{self.device.get('vendor', '')} {self.device.get('model', '')}".strip(),
                "apu": self.device.get("apu", ""),
                "how": self.device_how,
                "generic": bool(self.device.get("generic")),
                "verified": bool(self.device.get("verified")),
                "facts": devmod.public_facts(self.facts),
            },
            "devices": [{"id": d["id"], "name": f"{d['vendor']} {d['model']} ({d['apu']})"} for d in self.registry.devices],
            "os": self.detected["os"],
            "stack": {
                "detected": self.detected["tools"],
                "selected": selected,
                "names": names,
                "categories": self.registry.categories,
                "options": {c: [t["id"] for t in self.registry.tools_for(c)] for c in self.registry.categories},
            },
            "conflicts": stackmod.conflicts(self.registry, self.detected, self.device),
            "game": self.game,
            "source": self.source_state,
            "recommendations": self.recommendations() if self.game else [recommend.fallback(self.device, self.settings.get("workload"))],
            "update": self.update_info,
        }

    async def refresh(self) -> dict[str, Any]:
        await self.load_reports(force=True)
        return self.view()

    async def redetect(self) -> dict[str, Any]:
        await asyncio.to_thread(self.detect)
        return self.view()

    async def save_settings(self, values: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(values, Mapping):
            raise ValueError("settings must be an object")
        values = dict(values)
        if "device_override" in values and values["device_override"] and not self.registry.device(values["device_override"]):
            raise ValueError("unknown device")
        if "workload" in values and values["workload"] not in regmod.WORKLOADS:
            raise ValueError("workload must be light, medium or heavy")
        if "stack_overrides" in values:
            overrides = values["stack_overrides"]
            if not isinstance(overrides, Mapping):
                raise ValueError("stack overrides must be an object")
            for category, choice in overrides.items():
                if category not in self.registry.categories:
                    raise ValueError(f"unknown category {category}")
                valid = {stackmod.AUTO, stackmod.NONE} | {t["id"] for t in self.registry.tools_for(category)}
                if choice not in valid:
                    raise ValueError(f"unknown tool for {category}")
            values["stack_overrides"] = dict(overrides)
        changed = self.settings.update(values)
        if "device_override" in changed:
            await asyncio.to_thread(self.detect)
        if "source_deckverified" in changed:
            await self.load_reports(force=False)
        return self.view()

    def clear_cache(self) -> dict[str, Any]:
        removed = self.cache.clear()
        return {"ok": True, "removed": removed}
