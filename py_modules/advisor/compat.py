"""Compatibility section: Proton version and launch options. Recommend only.

Nothing here applies a value or runs a string. Launch options from community
reports are untrusted text. They are parsed so the panel can explain them,
flag anything that runs a command, and suggest a merge with what you already
have. You copy and set them yourself in Steam.

Steam launch option shape: `ENV=value ... wrapper ... %command% game-args`.
Without %command%, Steam passes the whole string to the game as arguments.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

COMMAND = "%command%"
MAX_LEN = 500
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELL_RE = re.compile(r"[;&|`<>]|\$\(")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
FSR4_ENV_RE = re.compile(r"FSR_?4", re.I)

# Wrappers that belong to a tool in the stack registry.
STACK_WRAPPERS = {
    "~/lsfg": "lsfg-vk",
    "~/fgmod/fgmod": "optiscaler",
}

WHERE_LAUNCH = "Steam, the game's Properties, General, Launch Options"
WHERE_LAUNCH_SHORTCUT = "Steam, the shortcut's Properties, Shortcut, Launch Options"
WHERE_PROTON = (
    "Steam, the game's Properties, Compatibility, turn on Force the use of a specific Steam Play "
    "compatibility tool, then pick it from the list"
)


def clean(text: Any) -> str:
    value = CONTROL_RE.sub(" ", str(text or "")).strip()
    return value[:MAX_LEN]


def split(text: str) -> list[str]:
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        # Unbalanced quotes. Fall back to whitespace so the panel can still show it.
        return text.split()


def parse(text: Any) -> dict[str, Any]:
    raw = clean(text)
    tokens = split(raw)
    env: list[str] = []
    wrappers: list[str] = []
    args: list[str] = []
    has_command = COMMAND in tokens
    seen_command = False
    for token in tokens:
        if token == COMMAND:
            seen_command = True
        elif not has_command:
            args.append(token)
        elif seen_command:
            args.append(token)
        elif ENV_RE.match(token) and not wrappers:
            env.append(token)
        else:
            wrappers.append(token)
    return {"raw": raw, "env": env, "wrappers": wrappers, "args": args, "has_command": has_command,
            "shell": bool(SHELL_RE.search(raw))}


def join(parsed: dict[str, Any]) -> str:
    parts = list(parsed["env"]) + list(parsed["wrappers"])
    if parsed["env"] or parsed["wrappers"] or parsed["has_command"]:
        parts.append(COMMAND)
    parts += parsed["args"]
    return " ".join(shlex.quote(p) if p != COMMAND and (" " in p or not p) else p for p in parts)


def wrapper_tool(token: str) -> str | None:
    return STACK_WRAPPERS.get(token)


def flags_for(parsed: dict[str, Any], selected: dict[str, str]) -> list[str]:
    flags: list[str] = []
    if parsed["shell"]:
        flags.append("Contains shell operators such as ; | & or $( ). Check every part before you use it.")
    for token in parsed["wrappers"]:
        tool = wrapper_tool(token)
        if tool is None:
            flags.append(f"Runs {token} before the game. Only use it if you know what it is and have it installed.")
        elif selected.get("framegen") != tool and selected.get("upscaler") != tool:
            flags.append(f"{token} needs {tool}, which is not in your selected tools.")
    if parsed["args"] and not parsed["has_command"]:
        flags.append("Has no %command%, so Steam passes the whole string to the game as arguments.")
    return flags


def drop_fsr4(parsed: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    kept = [e for e in parsed["env"] if not FSR4_ENV_RE.search(e.split("=", 1)[0])]
    if len(kept) == len(parsed["env"]):
        return parsed, []
    out = dict(parsed, env=kept)
    return out, ["An FSR 4 setting was removed. FSR 4 is not officially available on handheld chips under Proton."]


def merge(current: dict[str, Any], recommended: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Combine your current options with the recommendation. Recommended values
    win for the same environment variable. Your stack's wrappers are kept."""
    notes: list[str] = []
    env: dict[str, str] = {}
    for item in current["env"]:
        env[item.split("=", 1)[0]] = item
    for item in recommended["env"]:
        name = item.split("=", 1)[0]
        if name in env and env[name] != item:
            notes.append(f"Changes {env[name]} to {item}.")
        env[name] = item
    wrappers: list[str] = []
    for token in current["wrappers"]:
        if wrapper_tool(token):
            notes.append(f"Keeps {token} from your current options.")
            wrappers.append(token)
        else:
            notes.append(f"Keeps {token} from your current options. Remove it if you no longer use it.")
            wrappers.append(token)
    for token in recommended["wrappers"]:
        if token not in wrappers:
            wrappers.append(token)
    args = list(current["args"] if current["has_command"] else [])
    for token in recommended["args"]:
        if token not in args:
            args.append(token)
    if not current["has_command"] and current["args"]:
        notes.append("Your current options had no %command%, so they were game arguments. They are kept after %command%.")
        args = current["args"] + [a for a in args if a not in current["args"]]
    merged = {"env": list(env.values()), "wrappers": wrappers, "args": args,
              "has_command": True, "shell": current["shell"] or recommended["shell"]}
    return merged, notes


