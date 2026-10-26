"""Read the current per-game values from the user's tuning tools. Read only.

Only formats read from each tool's source are supported. Anything else, or
a file that does not parse, is skipped silently and the panel shows nothing.
These files are opened for reading and never written.

Formats, checked 26 October 2026 (VERIFICATION.md item 23):
- SimpleDeckyTDP: <settings>/settings.json, tdpProfiles.<appid>.tdp in watts,
  "default" otherwise. Per-game profiles apply only when enableTdpProfiles is on.
- PowerControl: <settings>/config.json, key "PowerControl", perApp.<appid>,
  "0" otherwise. Per-game applies only when overwrite is on. defaultSettig.tdp
  in watts with tdpEnable. acStateOverwrite keeps separate AC and battery values.
- LeGoTDP: <settings>/settings.json, game_profiles.<appid>.spl in milliwatts,
  with preset. Global values under "settings".
- Legion Go 2 Companion: <settings>/tdp_settings.json, same shape as LeGoTDP.
  Paused profiles live under inactive_game_profiles and are ignored.
- Decky LSFG-VK: ~/.config/lsfg-vk/conf.toml, version 2, [[profile]] entries
  with active_in app IDs, multiplier, flow_scale and performance_mode.
"""

from __future__ import annotations

import json
import os
from typing import Any

try:  # Python 3.11 and later. The loader floor is 3.10, where lsfg-vk is skipped.
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

MAX_BYTES = 2 * 1024 * 1024


def _read_json(path: str) -> Any:
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _watts(value: Any, milliwatts: bool = False) -> int | None:
    number = _num(value)
    if number is None or number <= 0:
        return None
    watts = number / 1000 if milliwatts else number
    return int(round(watts)) if 1 <= watts <= 120 else None


def simpledeckytdp(settings_dir: str, appid: str) -> dict[str, Any] | None:
    data = _read_json(os.path.join(settings_dir, "settings.json"))
    if not isinstance(data, dict):
        return None
    profiles = data.get("tdpProfiles")
    if not isinstance(profiles, dict):
        return None
    per_game = bool(data.get("enableTdpProfiles"))
    game = profiles.get(appid) if per_game else None
    profile, scope = (game, "this game's profile") if isinstance(game, dict) else (profiles.get("default"), "default profile")
    if not isinstance(profile, dict):
        return None
    tdp = _watts(profile.get("tdp"))
    if tdp is None:
        return None
    note = None if per_game else "Per-game profiles are off in SimpleDeckyTDP, so the default applies."
    return {"tdp_w": tdp, "scope": scope, "note": note}


def powercontrol(settings_dir: str, appid: str) -> dict[str, Any] | None:
    data = _read_json(os.path.join(settings_dir, "config.json"))
    root = data.get("PowerControl") if isinstance(data, dict) else None
    per_app = root.get("perApp") if isinstance(root, dict) else None
    if not isinstance(per_app, dict):
        return None
    game = per_app.get(appid)
    use_game = isinstance(game, dict) and bool(game.get("overwrite"))
    entry, scope = (game, "this game's profile") if use_game else (per_app.get("0"), "default profile")
    if not isinstance(entry, dict):
        return None
    setting = entry.get("defaultSettig")
    if not isinstance(setting, dict):
        return None
    if setting.get("tdpEnable") is False:
        return {"tdp_w": None, "scope": scope, "note": "The TDP limit is off in PowerControl for this profile."}
    tdp = _watts(setting.get("tdp"))
    if tdp is None:
        return None
    note = "PowerControl keeps separate AC and battery values here. This is the default one." if entry.get("acStateOverwrite") else None
    return {"tdp_w": tdp, "scope": scope, "note": note}


def _lenovo(path: str, appid: str, tool: str) -> dict[str, Any] | None:
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    profiles = data.get("game_profiles")
    game = profiles.get(appid) if isinstance(profiles, dict) else None
    if isinstance(game, dict) and game.get("spl") is not None:
        tdp = _watts(game.get("spl"), milliwatts=True)
        if tdp is None:
            return None
        preset = game.get("preset") if isinstance(game.get("preset"), str) and game.get("preset") else None
        note = f"Separate values on AC power are set in {tool}." if game.get("ac_separate") is True else None
        return {"tdp_w": tdp, "scope": "this game's profile", "preset": preset, "note": note}
    glob = data.get("settings")
    if isinstance(glob, dict):
        tdp = _watts(glob.get("spl"), milliwatts=True)
        if tdp is not None:
            return {"tdp_w": tdp, "scope": "global setting", "preset": None, "note": None}
    return None


def legotdp(settings_dir: str, appid: str) -> dict[str, Any] | None:
    return _lenovo(os.path.join(settings_dir, "settings.json"), appid, "LeGoTDP")


def legiongo2companion(settings_dir: str, appid: str) -> dict[str, Any] | None:
    return _lenovo(os.path.join(settings_dir, "tdp_settings.json"), appid, "Legion Go 2 Companion")


def lsfg(user_home: str, appid: str) -> dict[str, Any] | None:
    if tomllib is None:
        return None
    path = os.path.join(user_home, ".config", "lsfg-vk", "conf.toml")
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError):
        return None
    if data.get("version") != 2:
        return None
    for profile in data.get("profile") or []:
        if not isinstance(profile, dict):
            continue
        if appid in [str(a) for a in profile.get("active_in") or []]:
            multiplier = profile.get("multiplier")
            flow = _num(profile.get("flow_scale"))
            return {
                "profile": str(profile.get("name") or ""),
                "multiplier": multiplier if isinstance(multiplier, int) and not isinstance(multiplier, bool) else None,
                "flow_scale": flow,
                "performance_mode": profile.get("performance_mode") if isinstance(profile.get("performance_mode"), bool) else None,
            }
    return {"profile": None, "multiplier": None, "flow_scale": None, "performance_mode": None}


POWER_READERS = {
    "simpledeckytdp": simpledeckytdp,
    "powercontrol": powercontrol,
    "legotdp": legotdp,
    "legiongo2companion": legiongo2companion,
}


def read(selected: dict[str, str], detected: dict[str, Any], decky_home: str, user_home: str,
         appid: int | None) -> dict[str, Any]:
    """Current values for the selected power and frame generation tools."""
    out: dict[str, Any] = {"power": None, "framegen": None}
    if not appid:
        return out
    app = str(int(appid))
    folders = {t["id"]: t.get("folder") for t in detected.get("tools") or [] if not t.get("disabled")}
    power_id = selected.get("power")
    reader = POWER_READERS.get(power_id or "")
    folder = folders.get(power_id or "")
    if reader and folder:
        try:
            value = reader(os.path.join(decky_home, "settings", folder), app)
        except Exception:  # noqa: BLE001, an unexpected shape must never break the panel
            value = None
        if value:
            out["power"] = dict(value, tool=power_id)
    if selected.get("framegen") == "lsfg-vk" and "lsfg-vk" in folders:
        try:
            value = lsfg(user_home, app)
        except Exception:  # noqa: BLE001
            value = None
        if value:
            out["framegen"] = dict(value, tool="lsfg-vk")
    return out
