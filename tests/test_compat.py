import asyncio
import copy
import json
import logging
import os

import pytest

from advisor import compat, deckverified
from advisor.service import AdvisorService

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LSFG = {"framegen": "lsfg-vk"}


# Parsing


def test_parse_shape():
    p = compat.parse("PROTON_LOG=1 DXVK_HUD=fps ~/lsfg %command% -skipintro")
    assert p["env"] == ["PROTON_LOG=1", "DXVK_HUD=fps"]
    assert p["wrappers"] == ["~/lsfg"] and p["args"] == ["-skipintro"] and p["has_command"]


def test_parse_without_command_is_game_args():
    p = compat.parse("--launcher-skip -dx11")
    assert p["args"] == ["--launcher-skip", "-dx11"] and not p["has_command"] and p["wrappers"] == []


def test_env_after_a_wrapper_belongs_to_the_wrapper():
    p = compat.parse("gamemoderun FOO=1 %command%")
    assert p["env"] == [] and p["wrappers"] == ["gamemoderun", "FOO=1"]


def test_parse_tolerates_bad_quotes_and_control_chars():
    p = compat.parse('FOO="unbalanced %command%\x07')
    assert "\x07" not in p["raw"] and p["has_command"]


# Flags


def test_flags_unknown_wrapper_and_shell_operators():
    flags = compat.flags_for(compat.parse("/data/path1/mako-run %command%"), LSFG)
    assert any("Runs /data/path1/mako-run before the game" in f for f in flags)
    flags = compat.flags_for(compat.parse("FOO=1 %command%; rm -rf ~"), LSFG)
    assert any("shell operators" in f for f in flags)
    flags = compat.flags_for(compat.parse("echo $(id) %command%"), LSFG)
    assert any("shell operators" in f for f in flags)


def test_env_and_command_only_has_no_flags():
    assert compat.flags_for(compat.parse("PROTON_LOG=1 %command%"), {}) == []


def test_stack_wrapper_needs_tool():
    flags = compat.flags_for(compat.parse("~/lsfg %command%"), {"framegen": "none"})
    assert flags == ["~/lsfg needs lsfg-vk, which is not in your selected tools."]
    assert compat.flags_for(compat.parse("~/lsfg %command%"), LSFG) == []


def test_args_without_command_flagged():
    flags = compat.flags_for(compat.parse("-novid"), {})
    assert any("no %command%" in f for f in flags)


def test_fsr4_env_removed():
    section = compat.launch_section("PROTON_FSR4_UPGRADE=1 PROTON_LOG=1 %command%", "", {}, False)
    assert section["recommended"] == "PROTON_LOG=1 %command%"
    assert any("FSR 4" in f for f in section["flags"])


# Merging


def test_merge_keeps_stack_wrapper_and_explains():
    section = compat.launch_section("PROTON_LOG=1 %command% -skipintro", "~/lsfg %command%", LSFG, False)
    assert section["merged"] == "PROTON_LOG=1 ~/lsfg %command% -skipintro"
    assert "Keeps ~/lsfg from your current options." in section["merge_notes"]


def test_merge_recommended_env_wins_and_notes_change():
    section = compat.launch_section("DXVK_ASYNC=1 %command%", "DXVK_ASYNC=0 %command%", {}, False)
    assert section["merged"] is None or "DXVK_ASYNC=1" in section["merged"]
    merged, notes = compat.merge(compat.parse("DXVK_ASYNC=0 %command%"), compat.parse("DXVK_ASYNC=1 %command%"))
    assert merged["env"] == ["DXVK_ASYNC=1"] and notes == ["Changes DXVK_ASYNC=0 to DXVK_ASYNC=1."]


def test_merge_turns_old_args_into_args_after_command():
    merged, notes = compat.merge(compat.parse("-novid"), compat.parse("PROTON_LOG=1 %command%"))
    assert compat.join(merged) == "PROTON_LOG=1 %command% -novid"
    assert any("game arguments" in n for n in notes)


def test_same_as_current_needs_no_merge():
    section = compat.launch_section("~/lsfg %command%", "~/lsfg %command%", LSFG, False)
    assert section["same_as_current"] is True and section["merged"] is None


