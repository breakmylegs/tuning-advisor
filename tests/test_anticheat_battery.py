"""Anti-cheat status and battery estimates. No live calls."""

import asyncio
import copy
import json
import logging
import os

import pytest

from advisor import anticheat, deckverified, recommend, registry as regmod
from advisor.service import AdvisorService
from plugin_core.errors import PluginError

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = regmod.load(os.path.join(PLUGIN, "registry"))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# Anti-cheat list


def test_trim_keeps_known_statuses_and_safe_links(no_live_anticheat):
    data = anticheat.trim(json.loads(no_live_anticheat))
    assert set(data["by_appid"]) == {"976730", "1172470"}, "unknown statuses are dropped"
    shooter = data["by_appid"]["976730"]
    assert shooter["status"] == "Supported" and shooter["anticheats"] == ["Easy Anti-Cheat"]
    assert len(shooter["notes"]) == 3, "at most three notes"
    # Only https links survive. A javascript: link is blanked.
    assert data["by_appid"]["1172470"]["notes"][0]["url"] == ""
    assert "example store exclusive" in data["by_name"]


def test_trim_rejects_bad_lists():
    with pytest.raises(PluginError):
        anticheat.trim({"not": "a list"})
    with pytest.raises(PluginError):
        anticheat.trim([{"status": "Maybe"}])


def test_lookup_by_appid_and_by_name(tmp_path):
    ac = anticheat.AntiCheatList(str(tmp_path))
    ac.ensure()
    supported = ac.lookup(976730)
    assert supported["blocked"] is False and supported["by_name"] is False
    assert supported["url"] == "https://areweanticheatyet.com/game/example-shooter"
    assert "works under Proton" in supported["meaning"]
    denied = ac.lookup(1172470)
    assert denied["blocked"] is True and denied["status"] == "Denied"
    shortcut = ac.lookup(None, "  Example Store Exclusive ")
    assert shortcut["status"] == "Broken" and shortcut["by_name"] is True
    assert ac.lookup(123) is None and ac.lookup(None, "") is None


def test_refresh_is_weekly_and_keeps_the_old_copy_offline(tmp_path, no_live_anticheat):
    calls = []
    clock = [1_000_000.0]

    def fetch():
        calls.append(1)
        if len(calls) > 1:
            raise PluginError("offline", "no network")
        return no_live_anticheat

    ac = anticheat.AntiCheatList(str(tmp_path), fetch=fetch, now=lambda: clock[0])
    ac.ensure()
    os.utime(ac.path, (clock[0], clock[0]))
    ac.ensure()
    assert len(calls) == 1, "a fresh copy is not downloaded again"
    clock[0] += anticheat.REFRESH_AFTER + 1
    ac.ensure()
    assert len(calls) == 2 and ac.lookup(976730), "a failed refresh keeps the old copy"


def test_failed_refresh_waits_an_hour_unless_forced(tmp_path, no_live_anticheat):
    calls = []
    clock = [1_000_000.0]

    def offline():
        calls.append(1)
        raise PluginError("offline", "no network")

    ac = anticheat.AntiCheatList(str(tmp_path), fetch=offline, now=lambda: clock[0])
    with pytest.raises(PluginError):
        ac.ensure()
    with pytest.raises(PluginError) as err:
        ac.ensure()
    assert len(calls) == 1 and "Refresh reports" in err.value.message, "no retry within the hour"
    with pytest.raises(PluginError):
        ac.ensure(force=True)
    assert len(calls) == 2, "Refresh reports tries again at once"
    clock[0] += anticheat.RETRY_AFTER + 1
    with pytest.raises(PluginError):
        ac.ensure()
    assert len(calls) == 3


def test_a_slow_load_does_not_overwrite_a_newer_game(tmp_path, device_root, dv_fixture, no_live_anticheat):
    service = make_service(tmp_path, device_root, dv_fixture)

    async def scenario():
        first = asyncio.ensure_future(service.set_game(1172470, "Example Battle Royale"))
        await asyncio.sleep(0)
        await service.set_game(976730, "Example Shooter")
        await first

    asyncio.new_event_loop().run_until_complete(scenario())
    assert service.game["appid"] == 976730
    assert service.ac_state["entry"]["status"] == "Supported"


def test_first_download_failure_raises(tmp_path):
    def offline():
        raise PluginError("offline", "no network")

    with pytest.raises(PluginError):
        anticheat.AntiCheatList(str(tmp_path), fetch=offline).ensure()


# Service


