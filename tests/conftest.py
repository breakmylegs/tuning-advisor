import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(PLUGIN))
FIXTURES = os.path.join(HERE, "fixtures")

sys.path.insert(0, os.path.join(PLUGIN, "py_modules"))
# In the monorepo, plugin_core lives in shared/py until vendor_shared.py copies it.
if not os.path.isdir(os.path.join(PLUGIN, "py_modules", "plugin_core")):
    sys.path.insert(1, os.path.join(ROOT, "shared", "py"))


def capture_to_root(text: str, root: str) -> None:
    """Turn a tools/capture_device.sh dump into a fake filesystem root."""
    section = None
    dmi = os.path.join(root, "sys", "class", "dmi", "id")
    os.makedirs(dmi, exist_ok=True)
    os.makedirs(os.path.join(root, "proc"), exist_ok=True)
    os.makedirs(os.path.join(root, "etc"), exist_ok=True)
    os_lines = []
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.strip() or line.startswith("#"):
            continue
        if section == "dmi" and "=" in line:
            key, value = line.split("=", 1)
            if value != "<unreadable>":
                with open(os.path.join(dmi, key), "w", encoding="utf-8") as handle:
                    handle.write(value + "\n")
        elif section == "cpu" and line.startswith("model_name="):
            with open(os.path.join(root, "proc", "cpuinfo"), "w", encoding="utf-8") as handle:
                handle.write(f"processor\t: 0\nmodel name\t: {line.split('=', 1)[1]}\n")
        elif section == "gpu" and " vendor=" in line:
            card, rest = line.split(" ", 1)
            vendor = rest.split("vendor=", 1)[1].split()[0]
            folder = os.path.join(root, "sys", "class", "drm", card, "device")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "vendor"), "w", encoding="utf-8") as handle:
                handle.write(vendor + "\n")
        elif section == "os":
            os_lines.append(line)
    with open(os.path.join(root, "etc", "os-release"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(os_lines) + "\n")


@pytest.fixture()
def device_root(tmp_path):
    def make(name: str) -> str:
        with open(os.path.join(FIXTURES, "devices", f"{name}.txt"), encoding="utf-8") as handle:
            text = handle.read()
        root = tmp_path / f"root-{name}"
        capture_to_root(text, str(root))
        return str(root)

    return make


@pytest.fixture()
def decky_home(tmp_path):
    """Build a fake ~/homebrew with the given plugin names and disabled list."""

    def make(plugins: list[str], disabled: list[str] | None = None) -> str:
        home = tmp_path / "homebrew"
        for i, name in enumerate(plugins):
            folder = home / "plugins" / f"folder-{i}"
            folder.mkdir(parents=True)
            (folder / "plugin.json").write_text(json.dumps({"name": name}))
        (home / "settings").mkdir(parents=True, exist_ok=True)
        (home / "settings" / "loader.json").write_text(json.dumps({"disabled_plugins": disabled or []}))
        return str(home)

    return make


@pytest.fixture()
def dv_fixture():
    with open(os.path.join(FIXTURES, "deckverified_1091500.json"), encoding="utf-8") as handle:
        return json.load(handle)
