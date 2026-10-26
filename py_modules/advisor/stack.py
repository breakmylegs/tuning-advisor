"""Detect installed tuning tools, apply overrides, and find conflicts.

Reads only: other plugins' plugin.json files, Decky's loader settings for the
disabled list, /etc/os-release, and whether some paths exist. Never writes.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any

from .registry import Registry

NONE = "none"
AUTO = "auto"


def normalise(name: str) -> str:
    """Casefold and keep letters and digits, as Legion Go 2 Companion does."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def installed_plugins(decky_home: str) -> dict[str, dict[str, Any]]:
    """{normalised name: {"name", "disabled", "folder"}} for every installed plugin.
    The folder name is also the plugin's settings folder under <DECKY_HOME>/settings."""
    disabled: set[str] = set()
    try:
        with open(os.path.join(decky_home, "settings", "loader.json"), encoding="utf-8") as handle:
            raw = json.load(handle).get("disabled_plugins") or []
        disabled = {normalise(n) for n in raw if isinstance(n, str)}
    except (OSError, ValueError, AttributeError):
        pass
    out: dict[str, dict[str, Any]] = {}
    for manifest in sorted(glob.glob(os.path.join(decky_home, "plugins", "*", "plugin.json"))):
        try:
            with open(manifest, encoding="utf-8") as handle:
                name = json.load(handle).get("name")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(name, str) and name.strip():
            key = normalise(name)
            out[key] = {"name": name, "disabled": key in disabled,
                        "folder": os.path.basename(os.path.dirname(manifest))}
    return out


def read_os(root: str = "/") -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        with open(os.path.join(root, "etc", "os-release"), encoding="utf-8") as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                if sep:
                    values[key] = value.strip().strip('"')
    except OSError:
        pass
    os_id = values.get("ID", "").casefold()
    variant = values.get("VARIANT_ID", "").casefold()
    if os_id == "steamos":
        name = "steamos"
    elif os_id == "bazzite" or "bazzite" in values.get("ID_LIKE", "").casefold():
        name = "bazzite"
    elif os_id == "chimeraos":
        name = "chimeraos"
    elif os_id == "cachyos" and ("handheld" in variant or "deckify" in variant):
        name = "cachyos-handheld"
    else:
        name = "other"
    return {"id": name, "pretty": values.get("PRETTY_NAME", ""), "version": values.get("VERSION_ID", "")}


def _path_exists(root: str, path: str, user: str) -> bool:
    path = path.replace("{user}", user)
    return os.path.exists(os.path.join(root, path.lstrip("/")))


def detect(registry: Registry, decky_home: str, user_home: str, user: str, device: dict[str, Any],
           root: str = "/") -> dict[str, Any]:
    plugins = installed_plugins(decky_home)
    found: list[dict[str, Any]] = []
    for tool in registry.tools:
        rules = tool.get("detect") or {}
        hit = False
        disabled = False
        folder = None
        for name in rules.get("plugin_names") or []:
            entry = plugins.get(normalise(name))
            if entry:
                hit = True
                disabled = entry["disabled"]
                folder = entry["folder"]
                break
        if not hit:
            for path in rules.get("paths") or []:
                if _path_exists(root, path, user):
                    hit = True
                    break
        if hit and rules.get("steam_native") and not device.get("steam_native_tdp"):
            hit = False
        if hit and not disabled:
            extra = [p for p in rules.get("home_paths") or [] if os.path.exists(os.path.join(user_home, p))]
            found.append({"id": tool["id"], "home_paths_found": extra, "folder": folder})
        elif hit and disabled:
            found.append({"id": tool["id"], "disabled": True})
    return {"tools": found, "os": read_os(root)}


def active_ids(detected: dict[str, Any]) -> list[str]:
    return [t["id"] for t in detected["tools"] if not t.get("disabled")]


def select(registry: Registry, detected: dict[str, Any], overrides: dict[str, str]) -> dict[str, str]:
    """Pick one tool per category. Manual choice wins. Otherwise prefer a plugin
    over Steam's own control, because a plugin re-applies its value."""
    active = active_ids(detected)
    chosen: dict[str, str] = {}
    for category in registry.categories:
        manual = overrides.get(category, AUTO)
        if manual and manual != AUTO:
            chosen[category] = manual if manual == NONE or registry.tool(manual) else NONE
            continue
        candidates = [t["id"] for t in registry.tools_for(category) if t["id"] in active]
        plugins_first = [c for c in candidates if c != "steam-native"] + [c for c in candidates if c == "steam-native"]
        chosen[category] = plugins_first[0] if plugins_first else NONE
    return chosen


def conflicts(registry: Registry, detected: dict[str, Any], device: dict[str, Any]) -> list[dict[str, str]]:
    active = active_ids(detected)
    power = [t for t in active if "power" in (registry.tool(t) or {}).get("categories", [])]
    plugin_power = [t for t in power if t != "steam-native"]
    names = {t["id"]: t["name"] for t in registry.tools}
    out: list[dict[str, str]] = []
    if len(plugin_power) > 1:
        listed = " and ".join(names[t] for t in plugin_power)
        out.append({
            "kind": "multiple_power",
            "text": f"{listed} are both active. They will override each other's TDP. Disable all but one.",
        })
    if "legotdp" in plugin_power and "steam-native" in power:
        out.append({
            "kind": "legotdp_reapply",
            "text": "LeGoTDP re-applies its values every 5 s, so changes to Steam's TDP limit are reverted while it runs.",
        })
    if not power and not device.get("steam_native_tdp"):
        options = [t["name"] for t in registry.tools_for("power") if t["id"] != "steam-native" and _supports(t, device)]
        out.append({
            "kind": "no_power",
            "text": "No power tool found, and this device has no native TDP control. Consider: " + ", ".join(options) + ".",
        })
    return out


def _supports(tool: dict[str, Any], device: dict[str, Any]) -> bool:
    devices = tool.get("devices", "all")
    return devices == "all" or device.get("family") in devices