def test_no_recommended_launch_options_means_no_section():
    assert compat.launch_section(None, "~/lsfg %command%", LSFG, False) is None


def test_shortcut_location():
    section = compat.launch_section("PROTON_LOG=1 %command%", "", {}, True)
    assert "Shortcut, Launch Options" in section["where"]


# Proton names


@pytest.mark.parametrize(
    "tool,version,name,force",
    [
        ("Steam Proton", "default", "Steam's default", False),
        ("Steam Proton", "proton experimental", "Proton Experimental", True),
        ("Steam Proton", "Experimental", "Proton Experimental", True),
        ("Steam Proton", "9.0-3", "Proton 9.0", True),
        ("Steam Proton", "10.0", "Proton 10.0", True),
        ("Steam Proton", "Hotfix", "Proton Hotfix", True),
        ("Glorious Eggroll Proton (GE)", "10-20", "GE-Proton10-20", True),
        ("Glorious Eggroll Proton (GE)", "latest", "GE-Proton (latest)", True),
        ("Native Linux", "", "None. Native Linux build", False),
    ],
)
def test_proton_names(tool, version, name, force):
    named = compat.proton_name(tool, version)
    assert (named["name"], named["force"]) == (name, force)


def test_ge_proton_install_note_and_build():
    assert "ProtonUp-Qt" in compat.proton_name("Glorious Eggroll Proton (GE)", "10-20")["install_note"]
    assert compat.proton_name("Steam Proton", "9.0-3")["build"] == "9.0-3"


def test_proton_matches_current():
    rec = {"tool": "Steam Proton", "tool_version": "9.0-3"}
    assert compat.proton_section(rec, "Proton 9.0-4")["matches"] is True
    assert compat.proton_section(rec, "Proton Experimental")["matches"] is False
    default = {"tool": "Steam Proton", "tool_version": "default"}
    assert compat.proton_section(default, "")["matches"] is True
    assert compat.proton_section(default, "")["current"] == "Steam's default"
    assert compat.proton_section({"tool": None, "tool_version": None}, "") is None


# Fixture and service


def test_fixture_reports_produce_sections(dv_fixture):
    recs = [deckverified.normalise(r) for r in dv_fixture["reports"]]
    sections = [compat.section(r, {"launch_options": "", "compat_tool": ""}, LSFG, False) for r in recs]
    assert all(s is not None for s in sections)
    mako = next(s for s in sections if s["launch"] and "/data/path1" in s["launch"]["recommended"])
    assert any("before the game" in f for f in mako["launch"]["flags"])
    ge = next(s for s in sections if s["proton"]["recommended"].startswith("GE-Proton"))
    assert ge["proton"]["recommended"] == "GE-Proton10-20"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_service_attaches_sections_with_current_values(tmp_path, device_root, dv_fixture):
    async def emit(*_):
        pass

    service = AdvisorService(
        settings_dir=str(tmp_path / "s"), runtime_dir=str(tmp_path / "r"), plugin_dir=PLUGIN,
        decky_home=str(tmp_path / "h"), user_home=str(tmp_path / "u"), user="deck", version="0.2.0", emit=emit,
        logger=logging.getLogger("test"), root=device_root("synthetic-legion-go-2-z2e"),
        fetch_reports=lambda appid, name: copy.deepcopy(dv_fixture),
    )
    service.detect()
    view = _run(service.set_game(1091500, "Cyberpunk 2077", None, False, "~/lsfg %command%", "Proton Experimental"))
    recs = view["recommendations"]
    assert recs[-1]["source"] == "fallback" and recs[-1]["compat_section"] is None
    with_launch = [r for r in recs if r["compat_section"] and r["compat_section"]["launch"]]
    assert with_launch and all(r["compat_section"]["launch"]["current"] == "~/lsfg %command%" for r in with_launch)
    service.set_current_compat("", "")
    view = service.view()
    assert all((r["compat_section"] or {}).get("launch", {}) in (None, {}) or r["compat_section"]["launch"]["current"] == ""
               for r in view["recommendations"])
    assert "SetAppLaunchOptions" not in json.dumps(view)