def launch_section(rec_launch: Any, current_launch: Any, selected: dict[str, str], shortcut: bool) -> dict[str, Any] | None:
    recommended = parse(rec_launch)
    current = parse(current_launch)
    if not recommended["raw"]:
        return None
    recommended, fsr_flags = drop_fsr4(recommended)
    rec_text = join(recommended)
    section: dict[str, Any] = {
        "recommended": rec_text,
        "current": current["raw"],
        "where": WHERE_LAUNCH_SHORTCUT if shortcut else WHERE_LAUNCH,
        "flags": fsr_flags + flags_for(recommended, selected),
        "merged": None,
        "merge_notes": [],
        "same_as_current": False,
    }
    if current["raw"]:
        merged, notes = merge(current, recommended)
        merged_text = join(merged)
        if merged_text == current["raw"] or merged_text == join(current):
            section["same_as_current"] = True
        elif merged_text != rec_text:
            section["merged"] = merged_text
            section["merge_notes"] = notes
    return section


# Proton

GE_VERSION_RE = re.compile(r"(\d+)[-.](\d+)")
PROTON_VERSION_RE = re.compile(r"^\d+(\.\d+)?(-\d+)?$")


def proton_name(tool: Any, version: Any) -> dict[str, Any] | None:
    tool_text = clean(tool).casefold()
    version_text = clean(version)
    v = version_text.casefold()
    if not tool_text and not version_text:
        return None
    if "native" in tool_text or "linux" in tool_text:
        return {"name": "None. Native Linux build", "force": False, "install_note": None}
    if "ge" in tool_text.split() or "eggroll" in tool_text or "(ge)" in tool_text:
        match = GE_VERSION_RE.search(version_text)
        name = f"GE-Proton{match.group(1)}-{match.group(2)}" if match else "GE-Proton (latest)"
        return {"name": name, "force": True,
                "install_note": "GE-Proton is not built into Steam. Install it with ProtonUp-Qt or ProtonPlus in Desktop Mode, then restart Steam."}
    if v in ("", "default"):
        return {"name": "Steam's default", "force": False, "install_note": None}
    if "experimental" in v:
        return {"name": "Proton Experimental", "force": True, "install_note": None}
    if "hotfix" in v:
        return {"name": "Proton Hotfix", "force": True, "install_note": None}
    if PROTON_VERSION_RE.match(version_text):
        major = version_text.split("-")[0]
        return {"name": f"Proton {major}", "force": True, "install_note": None,
                "build": version_text if "-" in version_text else None}
    return {"name": clean(f"{clean(tool)} {version_text}"), "force": True, "install_note": None}


def proton_section(rec_compat: dict[str, Any], current_tool: Any) -> dict[str, Any] | None:
    named = proton_name(rec_compat.get("tool"), rec_compat.get("tool_version"))
    if named is None:
        return None
    current = clean(current_tool)
    current_label = current or "Steam's default"
    matches = (not named["force"] and not current) or (
        bool(current) and named["force"] and named["name"].casefold() in current.casefold())
    return {
        "recommended": named["name"],
        "force": named["force"],
        "build": named.get("build"),
        "install_note": named["install_note"],
        "current": current_label,
        "matches": matches,
        "where": WHERE_PROTON if named["force"] else "Steam, the game's Properties, Compatibility, turn off Force the use of a specific Steam Play compatibility tool",
        "as_reported": clean(" ".join(p for p in (clean(rec_compat.get("tool")), clean(rec_compat.get("tool_version"))) if p)),
    }


def section(rec: dict[str, Any], current: dict[str, Any], selected: dict[str, str], shortcut: bool) -> dict[str, Any] | None:
    compat = rec.get("compat") or {}
    proton = None if shortcut and not compat.get("tool") else proton_section(compat, current.get("compat_tool"))
    launch = launch_section(compat.get("launch_options"), current.get("launch_options"), selected, shortcut)
    if not proton and not launch:
        return None
    return {"proton": proton, "launch": launch}