def make_service(tmp_path, device_root, dv_fixture, **kwargs):
    async def emit(*_):
        pass

    service = AdvisorService(
        settings_dir=str(tmp_path / "s"), runtime_dir=str(tmp_path / "r"), plugin_dir=PLUGIN,
        decky_home=str(tmp_path / "h"), user_home=str(tmp_path / "home"), user="deck", version="0.10.0", emit=emit,
        logger=logging.getLogger("test"), root=device_root("synthetic-legion-go-2-z2e"),
        fetch_reports=lambda appid, name: copy.deepcopy(dv_fixture), **kwargs,
    )
    service.detect()
    return service


def test_service_shows_anti_cheat_for_the_game(tmp_path, device_root, dv_fixture):
    service = make_service(tmp_path, device_root, dv_fixture)
    view = _run(service.set_game(1172470, "Example Battle Royale"))
    entry = view["anticheat"]["entry"]
    assert view["anticheat"]["enabled"] is True and entry["status"] == "Denied" and entry["blocked"] is True
    assert "MIT" in entry["attribution"]
    view = _run(service.set_game(1091500, "Cyberpunk 2077"))
    assert view["anticheat"]["entry"] is None and view["anticheat"]["error"] is None


def test_service_anti_cheat_can_be_turned_off(tmp_path, device_root, dv_fixture):
    calls = []

    def fetch():
        calls.append(1)
        return b"[]"

    service = make_service(tmp_path, device_root, dv_fixture, anticheat_fetch=fetch)
    _run(service.save_settings({"source_anticheat": False}))
    view = _run(service.set_game(1172470, "Example Battle Royale"))
    assert view["anticheat"] == {"enabled": False, "error": None, "entry": None} and calls == []


def test_service_anti_cheat_failure_is_reported(tmp_path, device_root, dv_fixture):
    def offline():
        raise PluginError("offline", "no network")

    service = make_service(tmp_path, device_root, dv_fixture, anticheat_fetch=offline)
    view = _run(service.set_game(1172470, "Example Battle Royale"))
    assert view["anticheat"]["error"]["kind"] == "offline"
    assert "deckverified" in {r["source"] for r in view["recommendations"]}


def test_clear_cache_removes_the_anti_cheat_list(tmp_path, device_root, dv_fixture):
    service = make_service(tmp_path, device_root, dv_fixture)
    _run(service.set_game(1172470, "Example Battle Royale"))
    assert os.path.exists(service.anticheat.path)
    service.clear_cache()
    assert not os.path.exists(service.anticheat.path)


# Battery


@pytest.mark.parametrize(
    "raw,watts",
    [("15", 15.0), ("12.5", 12.5), ("Unknown", None), (None, None), ("0", None), ("500", None), (True, None)],
)
def test_battery_draw_parsing(raw, watts):
    assert deckverified._watts(raw) == watts


def test_normalise_reads_battery_fields():
    rec = deckverified.normalise({"data": {"average_battery_power_draw": "17", "calculated_battery_life_minutes": 196}})
    assert rec["battery"] == {"draw_w": 17.0, "minutes": 196}


def _rec(draw, match, device_reported="Lenovo Legion Go S", minutes=None):
    return {"battery": {"draw_w": draw, "minutes": minutes}, "device_match": match, "device_reported": device_reported}


def test_battery_estimate_on_this_device():
    go2 = REG.device("lenovo-legion-go-2-z2e")
    assert recommend.battery_lines(_rec(17.0, "exact"), go2) == [
        "Reported battery draw 17 W. On your 74 Wh battery that is about 4h 21m."
    ]


def test_battery_estimate_from_another_device_is_labelled_rough():
    go2 = REG.device("lenovo-legion-go-2-z2e")
    (line,) = recommend.battery_lines(_rec(12.5, "other_handheld", "ASUS ROG Ally X"), go2)
    assert "on ASUS ROG Ally X" in line and "about 5h 55m" in line and "rough guide" in line


def test_battery_estimate_for_a_generic_device_uses_the_reported_figure():
    generic = {"generic": True, "battery_wh": None}
    assert recommend.battery_lines(_rec(10.0, "generic", "ASUS ROG Ally X", 480), generic) == [
        "Reported battery draw 10 W on ASUS ROG Ally X, about 8h 00m on its battery."
    ]
    assert recommend.battery_lines(_rec(None, "exact"), generic) == []


def test_battery_lines_reach_the_recommendation():
    go2 = REG.device("lenovo-legion-go-2-z2e")
    report = deckverified.normalise({"data": {"device": "Lenovo Legion Go 2", "average_battery_power_draw": "20"}})
    recs = recommend.build([report], REG, go2, {"power": "none"}, "medium", False)
    assert any("74 Wh battery" in line for line in recs[0]["lines"]["battery"])
    assert recs[-1]["source"] == "fallback" and recs[-1]["lines"]["battery"] == []
