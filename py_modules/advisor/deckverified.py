"""Deck Verified (DeckSettings) community reports.

GET https://deckverified.games/deck-verified/api/v1/game_details?appid=<id>
or ?name=<game name> for non-Steam shortcuts. 400 with neither, 204 for an app
ID above Steam's range, 120 requests per IP per 2 minutes. Report data is
GPL-3.0 and every report links back to its GitHub issue.

Report text is untrusted community input. It is shown, never executed.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from plugin_core.errors import BAD_RESPONSE, FORBIDDEN, HTTP_ERROR, PluginError, from_status
from plugin_core.http import HttpClient, parse_base_url

BASE = "https://deckverified.games"
PATH = "deck-verified/api/v1/game_details"
SOURCE = "deckverified"
SITE = "https://deckverified.games"
MAX_TEXT = 400
MAX_SETTINGS = 12


def fetch(appid: int | None, name: str | None, timeout: float = 10.0) -> dict[str, Any]:
    """Blocking. Returns the raw reply, or an empty reply on 204."""
    params: dict[str, Any] = {}
    if appid:
        params["appid"] = int(appid)
    elif name:
        params["name"] = name[:200]
    else:
        raise ValueError("appid or name is required")
    client = HttpClient(parse_base_url(BASE), timeout=timeout)
    res = client.get(PATH, params=params)
    if res.status == 204:
        return {"reports": []}
    if res.status in (403, 429):
        # Deck Verified is public, so this is the site turning the request
        # away, not a credentials problem.
        raise PluginError(FORBIDDEN if res.status == 403 else HTTP_ERROR, f"HTTP {res.status}", res.status,
                          hint=f"Deck Verified turned the request away (HTTP {res.status}). Try Refresh reports later.")
    if res.status != 200:
        raise from_status(res.status)
    data = res.json()
    if not isinstance(data, dict):
        raise PluginError(BAD_RESPONSE, "reply is not an object")
    return data


# Normalising


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def _on(value: Any) -> bool | None:
    text = str(value or "").strip().casefold()
    if text in ("on", "yes", "true", "enabled"):
        return True
    if text in ("off", "no", "false", "disabled"):
        return False
    return None


SETTING_RE = re.compile(r"^\s*(?:[-*+]\s*)?\**\s*([^:*|#][^:*|]{0,60}?)\s*\**\s*:\s*\**\s*(.{1,80}?)\s*\**\s*$")
PRESET_NAMES = ("preset", "quick preset", "graphics preset", "quality preset", "graphics quality", "quality")
UPSCALER_RE = re.compile(
    r"\b(FidelityFX Super Resolution ?[1-4]?(?:\.\d)?|FSR ?[1-4](?:\.\d)?|FSR|DLSS|XeSS(?: Super Resolution)?|TAAU|TSR)\b",
    re.I,
)


def upscaler_name(raw: str) -> str:
    text = raw.strip()
    lower = text.casefold().replace(" ", "")
    lower = lower.replace("fidelityfxsuperresolution", "fsr").replace("xesssuperresolution", "xess")
    if lower.startswith("fsr"):
        return ("FSR " + lower[3:]).strip()
    return {"dlss": "DLSS", "xess": "XeSS", "taau": "TAAU", "tsr": "TSR"}.get(lower, text)


def parse_settings(markdown: Any) -> list[dict[str, str]]:
    """Pull "Name: Value" lines from the report's settings Markdown."""
    out: list[dict[str, str]] = []
    for line in str(markdown or "").splitlines():
        match = SETTING_RE.match(line)
        if not match:
            continue
        name, value = match.group(1).strip(), match.group(2).strip()
        if name and value and not name.startswith("http"):
            out.append({"name": _text(name, 60), "value": _text(value, 80)})
        if len(out) >= MAX_SETTINGS:
            break
    return out


def frame_gen_from_launch(options: str) -> str | None:
    if "~/lsfg" in options or "lsfg" in options.split():
        return "lsfg-vk"
    if "fgmod" in options:
        return "optiscaler"
    return None


def report_device(report: dict[str, Any]) -> str:
    data = report.get("data") or {}
    device = _text(data.get("device"), 80)
    if device:
        return device
    for label in report.get("labels") or []:
        name = str(label.get("name") or "")
        if name.startswith("DEVICE: "):
            return name[len("DEVICE: "):]
    return ""


def normalise(report: dict[str, Any]) -> dict[str, Any]:
    data = report.get("data") or {}
    reactions = report.get("reactions") or {}
    graphics = parse_settings(data.get("game_graphics_settings"))
    display_settings = parse_settings(data.get("game_display_settings"))
    settings = graphics + [s for s in display_settings if s not in graphics]
    preset = next((s["value"] for s in settings if s["name"].casefold() in PRESET_NAMES), None)
    upscaler = None
    for s in settings:
        hit = UPSCALER_RE.search(f"{s['name']} {s['value']}")
        if hit:
            upscaler = {"name": upscaler_name(hit.group(1)), "mode": s["value"]}
            break
    launch = _text(data.get("custom_launch_options"), 200)
    fps_cap = _int(data.get("frame_limit"))
    if _on(data.get("disable_frame_limit")) is True:
        fps_cap = None
    tool = _text(data.get("steam_play_compatibility_tool_used"), 60)
    version = _text(data.get("compatibility_tool_version"), 40)
    notes = " ".join(p for p in (_text(data.get("summary")), _text(data.get("additional_notes"))) if p)
    return {
        "source": SOURCE,
        "source_url": str(report.get("html_url") or ""),
        "report_title": _text(report.get("title"), 120),
        "report_date": str(report.get("updated_at") or report.get("created_at") or ""),
        "votes": int(reactions.get("reactions_thumbs_up") or 0) - int(reactions.get("reactions_thumbs_down") or 0),
        "device_reported": report_device(report),
        "device_match": "other_handheld",
        "confidence": "low",
        "power": {"tdp_w": _int(data.get("tdp_limit")), "gpu_clock_mhz": _int(data.get("manual_gpu_clock"))},
        "display": {"refresh_hz": None, "fps_cap": fps_cap, "vrr": _on(data.get("enable_vrr"))},
        "scaling": {
            "steam_filter": _text(data.get("scaling_filter"), 30) or None,
            "scaling_mode": _text(data.get("scaling_mode"), 30) or None,
            "game_resolution": None if _text(data.get("game_resolution")).casefold() in ("", "default") else _text(data.get("game_resolution"), 30),
        },
        "upscaler": upscaler or {"name": None, "mode": None},
        "frame_gen": {"tool": frame_gen_from_launch(launch), "mode": None},
        "in_game": {"preset": preset, "settings": settings},
        "compat": {
            "proton": " ".join(p for p in (tool, version) if p) or None,
            "tool": tool or None,
            "tool_version": version or None,
            "launch_options": launch or None,
        },
        "rating": _text(data.get("performance_rating"), 30) or None,
        "target_fps": _text(data.get("target_framerate"), 30) or None,
        "os_version": _text(data.get("os_version"), 60) or None,
        "notes": notes,
    }


def parse_date(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None
