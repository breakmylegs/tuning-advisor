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
from plugin_core.secrets import SecretStore, import_path, read_import_file
from plugin_core.settings import JsonStore
from plugin_core.update_check import UpdateChecker, load_build_info

from . import compat, current, deckverified, device as devmod, pcgw, protondb, recommend, registry as regmod, stack as stackmod
from .ai import PROVIDERS, SECRET_NAMES
from .ai.runner import AiRunner
from .cache import SourceCache

Emit = Callable[..., Awaitable[None]]

DEFAULTS: dict[str, Any] = {
    "device_override": "",
    "stack_overrides": {},
    "source_deckverified": True,
    "workload": "medium",
    "update_check": True,
    "remove_data_on_uninstall": False,
    "ai_provider": "",
    "ai_model": "",
    "ai_daily_cap": 0,
    "source_protondb": False,
    "source_pcgw": False,
    "pcgw_username": "",
}
AI_SECRETS = tuple(SECRET_NAMES.values())
PCGW_SECRET = "pcgw_bot_password"

# Non-Steam shortcuts carry app IDs above this. Their reports are matched by name.
SHORTCUT_APPID_MIN = 2 ** 31


class AdvisorService:
    plugin_id = "tuning-advisor"

    def __init__(self, settings_dir: str, runtime_dir: str, plugin_dir: str, decky_home: str, user_home: str,
                 user: str, version: str, emit: Emit, logger: Any, root: str = "/",
                 fetch_reports: Callable[[int | None, str | None], dict] = deckverified.fetch,
                 ai_providers: dict | None = None,
                 protondb_fetch: Callable[[str], bytes] = protondb.download,
                 pcgw_factory: Callable[..., Any] = pcgw.PcgwClient):
        self.settings = JsonStore(os.path.join(settings_dir, "settings.json"), DEFAULTS)
        self.secrets = SecretStore(os.path.join(settings_dir, "secrets.json"), AI_SECRETS + (PCGW_SECRET,))
        self.registry = regmod.load(os.path.join(plugin_dir, "registry"))
        self.cache = SourceCache(runtime_dir)
        self.ai = AiRunner(self.secrets, self.cache, runtime_dir, ai_providers)
        self.ai_result: dict[str, Any] | None = None
        self.decky_home = decky_home
        self.user_home = user_home
        self.user = user
        self.root = root
        self.version = version
        self._emit = emit
        self.log = logger
        self._fetch_reports = fetch_reports
        build_info = load_build_info(plugin_dir)
        self.updates = UpdateChecker(build_info, version, os.path.join(runtime_dir, "update.json"), fetch_json)
        self.protondb = protondb.ProtonDbIndex(runtime_dir, protondb.index_url(build_info.get("monorepo", "")),
                                               fetch=protondb_fetch)
        self._pcgw_factory = pcgw_factory
        self._pcgw_ua = pcgw.user_agent(version, build_info.get("monorepo", ""))
        self.pdb_reports: list[dict[str, Any]] = []
        self.pdb_state: dict[str, Any] = {"enabled": False, "error": None, "summary": None, "dump": None}
        self.pcgw_data: dict[str, Any] | None = None
        self.pcgw_state: dict[str, Any] = {"enabled": False, "error": None, "cached": False}
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
            self.secrets.delete_file()
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
        self.ai_result = None
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
        await self._load_deckverified(force)
        await self._load_protondb()
        await self._load_pcgw(force)

    async def _load_protondb(self) -> None:
        enabled = bool(self.settings.get("source_protondb"))
        self.pdb_reports = []
        self.pdb_state = {"enabled": enabled, "error": None, "summary": None, "dump": None}
        appid = (self.game or {}).get("appid")
        if not enabled or not appid:
            return
        try:
            header = await asyncio.to_thread(self.protondb.ensure)
            entry = await asyncio.to_thread(self.protondb.lookup, appid)
        except Exception as exc:  # noqa: BLE001, classified
            err = classify(exc)
            self.log.warning("protondb index failed: %s", err.kind)
            self.pdb_state["error"] = err.to_dict()
            return
        self.pdb_state["dump"] = header.get("dump")
        self.pdb_state["summary"] = protondb.summary(entry, header)
        self.pdb_reports = protondb.normalise(entry, appid) if entry else []

    async def _load_pcgw(self, force: bool) -> None:
        enabled = bool(self.settings.get("source_pcgw"))
        self.pcgw_data = None
        self.pcgw_state = {"enabled": enabled, "error": None, "cached": False}
        game = self.game or {}
        if not enabled or not (game.get("appid") or game.get("name")):
            return
        key = "pcgw:" + self._cache_key()
        cached = self.cache.get(pcgw.SOURCE, key)
        if cached and not force and self.cache.fresh(cached[1]):
            self.pcgw_data, self.pcgw_state["cached"] = cached[0], True
            return
        client = self._pcgw_factory(self.settings.get("pcgw_username"), self.secrets.get(PCGW_SECRET), self._pcgw_ua)
        try:
            data = await asyncio.to_thread(client.game, game.get("appid"),
                                           None if game.get("appid") else game.get("name"))
        except Exception as exc:  # noqa: BLE001, classified
            err = classify(exc)
            self.log.warning("pcgamingwiki failed: %s", err.kind)
            self.pcgw_state["error"] = err.to_dict()
            if cached:
                self.pcgw_data, self.pcgw_state["cached"] = cached[0], True
            return
        self.cache.put(pcgw.SOURCE, key, data)
        self.pcgw_data = data

    async def _load_deckverified(self, force: bool) -> None:
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
                self.log.warning("deck verified fetch failed: %s %s", err.kind, err.detail)
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

    def current_values(self, selected: dict[str, str]) -> dict[str, Any]:
        """What the user's own tools are set to for this game. Read only."""
        game = self.game or {}
        appid = game.get("appid") or game.get("shortcut_appid")
        return current.read(selected, self.detected, self.decky_home, self.user_home, appid)

    def set_current_compat(self, launch_options: str = "", compat_tool: str = "") -> None:
        self.current_compat = {"launch_options": compat.clean(launch_options), "compat_tool": compat.clean(compat_tool)}

    def recommendations(self) -> list[dict[str, Any]]:
        low = bool(self.game and self.game.get("shortcut"))
        selected = self.selected()
        # With no game there are no reports, only general guidance. It still goes
        # through the full pipeline, because the panel reads its lines and compat.
        reports = self.reports + self.pdb_reports if self.game else []
        recs = recommend.build(reports, self.registry, self.device, selected, self.settings.get("workload"), low)
        listed = (self.pcgw_data or {}).get("upscaling") or []
        for rec in recs:
            rec["compat_section"] = compat.section(rec, self.current_compat, selected, low)
            name = (rec.get("upscaler") or {}).get("name")
            if name and listed and not pcgw.upscaler_supported(name, listed):
                rec["flags"].append(f"PCGamingWiki does not list {name} for this game. It lists {', '.join(listed)}.")
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
            "current": self.current_values(selected),
            "protondb": self.pdb_state,
            "pcgw": dict(self.pcgw_state, data=self.pcgw_data, has_password=self.secrets.has(PCGW_SECRET)),
            "recommendations": self.recommendations(),
            "update": self.update_info,
            "ai": {
                "providers": self.ai.providers_view(),
                "used_today": self.ai.used_today(),
                "result": self.ai_result,
            },
            "import_path": import_path(self.user_home, self.plugin_id),
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
        if "ai_provider" in values and values["ai_provider"] not in ("", *PROVIDERS):
            raise ValueError("unknown AI provider")
        if "ai_daily_cap" in values:
            cap = values["ai_daily_cap"]
            if not isinstance(cap, int) or isinstance(cap, bool) or not 0 <= cap <= 1000:
                raise ValueError("daily cap must be 0 to 1000")
        if "ai_provider" in values and values["ai_provider"] != self.settings.get("ai_provider"):
            values.setdefault("ai_model", "")
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
        if {"source_deckverified", "source_protondb", "source_pcgw", "pcgw_username"} & set(changed):
            await self.load_reports(force=False)
        return self.view()

    # AI, phase 2. Button-triggered only.

    def set_secret(self, name: str, value: str) -> dict[str, Any]:
        self.secrets.set(name, value)
        return self.view()

    async def set_pcgw_password(self, value: str) -> dict[str, Any]:
        self.secrets.set(PCGW_SECRET, value)
        await self._load_pcgw(force=True)
        return self.view()

    def clear_secret(self, name: str) -> dict[str, Any]:
        self.secrets.clear(name)
        return self.view()

    async def list_models(self, provider_id: str) -> dict[str, Any]:
        try:
            models = await asyncio.to_thread(self.ai.list_models, provider_id)
        except Exception as exc:  # noqa: BLE001, classified
            return {"ok": False, "error": classify(exc).to_dict()}
        return {"ok": True, "models": models}

    async def generate_ai(self) -> dict[str, Any]:
        if not self.game:
            self.ai_result = {"error": {"kind": "bad_response", "message": "Pick a game first."}, "rec": None}
            return self.view()
        self.ai_result = await asyncio.to_thread(
            self.ai.generate, self.settings.get("ai_provider"), self.settings.get("ai_model"),
            self.settings.get("ai_daily_cap"), self.game, self.device, self.selected(), self.registry,
            self.reports, self.current_compat)
        return self.view()

    def import_from_file(self) -> dict[str, Any]:
        path = import_path(self.user_home, self.plugin_id)
        try:
            settings, secrets = read_import_file(path, ("ai_provider", "ai_model", "ai_daily_cap"), AI_SECRETS)
            for name, value in secrets.items():
                self.secrets.set(name, value)
            if settings:
                self.settings.update(settings)
        except ValueError as err:
            return {"ok": False, "message": str(err), "path": path}
        return {"ok": True, "imported": sorted(list(settings) + list(secrets)), "path": path, "view": self.view()}

    def delete_import_file(self) -> dict[str, Any]:
        path = import_path(self.user_home, self.plugin_id)
        try:
            os.unlink(path)
        except FileNotFoundError:
            return {"ok": True, "message": "The import file was already gone."}
        except OSError:
            return {"ok": False, "message": f"Could not delete {path}. Delete it with a file manager."}
        return {"ok": True, "message": "Import file deleted."}

    def clear_cache(self) -> dict[str, Any]:
        removed = self.cache.clear()
        return {"ok": True, "removed": removed}
