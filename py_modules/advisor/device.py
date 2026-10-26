"""Detect the handheld from DMI strings, with a generic fallback.

Reads only. Serial numbers and UUIDs are never read. `root` lets tests point
at a captured dump instead of the live filesystem.
"""

from __future__ import annotations

import glob
import os
from typing import Any

from .registry import Registry, derived_bands

DMI_FIELDS = ("sys_vendor", "product_name", "product_version", "product_family", "board_name", "board_vendor")
GPU_VENDORS = {"0x1002": "amd", "0x8086": "intel", "0x10de": "nvidia"}

GENERIC_TDP = {"min": 5, "max": 25}


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def read_facts(root: str = "/") -> dict[str, Any]:
    dmi_dir = os.path.join(root, "sys", "class", "dmi", "id")
    facts: dict[str, Any] = {f: _read(os.path.join(dmi_dir, f)) for f in DMI_FIELDS}
    cpu = ""
    for line in _read(os.path.join(root, "proc", "cpuinfo")).splitlines():
        if line.startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    facts["cpu_model"] = cpu
    vendors = []
    for vendor_file in sorted(glob.glob(os.path.join(root, "sys", "class", "drm", "card[0-9]", "device", "vendor"))):
        vendor = GPU_VENDORS.get(_read(vendor_file).lower())
        if vendor and vendor not in vendors:
            vendors.append(vendor)
    facts["gpu_vendor"] = vendors[0] if vendors else ""
    return facts


def _field_matches(actual: str, wanted: list[str]) -> bool:
    actual = actual.strip().casefold()
    return any(actual == w.strip().casefold() for w in wanted)


def match_score(entry: dict[str, Any], facts: dict[str, Any]) -> int:
    """0 when the entry does not match. Otherwise the number of conditions met,
    so the most specific entry wins."""
    score = 0
    for field, wanted in (entry.get("match") or {}).items():
        if not wanted:
            continue
        if not _field_matches(str(facts.get(field, "")), wanted):
            return 0
        score += 1
    if score == 0:
        return 0
    cpu = str(facts.get("cpu_model", "")).casefold()
    for needle in entry.get("cpu_contains") or []:
        if needle.casefold() not in cpu:
            return 0
        score += 1
    for needle in entry.get("cpu_excludes") or []:
        if needle.casefold() in cpu:
            return 0
    return score


def detect(registry: Registry, facts: dict[str, Any]) -> dict[str, Any] | None:
    best, best_score = None, 0
    for entry in registry.devices:
        score = match_score(entry, facts)
        if score > best_score:
            best, best_score = entry, score
    return best


def generic_profile(facts: dict[str, Any]) -> dict[str, Any]:
    vendor = facts.get("gpu_vendor") or "unknown"
    return {
        "id": "generic",
        "vendor": facts.get("sys_vendor") or "Unknown",
        "model": facts.get("product_version") or facts.get("product_name") or "Unknown device",
        "family": "generic",
        "apu": facts.get("cpu_model") or "Unknown",
        "gpu": {"vendor": vendor, "name": "", "arch": "", "cu": None},
        "display": {"refresh_hz_max": None, "vrr": False, "vrr_range_hz": None},
        "tdp_w": dict(GENERIC_TDP),
        "tdp_bands_w": derived_bands(GENERIC_TDP["min"], GENERIC_TDP["max"]),
        "steam_native_tdp": None,
        "report_aliases": [],
        "generic": True,
        "verified": False,
    }


def resolve(registry: Registry, facts: dict[str, Any], override: str = "") -> tuple[dict[str, Any], str]:
    """Return (device, how). how is "override", "detected" or "generic"."""
    if override:
        chosen = registry.device(override)
        if chosen:
            return chosen, "override"
    found = detect(registry, facts)
    if found:
        return found, "detected"
    return generic_profile(facts), "generic"


def public_facts(facts: dict[str, Any]) -> dict[str, str]:
    """Facts shown in the panel. DMI model strings and the CPU name only."""
    return {k: str(facts.get(k, "")) for k in ("sys_vendor", "product_name", "product_version", "board_name", "cpu_model")}
