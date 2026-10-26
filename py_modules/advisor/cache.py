"""Source response cache in DECKY_PLUGIN_RUNTIME_DIR.

Keyed by source, app and game build. Entries live 7 days. A stale entry is
still returned when the source cannot be reached, marked as cached.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Callable

from plugin_core.settings import atomic_write_json, read_json

TTL = 7 * 24 * 60 * 60


class SourceCache:
    def __init__(self, folder: str, now: Callable[[], float] = time.time):
        self.folder = folder
        self._now = now

    def _path(self, source: str, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        return os.path.join(self.folder, f"{source}-{digest}.json")

    def get(self, source: str, key: str) -> tuple[Any, float] | None:
        raw = read_json(self._path(source, key))
        if not isinstance(raw, dict) or "stored_at" not in raw or raw.get("key") != key:
            return None
        return raw.get("data"), float(raw["stored_at"])

    def fresh(self, stored_at: float) -> bool:
        return self._now() - stored_at < TTL

    def put(self, source: str, key: str, data: Any) -> None:
        atomic_write_json(self._path(source, key), {"key": key, "stored_at": self._now(), "data": data})

    def clear(self) -> int:
        removed = 0
        try:
            names = os.listdir(self.folder)
        except FileNotFoundError:
            return 0
        for name in names:
            if name.endswith(".json") and "-" in name and name != "update.json":
                try:
                    os.unlink(os.path.join(self.folder, name))
                    removed += 1
                except OSError:
                    pass
        return removed
