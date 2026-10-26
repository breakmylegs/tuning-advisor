"""Load the device and stack registries shipped in the plugin's registry folder."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

BAND_FRACTIONS = {"light": 0.25, "medium": 0.50, "heavy": 0.70, "max": 0.90}
WORKLOADS = ("light", "medium", "heavy")


def round_half_up(value: float) -> int:
    return int(value + 0.5)


def derived_bands(tdp_min: float, tdp_max: float) -> dict[str, Any]:
    span = tdp_max - tdp_min
    bands: dict[str, Any] = {k: round_half_up(tdp_min + span * f) for k, f in BAND_FRACTIONS.items()}
    bands["derived"] = True
    return bands


@dataclass
class Registry:
    devices: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    categories: list[str] = field(default_factory=lambda: ["power", "framegen", "upscaler", "fan"])

    def device(self, device_id: str) -> dict[str, Any] | None:
        return next((d for d in self.devices if d["id"] == device_id), None)

    def tool(self, tool_id: str) -> dict[str, Any] | None:
        return next((t for t in self.tools if t["id"] == tool_id), None)

    def tools_for(self, category: str) -> list[dict[str, Any]]:
        return [t for t in self.tools if category in t.get("categories", [])]


def load(registry_dir: str) -> Registry:
    with open(os.path.join(registry_dir, "devices.json"), encoding="utf-8") as handle:
        devices = json.load(handle)["devices"]
    with open(os.path.join(registry_dir, "stacks.json"), encoding="utf-8") as handle:
        stacks = json.load(handle)
    return Registry(devices=devices, tools=stacks["tools"], categories=stacks.get("categories", []))
