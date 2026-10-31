"""Anti-cheat status from Are We Anti-Cheat Yet.

https://github.com/AreWeAntiCheatYet/AreWeAntiCheatYet keeps games.json, a
list of games with anti-cheat and whether it works under Linux and Proton. It
is MIT licensed, so the plugin may copy it with the notice below. The logos on
the site come from SteamGridDB and are not used.

The plugin downloads the whole list at most once a week, so no game name or
app ID is sent anywhere. It keeps a trimmed copy in the runtime folder and
looks games up locally. A failed refresh keeps the old copy.

The list is community input. It is shown, never acted on.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

from plugin_core.errors import BAD_RESPONSE, PluginError, from_status
from plugin_core.http import HttpClient, parse_base_url
from plugin_core.settings import atomic_write_json, read_json

URL = "https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/master/games.json"
SITE = "https://areweanticheatyet.com"
CACHE_FILE = "anticheat.json"
REFRESH_AFTER = 7 * 24 * 60 * 60
# After a failed refresh, wait this long before trying again, so an offline
# device does not retry on every game it opens.
RETRY_AFTER = 60 * 60
MAX_BYTES = 8 * 1024 * 1024
MAX_NOTES = 3
SCHEMA = 1
ATTRIBUTION = "Anti-cheat status from Are We Anti-Cheat Yet (areweanticheatyet.com), MIT licence."

# The site's own wording, from components/Legend.tsx.
STATUSES = {
    "Supported": "The developers enabled the anti-cheat on Linux, or it works under Proton as it is.",
    "Running": "Runs on Linux with no impact on online play, but may need some tinkering.",
    "Planned": "The developers have said they plan to support Linux.",
    "Broken": "Will not run online because of its anti-cheat.",
    "Denied": "The developers have said they will not enable the anti-cheat on Linux.",
}
# Statuses where settings cannot help online play.
BLOCKED = frozenset({"Broken", "Denied"})


def download(url: str = URL, timeout: float = 30.0) -> bytes:
    """Blocking."""
    parts = url.split("/", 3)
    client = HttpClient(parse_base_url("/".join(parts[:3])), timeout=timeout)
    res = client.get("/" + parts[3])
    if res.status != 200:
        raise from_status(res.status)
    if len(res.body) > MAX_BYTES:
        raise PluginError(BAD_RESPONSE, "too big", hint="The anti-cheat list is larger than expected. Try again later.")
    return res.body


def _text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _url(value: Any) -> str:
    text = str(value or "").strip()
    return text[:300] if text.startswith("https://") else ""


def trim(raw: Any) -> dict[str, Any]:
    """Keep what the panel shows, keyed by Steam app ID and by name."""
    if not isinstance(raw, list):
        raise PluginError(BAD_RESPONSE, "not a list", hint="The anti-cheat list was not valid. Try again later.")
    by_appid: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for game in raw:
        if not isinstance(game, dict) or game.get("status") not in STATUSES:
            continue
        notes = []
        for note in game.get("notes") or []:
            if isinstance(note, list) and note:
                notes.append({"text": _text(note[0], 200), "url": _url(note[1] if len(note) > 1 else "")})
            if len(notes) >= MAX_NOTES:
                break
        entry = {
            "name": _text(game.get("name"), 120),
            "status": game["status"],
            "anticheats": [_text(a, 60) for a in game.get("anticheats") or [] if isinstance(a, str)][:4],
            "notes": notes,
            "slug": _text(game.get("slug"), 120),
            "changed": _text(game.get("dateChanged"), 30),
        }
        steam = (game.get("storeIds") or {}).get("steam") if isinstance(game.get("storeIds"), dict) else None
        if steam and str(steam).isdigit():
            by_appid[str(int(steam))] = entry
        if entry["name"]:
            by_name[entry["name"].casefold()] = entry
    if not by_appid and not by_name:
        raise PluginError(BAD_RESPONSE, "empty", hint="The anti-cheat list was empty. Try again later.")
    return {"schema": SCHEMA, "by_appid": by_appid, "by_name": by_name}


class AntiCheatList:
    def __init__(self, runtime_dir: str, fetch: Callable[[], bytes] | None = None,
                 now: Callable[[], float] = time.time):
        self.path = os.path.join(runtime_dir, CACHE_FILE)
        # Looked up at call time, so tests can replace download.
        self._fetch = fetch or (lambda: download())
        self._now = now
        self._data: dict[str, Any] | None = None
        self._failed_at: float | None = None

    def _load(self) -> dict[str, Any] | None:
        if self._data is None:
            data = read_json(self.path)
            self._data = data if isinstance(data, dict) and data.get("schema") == SCHEMA else None
        return self._data

    def age(self) -> float | None:
        try:
            return self._now() - os.path.getmtime(self.path)
        except OSError:
            return None

    def ensure(self, force: bool = False) -> None:
        """Blocking. Download when missing, broken or a week old. After a failure,
        wait an hour unless forced, as Refresh reports does."""
        data = self._load()
        age = self.age()
        if data and age is not None and age < REFRESH_AFTER:
            return
        if not force and self._failed_at is not None and self._now() - self._failed_at < RETRY_AFTER:
            if data:
                return
            raise PluginError(BAD_RESPONSE, "retry later",
                              hint="Could not download the anti-cheat list. Press Refresh reports to try again.")
        try:
            fresh = trim(json.loads(self._fetch().decode("utf-8")))
        except Exception:
            self._failed_at = self._now()
            if data:
                return
            raise
        self._failed_at = None
        atomic_write_json(self.path, fresh)
        self._data = fresh

    def lookup(self, appid: int | None, name: str = "") -> dict[str, Any] | None:
        """By Steam app ID, or by exact name for a non-Steam shortcut."""
        data = self._load() or {}
        entry = None
        if appid:
            entry = (data.get("by_appid") or {}).get(str(int(appid)))
        elif name:
            entry = (data.get("by_name") or {}).get(name.strip().casefold())
        if not entry:
            return None
        status = entry.get("status")
        slug = entry.get("slug") or ""
        return {
            **entry,
            "meaning": STATUSES.get(status, ""),
            "blocked": status in BLOCKED,
            "by_name": not appid,
            "url": f"{SITE}/game/{slug}" if slug else SITE,
            "attribution": ATTRIBUTION,
        }

    def delete(self) -> None:
        self._data = None
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
