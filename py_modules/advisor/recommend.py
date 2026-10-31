"""Device matching, ranking, validation, translation and fallback rules.

Every recommendation uses the normalised model from CLAUDE.md section 8.6.
Values reported on another device are shown as reported, labelled with that
device, and never scaled. Validation clamps or drops what this device cannot
do and records each change as a flag.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .deckverified import parse_date
from .registry import Registry

MATCH_ORDER = ("exact", "variant", "family", "same_apu", "other_handheld", "steam_deck", "generic")
MATCH_LABELS = {
    "exact": "your device",
    "variant": "another variant of your device",
    "family": "the same device family",
    "same_apu": "a device with the same chip",
    "other_handheld": "another handheld",
    "steam_deck": "a Steam Deck",
    "generic": "general guidance",
}
RECENT = timedelta(days=365)
FPS_TARGETS = {"light": 60, "medium": 45, "heavy": 30}
FALLBACK_FILTER = {"light": "Linear", "medium": "Linear", "heavy": "FSR"}
FSR4_RE = re.compile(r"\b(?:fsr|fidelityfx super resolution)\s*4\b", re.I)


# Device matching


def device_for_report(registry: Registry, reported: str) -> dict[str, Any] | None:
    for entry in registry.devices:
        for pattern in entry.get("report_aliases") or []:
            try:
                if re.match(pattern, reported, re.I):
                    return entry
            except re.error:
                continue
    return None


def chip(name: Any) -> str:
    """Compare chips by name. "AMD Ryzen AI Z2 Extreme" is the same chip as "AMD Ryzen Z2 Extreme"."""
    return " ".join(w for w in str(name or "").casefold().split() if w not in ("ai", "amd"))


def device_match(registry: Registry, reported: str, mine: dict[str, Any], apu_reported: str = "") -> str:
    theirs = device_for_report(registry, reported)
    if theirs is None:
        # ProtonDB reports name a chip, not a device.
        if apu_reported and chip(apu_reported) == chip(mine.get("apu")):
            return "same_apu"
        return "steam_deck" if "steam deck" in reported.casefold() and mine.get("family") != "steam-deck" else "other_handheld"
    if theirs["id"] == mine.get("id"):
        return "exact"
    if theirs.get("model") == mine.get("model") and theirs.get("vendor") == mine.get("vendor"):
        return "variant"
    if theirs.get("family") == mine.get("family") and mine.get("family") not in (None, "generic"):
        return "family"
    if theirs.get("apu") and chip(theirs.get("apu")) == chip(mine.get("apu")):
        return "same_apu"
    if theirs.get("family") == "steam-deck":
        return "steam_deck"
    return "other_handheld"


def confidence(rec: dict[str, Any], now: datetime, low_confidence_game: bool) -> str:
    if low_confidence_game:
        return "low"
    match = rec["device_match"]
    date = parse_date(rec.get("report_date", ""))
    recent = bool(date and now - date <= RECENT)
    if match in ("exact", "variant") and recent:
        return "high"
    if match in ("exact", "variant", "family", "same_apu"):
        return "medium"
    return "low"


# Ranking


def rank(recs: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    def key(rec: dict[str, Any]) -> tuple:
        date = parse_date(rec.get("report_date", "")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (
            MATCH_ORDER.index(rec["device_match"]) if rec["device_match"] in MATCH_ORDER else len(MATCH_ORDER),
            0 if now - date <= RECENT else 1,
            -int(rec.get("votes") or 0),
            -date.timestamp(),
        )

    return sorted(recs, key=key)


# Validation


def _even_divisor(cap: int, refresh: int) -> bool:
    return cap > 0 and refresh % cap == 0


def nearest_divisor(target: int, refresh: int) -> int:
    divisors = [refresh // n for n in range(1, refresh + 1) if refresh % n == 0 and refresh // n >= 20]
    below = [d for d in divisors if d <= target]
    return max(below) if below else min(divisors)


def validate(rec: dict[str, Any], device: dict[str, Any], selected: dict[str, str]) -> dict[str, Any]:
    out = copy.deepcopy(rec)
    flags: list[str] = []
    tdp = out["power"].get("tdp_w")
    rng = device.get("tdp_w") or {}
    if tdp is not None and rng:
        lo, hi = rng.get("min"), rng.get("max")
        if lo is not None and tdp < lo:
            flags.append(f"TDP {tdp} W is below this device's {lo} W minimum. Raised to {lo} W.")
            out["power"]["tdp_w"] = lo
        elif hi is not None and tdp > hi:
            flags.append(f"TDP {tdp} W is above this device's {hi} W maximum. Lowered to {hi} W.")
            out["power"]["tdp_w"] = hi

    display = device.get("display") or {}
    max_hz = display.get("refresh_hz_max")
    refresh = out["display"].get("refresh_hz")
    if refresh and max_hz and refresh > max_hz:
        flags.append(f"Refresh {refresh} Hz is above this screen's {max_hz} Hz. Dropped.")
        out["display"]["refresh_hz"] = None
        refresh = None

    cap = out["display"].get("fps_cap")
    if cap and max_hz:
        panel_hz = refresh or max_hz
        if cap > max_hz:
            flags.append(f"FPS cap {cap} is above this screen's {max_hz} Hz. Dropped.")
            out["display"]["fps_cap"] = None
        elif display.get("vrr"):
            low, high = display.get("vrr_range_hz") or [30, max_hz]
            if not low <= cap <= high:
                flags.append(f"FPS cap {cap} is outside this screen's VRR range ({low} to {high} Hz).")
        elif not _even_divisor(cap, panel_hz):
            better = nearest_divisor(cap, panel_hz)
            flags.append(
                f"FPS cap {cap} does not divide {panel_hz} Hz evenly, so frame pacing may stutter. Try {better}."
            )
    if out["display"].get("vrr") and not display.get("vrr") and max_hz:
        flags.append("The report uses VRR. This screen has no VRR.")
        out["display"]["vrr"] = False

    upscaler = out.get("upscaler") or {}
    if upscaler.get("name") and FSR4_RE.search(f"{upscaler.get('name')} {upscaler.get('mode') or ''}"):
        flags.append("FSR 4 is not recommended. It is not officially available on handheld chips under Proton.")
        out["upscaler"] = {"name": None, "mode": None}

    settings = (out.get("in_game") or {}).get("settings") or []
    kept = [st for st in settings if not FSR4_RE.search(f"{st.get('name', '')} {st.get('value', '')}")]
    if len(kept) != len(settings):
        out["in_game"]["settings"] = kept
        if not any("FSR 4" in f for f in flags):
            flags.append("FSR 4 settings from the report are hidden. FSR 4 is not officially available on handheld chips under Proton.")

    tool = (out.get("frame_gen") or {}).get("tool")
    if tool and selected.get("framegen") != tool:
        out["frame_gen"]["requires"] = tool
        flags.append(f"Uses frame generation that needs {tool}, which is not in your selected tools.")

    out["flags"] = flags
    return out


# Translation into the selected tools' words


def nearest_preset(presets: list[dict[str, Any]], watts: int) -> dict[str, Any]:
    return min(presets, key=lambda p: (abs(p["spl"] - watts), p["spl"]))


def translate(rec: dict[str, Any], registry: Registry, device: dict[str, Any], selected: dict[str, str]) -> dict[str, Any]:
    lines: dict[str, list[str]] = {"power": [], "display": [], "scaling": [], "frame_gen": [], "in_game": []}
    watts = rec["power"].get("tdp_w")
    power_id = selected.get("power", "none")
    tool = registry.tool(power_id) if power_id != "none" else None
    if watts is not None:
        if tool:
            phrase = (tool.get("vocabulary") or {}).get("power", "Set the TDP to {w} W in " + tool["name"] + ".")
            if "{preset}" in phrase:
                presets = (tool.get("presets") or {}).get(device.get("id")) or (tool.get("presets") or {}).get("default") or []
                if presets:
                    preset = nearest_preset(presets, watts)
                    phrase = phrase.replace("{preset}", preset["name"]).replace("{spl}", str(preset["spl"]))
                else:
                    phrase = "Set SPL (Sustained) to {w} W in " + tool["name"] + "."
            lines["power"].append(phrase.replace("{w}", str(watts)))
        else:
            lines["power"].append(f"Set the TDP to {watts} W. No power tool is selected.")
    if rec["power"].get("gpu_clock_mhz"):
        lines["power"].append(f"Fix the GPU clock at {rec['power']['gpu_clock_mhz']} MHz in Steam, Performance.")

    display = rec["display"]
    if display.get("refresh_hz"):
        lines["display"].append(f"Set Refresh Rate to {display['refresh_hz']} Hz in Steam, Performance.")
    if display.get("fps_cap"):
        lines["display"].append(f"Set Framerate Limit to {display['fps_cap']} in Steam, Performance.")
    if display.get("vrr") is True:
        lines["display"].append("Turn on Variable Refresh Rate in Steam, Performance.")
    elif display.get("vrr") is False and (device.get("display") or {}).get("vrr"):
        lines["display"].append("Leave Variable Refresh Rate off.")

    scaling = rec["scaling"]
    if scaling.get("game_resolution"):
        lines["scaling"].append(f"Set the game resolution to {scaling['game_resolution']}.")
    if scaling.get("steam_filter"):
        lines["scaling"].append(f"Set Scaling Filter to {scaling['steam_filter']} in Steam, Performance.")
    upscaler = rec.get("upscaler") or {}
    if upscaler.get("name"):
        lines["scaling"].append(f"In game, use {upscaler['name']}" + (f" ({upscaler['mode']})." if upscaler.get("mode") else "."))

    fg = rec.get("frame_gen") or {}
    if fg.get("tool"):
        fg_tool = registry.tool(fg["tool"])
        phrase = (fg_tool or {}).get("vocabulary", {}).get("framegen") if fg_tool else None
        lines["frame_gen"].append(phrase or f"Uses frame generation with {fg['tool']}.")
        if fg.get("requires"):
            lines["frame_gen"].append(f"Requires {(fg_tool or {}).get('name', fg['tool'])}.")

    in_game = rec.get("in_game") or {}
    if in_game.get("preset"):
        lines["in_game"].append(f"Graphics preset: {in_game['preset']}.")
    lines["battery"] = battery_lines(rec, device)
    out = copy.deepcopy(rec)
    out["lines"] = lines
    return out


# Battery


# Close enough that the same settings should draw about the same power.
NEAR_MATCHES = ("exact", "variant", "family")


def duration(minutes: float) -> str:
    total = int(round(minutes))
    hours, mins = divmod(total, 60)
    return f"{hours}h {mins:02d}m" if hours else f"{mins}m"


def _watt_text(watts: float) -> str:
    return f"{watts:g} W"


def battery_lines(rec: dict[str, Any], device: dict[str, Any]) -> list[str]:
    """A battery estimate from the report's measured draw and this device's battery.
    No published model links TDP to whole-device draw, so only measured draw is used."""
    battery = rec.get("battery") or {}
    draw = battery.get("draw_w")
    if not isinstance(draw, (int, float)) or isinstance(draw, bool) or draw <= 0:
        return []
    where = rec.get("device_reported") or "the reporting device"
    wh = device.get("battery_wh")
    if device.get("generic") or not isinstance(wh, (int, float)) or isinstance(wh, bool) or wh <= 0:
        reported = battery.get("minutes")
        line = f"Reported battery draw {_watt_text(draw)} on {where}"
        return [line + (f", about {duration(reported)} on its battery." if reported else ".")]
    estimate = duration(wh * 60 / draw)
    if rec.get("device_match") in NEAR_MATCHES:
        return [f"Reported battery draw {_watt_text(draw)}. On your {wh:g} Wh battery that is about {estimate}."]
    return [
        f"Reported battery draw {_watt_text(draw)} on {where}. At the same draw, your {wh:g} Wh battery lasts "
        f"about {estimate}. Your screen and chip differ, so treat this as a rough guide."
    ]


# Fallback


def fallback(device: dict[str, Any], workload: str) -> dict[str, Any]:
    workload = workload if workload in FPS_TARGETS else "medium"
    bands = device.get("tdp_bands_w") or {}
    display = device.get("display") or {}
    max_hz = display.get("refresh_hz_max") or 60
    target = FPS_TARGETS[workload]
    if display.get("vrr"):
        low, high = display.get("vrr_range_hz") or [30, max_hz]
        cap = max(low, min(target, high))
    else:
        cap = nearest_divisor(target, max_hz)
    return {
        "source": "fallback",
        "source_url": "",
        "report_date": "",
        "votes": 0,
        "device_reported": "",
        "device_match": "generic",
        "confidence": "low",
        "workload": workload,
        "power": {"tdp_w": bands.get(workload), "gpu_clock_mhz": None},
        "display": {"refresh_hz": None, "fps_cap": cap, "vrr": True if display.get("vrr") else None},
        "scaling": {"steam_filter": FALLBACK_FILTER[workload], "scaling_mode": None, "game_resolution": None},
        "upscaler": {"name": None, "mode": None},
        "frame_gen": {"tool": None, "mode": None},
        "in_game": {"preset": None, "settings": []},
        "compat": {"proton": None, "tool": None, "tool_version": None, "launch_options": None},
        "notes": "General guidance, not game-specific."
        + (" TDP bands are derived from the device's TDP range." if bands.get("derived") else ""),
    }


def build(reports: list[dict[str, Any]], registry: Registry, device: dict[str, Any], selected: dict[str, str],
          workload: str, low_confidence_game: bool, now: datetime | None = None) -> list[dict[str, Any]]:
    """Full pipeline. Source reports first, ranked, then the fallback last."""
    now = now or datetime.now(timezone.utc)
    recs = []
    for rec in reports:
        rec = dict(rec)
        rec["device_match"] = device_match(registry, rec.get("device_reported", ""), device, rec.get("apu_reported", ""))
        rec["confidence"] = confidence(rec, now, low_confidence_game)
        recs.append(rec)
    ranked = rank(recs, now)
    ranked.append(fallback(device, workload))
    return [translate(validate(r, device, selected), registry, device, selected) for r in ranked]
