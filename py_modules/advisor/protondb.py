"""ProtonDB reports from the local index. Phase 2, optional.

The index is built from ProtonDB's monthly ODbL dump by tools/protondb_index.py
and published to the monorepo's rolling release protondb-index. The plugin
downloads it once when you turn the source on, refreshes it after 31 days, and
finds one game by reading the gzipped lines. Nothing stays in memory.

ProtonDB has no TDP or frame rate fields, so these reports feed the
compatibility section and notes, not power settings.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

from plugin_core.errors import BAD_RESPONSE, PluginError, from_status
from plugin_core.http import HttpClient, parse_base_url

INDEX_FILE = "protondb-index.json.gz"
REFRESH_AFTER = 31 * 24 * 60 * 60
MAX_BYTES = 30 * 1024 * 1024
SOURCE = "protondb"
ATTRIBUTION = "Contains information from ProtonDB, made available under the ODbL."


def index_url(monorepo: str) -> str:
    return f"https://github.com/{monorepo}/releases/download/protondb-index/{INDEX_FILE}" if monorepo else ""


def download(url: str, timeout: float = 60.0) -> bytes:
    """Blocking. GitHub redirects release downloads to its file host."""
    parts = url.split("/", 3)
    client = HttpClient(parse_base_url("/".join(parts[:3])), timeout=timeout,
                        headers={"Accept": "application/octet-stream"})
    res = client.get("/" + parts[3])
    if res.status != 200:
        raise from_status(res.status)
    if len(res.body) > MAX_BYTES:
        raise PluginError(BAD_RESPONSE, "too big", hint="The ProtonDB index is larger than expected. Try again later.")
    return res.body


class ProtonDbIndex:
    def __init__(self, runtime_dir: str, url: str, fetch: Callable[[str], bytes] = download,
                 now: Callable[[], float] = time.time):
        self.path = os.path.join(runtime_dir, INDEX_FILE)
        self.url = url
        self._fetch = fetch
        self._now = now

    def header(self) -> dict[str, Any] | None:
        try:
            with gzip.open(self.path, "rt", encoding="utf-8") as handle:
                data = json.loads(handle.readline())
        except (OSError, ValueError, EOFError):
            return None
        return data if isinstance(data, dict) and data.get("schema") == 1 else None

    def age(self) -> float | None:
        try:
            return self._now() - os.path.getmtime(self.path)
        except OSError:
            return None

    def ensure(self) -> dict[str, Any]:
        """Blocking. Download when missing, broken or old. A failed refresh keeps
        the old file, so the source still works offline."""
        header = self.header()
        age = self.age()
        if header and age is not None and age < REFRESH_AFTER:
            return header
        if not self.url:
            if header:
                return header
            raise PluginError(BAD_RESPONSE, "no url", hint="This build does not know where the ProtonDB index lives.")
        try:
            data = self._fetch(self.url)
            self._store(data)
        except Exception:
            if header:
                return header
            raise
        fresh = self.header()
        if not fresh:
            raise PluginError(BAD_RESPONSE, "bad index", hint="The downloaded ProtonDB index was not valid. Try again later.")
        return fresh

    def _store(self, data: bytes) -> None:
        tmp = self.path + ".part"
        with open(tmp, "wb") as handle:
            handle.write(data)
        # Check it reads before replacing the old copy.
        with gzip.open(tmp, "rt", encoding="utf-8") as handle:
            first = json.loads(handle.readline())
        if not isinstance(first, dict) or first.get("schema") != 1:
            os.unlink(tmp)
            raise PluginError(BAD_RESPONSE, "bad index", hint="The downloaded ProtonDB index was not valid. Try again later.")
        os.replace(tmp, self.path)

    def lookup(self, appid: int) -> dict[str, Any] | None:
        prefix = f"{int(appid)}\t"
        try:
            with gzip.open(self.path, "rt", encoding="utf-8") as handle:
                handle.readline()
                for line in handle:
                    if line.startswith(prefix):
                        return json.loads(line[len(prefix):])
        except (OSError, ValueError, EOFError):
            return None
        return None

    def delete(self) -> None:
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


GE_RE = re.compile(r"ge[- ]?proton\s*(\d+[-.]\d+)", re.I)


def compat_fields(variant: Any, proton: Any) -> tuple[str | None, str | None]:
    """Map ProtonDB's variant and version to the tool and version that
    compat.proton_name reads from Deck Verified reports."""
    text = str(proton or "").strip()
    ge = GE_RE.search(text)
    if variant == "ge" or ge:
        return "Glorious Eggroll Proton (GE)", ge.group(1) if ge else "latest"
    if variant == "native":
        return "Native Linux", ""
    if variant == "experimental":
        return "Steam Proton", "experimental"
    if text:
        return "Steam Proton", re.sub(r"(?i)^\s*proton\s*", "", text) or "default"
    if variant == "official":
        return "Steam Proton", "default"
    return None, None


def normalise(entry: dict[str, Any], appid: int) -> list[dict[str, Any]]:
    out = []
    for report in entry.get("reports") or []:
        ts = int(report.get("t") or 0)
        works = report.get("verdict") == "yes"
        tool, version = compat_fields(report.get("variant"), report.get("proton"))
        launch = report.get("launch")
        frame_gen = "lsfg-vk" if launch and "lsfg" in launch else ("optiscaler" if launch and "fgmod" in launch else None)
        notes = report.get("notes") or ""
        out.append({
            "source": SOURCE,
            "source_url": f"https://www.protondb.com/app/{int(appid)}",
            "report_title": "Works" if works else "Reported not working",
            "report_date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else "",
            "votes": 0,
            "device_reported": str(report.get("device") or ""),
            "apu_reported": str(report.get("apu") or ""),
            "device_match": "other_handheld",
            "confidence": "low",
            "works": works,
            "power": {"tdp_w": None, "gpu_clock_mhz": None},
            "display": {"refresh_hz": None, "fps_cap": None, "vrr": None},
            "scaling": {"steam_filter": None, "scaling_mode": None, "game_resolution": None},
            "upscaler": {"name": None, "mode": None},
            "frame_gen": {"tool": frame_gen, "mode": None},
            "in_game": {"preset": None, "settings": []},
            "compat": {"proton": report.get("proton"), "tool": tool, "tool_version": version, "launch_options": launch},
            "notes": notes if works else f"Reported not working. {notes}".strip(),
        })
    return out


def summary(entry: dict[str, Any] | None, header: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    n = int(entry.get("n") or 0)
    works = int(entry.get("works") or 0)
    return {"reports": n, "works": works, "handheld": int(entry.get("handheld") or 0),
            "share": round(100 * works / n) if n else None, "dump": (header or {}).get("dump"),
            "attribution": ATTRIBUTION}
