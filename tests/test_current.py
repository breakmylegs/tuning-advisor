"""Read-only current values from the tuning tools. File shapes follow each
tool's own source (see advisor/current.py for the references)."""

import asyncio
import copy
import hashlib
import json
import logging
import os

import pytest

from advisor import current
from advisor.service import AdvisorService

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = "1091500"


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(data if isinstance(data, str) else json.dumps(data))
    return path


def digest(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


# SimpleDeckyTDP


def test_simpledeckytdp_game_profile_and_default(tmp_path):
    d = str(tmp_path)
    write(os.path.join(d, "settings.json"), {"enableTdpProfiles": True,
                                             "tdpProfiles": {"default": {"tdp": 12}, APP: {"tdp": 18, "cpuBoost": False}}})
    assert current.simpledeckytdp(d, APP) == {"tdp_w": 18, "scope": "this game's profile", "note": None}
    assert current.simpledeckytdp(d, "620")["scope"] == "default profile"
    write(os.path.join(d, "settings.json"), {"enableTdpProfiles": False,
                                             "tdpProfiles": {"default": {"tdp": 12}, APP: {"tdp": 18}}})
    off = current.simpledeckytdp(d, APP)
    assert off["tdp_w"] == 12 and "Per-game profiles are off" in off["note"]


# PowerControl


def test_powercontrol_overwrite_default_and_disabled(tmp_path):
    d = str(tmp_path)
    data = {"PowerControl": {"perApp": {
        "0": {"overwrite": False, "defaultSettig": {"tdp": 10, "tdpEnable": True}},
        APP: {"overwrite": True, "acStateOverwrite": True, "defaultSettig": {"tdp": 20, "tdpEnable": True}},
        "620": {"overwrite": False, "defaultSettig": {"tdp": 25, "tdpEnable": True}},
        "730": {"overwrite": True, "defaultSettig": {"tdp": 25, "tdpEnable": False}},
    }}}
    write(os.path.join(d, "config.json"), data)
    game = current.powercontrol(d, APP)
    assert game["tdp_w"] == 20 and game["scope"] == "this game's profile" and "AC and battery" in game["note"]
    assert current.powercontrol(d, "620") == {"tdp_w": 10, "scope": "default profile", "note": None}
    assert current.powercontrol(d, "730")["tdp_w"] is None


# LeGoTDP and Legion Go 2 Companion, milliwatts


@pytest.mark.parametrize("reader,filename", [
    (current.legotdp, "settings.json"),
    (current.legiongo2companion, "tdp_settings.json"),
])
def test_lenovo_tools_read_milliwatts(tmp_path, reader, filename):
    d = str(tmp_path)
    write(os.path.join(d, filename), {
        "settings": {"spl": 15000, "sppt": 18000, "fppt": 25000},
        "game_profiles": {APP: {"spl": 22000, "sppt": 25000, "fppt": 30000, "preset": "Performance", "ac_separate": True}},
        "inactive_game_profiles": {"620": {"spl": 8000}},
    })
    game = reader(d, APP)
    assert game["tdp_w"] == 22 and game["preset"] == "Performance" and "AC power" in game["note"]
    assert reader(d, "620") == {"tdp_w": 15, "scope": "global setting", "preset": None, "note": None}, \
        "a paused profile is ignored"


# LSFG-VK


def test_lsfg_profile_for_this_game(tmp_path):
    home = str(tmp_path)
    write(os.path.join(home, ".config", "lsfg-vk", "conf.toml"), """version = 2

[global]
allow_fp16 = true

[[profile]]
name = "Cyberpunk 2077"
active_in = [ "1091500" ]
pacing_mode = "vsync"
multiplier = 3
flow_scale = 0.75
performance_mode = true
""")
    assert current.lsfg(home, APP) == {"profile": "Cyberpunk 2077", "multiplier": 3, "flow_scale": 0.75,
                                       "performance_mode": True}
    assert current.lsfg(home, "620")["profile"] is None


def test_unknown_or_broken_formats_are_skipped(tmp_path):
    d = str(tmp_path)
    assert current.simpledeckytdp(d, APP) is None
    write(os.path.join(d, "settings.json"), "{not json")
    assert current.simpledeckytdp(d, APP) is None and current.legotdp(d, APP) is None
    write(os.path.join(d, "settings.json"), {"tdpProfiles": {"default": {"tdp": "lots"}}})
    assert current.simpledeckytdp(d, APP) is None
    write(os.path.join(d, "settings.json"), {"game_profiles": {APP: {"spl": 999999999}}})
    assert current.legotdp(d, APP) is None, "an implausible wattage is not shown"
    write(os.path.join(d, ".config", "lsfg-vk", "conf.toml"), 'version = 1\n')
    assert current.lsfg(d, APP) is None


def test_read_picks_the_selected_tool_and_its_folder(tmp_path):
    decky = str(tmp_path / "homebrew")
    write(os.path.join(decky, "settings", "SimpleDeckyTDP-main", "settings.json"),
          {"enableTdpProfiles": True, "tdpProfiles": {APP: {"tdp": 14}}})
    detected = {"tools": [{"id": "simpledeckytdp", "folder": "SimpleDeckyTDP-main"},
                          {"id": "powercontrol", "folder": "PowerControl", "disabled": True}]}
    got = current.read({"power": "simpledeckytdp", "framegen": "none"}, detected, decky, str(tmp_path), 1091500)
    assert got["power"]["tdp_w"] == 14 and got["power"]["tool"] == "simpledeckytdp" and got["framegen"] is None
    assert current.read({"power": "powercontrol"}, detected, decky, str(tmp_path), 1091500)["power"] is None
    assert current.read({"power": "steam-native"}, detected, decky, str(tmp_path), 1091500)["power"] is None
    assert current.read({"power": "simpledeckytdp"}, detected, decky, str(tmp_path), None) == {"power": None, "framegen": None}


# Service: shown in the view, files untouched


def test_service_shows_current_values_and_never_writes(tmp_path, device_root, dv_fixture):
    decky = tmp_path / "homebrew"
    plugin = decky / "plugins" / "LeGoTDP"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(json.dumps({"name": "LeGoTDP"}))
    settings_file = write(str(decky / "settings" / "LeGoTDP" / "settings.json"),
                          {"game_profiles": {APP: {"spl": 18000, "preset": "Balanced"}}})
    lsfg_plugin = decky / "plugins" / "lsfg"
    lsfg_plugin.mkdir(parents=True)
    (lsfg_plugin / "plugin.json").write_text(json.dumps({"name": "Decky LSFG-VK"}))
    home = tmp_path / "home"
    conf = write(str(home / ".config" / "lsfg-vk" / "conf.toml"),
                 'version = 2\n\n[[profile]]\nname = "X"\nactive_in = [ "1091500" ]\nmultiplier = 2\nflow_scale = 0.8\n')
    before = (digest(settings_file), digest(conf), os.path.getmtime(settings_file), os.path.getmtime(conf))

    async def emit(*_):
        pass

    service = AdvisorService(
        settings_dir=str(tmp_path / "s"), runtime_dir=str(tmp_path / "r"), plugin_dir=PLUGIN,
        decky_home=str(decky), user_home=str(home), user="deck", version="0.5.0", emit=emit,
        logger=logging.getLogger("test"), root=device_root("synthetic-legion-go-2-z2e"),
        fetch_reports=lambda appid, name: copy.deepcopy(dv_fixture),
    )
    service.detect()
    view = asyncio.new_event_loop().run_until_complete(service.set_game(1091500, "Cyberpunk 2077"))
    assert view["stack"]["selected"]["power"] == "legotdp"
    assert view["current"]["power"] == {"tdp_w": 18, "scope": "this game's profile", "preset": "Balanced",
                                        "note": None, "tool": "legotdp"}
    assert view["current"]["framegen"]["multiplier"] == 2
    after = (digest(settings_file), digest(conf), os.path.getmtime(settings_file), os.path.getmtime(conf))
    assert before == after, "other tools' files must never change"
