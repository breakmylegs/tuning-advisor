import asyncio
import copy
import json
import logging
import os
from datetime import datetime, timezone

import pytest

from advisor import deckverified, device as devmod, recommend, registry as regmod, stack as stackmod
from advisor.cache import TTL, SourceCache
from advisor.service import AdvisorService
from plugin_core.errors import OFFLINE, PluginError

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = regmod.load(os.path.join(PLUGIN, "registry"))
NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def dev(device_id):
    return REG.device(device_id)


# Registry integrity


def test_registry_ids_unique_and_fields_present():
    ids = [d["id"] for d in REG.devices]
    assert len(ids) == len(set(ids)) == 17
    for d in REG.devices:
        assert d["tdp_w"]["min"] < d["tdp_w"]["max"], d["id"]
        assert d["display"]["refresh_hz_max"], d["id"]
        assert d["sources"], d["id"]
        assert d["match"], d["id"]
        for pattern in d["report_aliases"]:
            __import__("re").compile(pattern)


def test_derived_bands_match_the_formula():
    for d in REG.devices:
        bands = d["tdp_bands_w"]
        if bands.get("derived"):
            expected = regmod.derived_bands(d["tdp_w"]["min"], d["tdp_w"]["max"])
            assert {k: bands[k] for k in regmod.BAND_FRACTIONS} == {k: expected[k] for k in regmod.BAND_FRACTIONS}, d["id"]
        for k in ("light", "medium", "heavy", "max"):
            assert d["tdp_w"]["min"] <= bands[k] <= d["tdp_w"]["max"], (d["id"], k)


def test_stack_registry_ids_unique_and_vocab_has_watts():
    ids = [t["id"] for t in REG.tools]
    assert len(ids) == len(set(ids))
    for t in REG.tools:
        if "power" in t["categories"]:
            assert "{w}" in t["vocabulary"]["power"], t["id"]


# Device detection


@pytest.mark.parametrize(
    "capture,expected",
    [
        ("synthetic-legion-go-2-z2e", "lenovo-legion-go-2-z2e"),
        ("synthetic-steam-deck-oled", "valve-steam-deck-oled"),
        ("synthetic-rog-ally-z1", "asus-rog-ally-z1"),
    ],
)
def test_detect_from_capture(device_root, capture, expected):
    facts = devmod.read_facts(device_root(capture))
    found, how = devmod.resolve(REG, facts)
    assert (found["id"], how) == (expected, "detected")


def test_cpu_splits_variants_that_share_dmi():
    base = {"sys_vendor": "LENOVO", "product_name": "83N1"}
    assert devmod.detect(REG, {**base, "cpu_model": "AMD Ryzen Z2 Extreme"})["id"] == "lenovo-legion-go-2-z2e"
    assert devmod.detect(REG, {**base, "cpu_model": "AMD Ryzen Z2"})["id"] == "lenovo-legion-go-2-z2"
    ally = {"board_name": "RC71L"}
    assert devmod.detect(REG, {**ally, "cpu_model": "AMD Ryzen Z1 Extreme"})["id"] == "asus-rog-ally-z1e"
    gos = {"sys_vendor": "LENOVO", "product_name": "83L3"}
    assert devmod.detect(REG, {**gos, "cpu_model": "AMD Ryzen Z2 Go"})["id"] == "lenovo-legion-go-s-z2go"
    # Lenovo PSREF lists a Z1 Legion Go as well as the Z1 Extreme one.
    go = {"sys_vendor": "LENOVO", "product_name": "83E1"}
    assert devmod.detect(REG, {**go, "cpu_model": "AMD Ryzen Z1"})["id"] == "lenovo-legion-go-z1"
    assert devmod.detect(REG, {**go, "cpu_model": "AMD Ryzen Z1 Extreme"})["id"] == "lenovo-legion-go"
    assert devmod.detect(REG, {**go, "cpu_model": ""})["id"] == "lenovo-legion-go"


def test_variant_split_does_not_depend_on_registry_order():
    reversed_reg = regmod.Registry(devices=list(reversed(REG.devices)), tools=REG.tools, categories=REG.categories)
    go2 = {"sys_vendor": "LENOVO", "product_name": "83N0", "cpu_model": "AMD Ryzen Z2 Extreme"}
    assert devmod.detect(reversed_reg, go2)["id"] == "lenovo-legion-go-2-z2e"
    ally = {"board_name": "RC71L", "cpu_model": "AMD Ryzen Z1 Extreme"}
    assert devmod.detect(reversed_reg, ally)["id"] == "asus-rog-ally-z1e"


def test_unknown_device_gets_generic_profile(device_root):
    facts = devmod.read_facts(device_root("synthetic-unknown-handheld"))
    found, how = devmod.resolve(REG, facts)
    assert how == "generic" and found["generic"] and found["gpu"]["vendor"] == "amd"
    assert found["tdp_bands_w"]["derived"] is True


def test_override_wins(device_root):
    facts = devmod.read_facts(device_root("synthetic-steam-deck-oled"))
    found, how = devmod.resolve(REG, facts, override="msi-claw-a8")
    assert (found["id"], how) == ("msi-claw-a8", "override")
    found, how = devmod.resolve(REG, facts, override="not-a-device")
    assert how == "detected"


def test_os_detection(device_root):
    assert stackmod.read_os(device_root("synthetic-rog-ally-z1"))["id"] == "bazzite"
    assert stackmod.read_os(device_root("synthetic-unknown-handheld"))["id"] == "chimeraos"
    assert stackmod.read_os(device_root("synthetic-steam-deck-oled"))["id"] == "steamos"


# Stack detection


def test_plugins_matched_by_normalised_name_and_disabled_excluded(decky_home, tmp_path):
    home = decky_home(["SimpleDeckyTDP", "Legion Go 2 Companion", "decky lsfg-vk", "PowerTools"], disabled=["PowerTools"])
    found = stackmod.detect(REG, home, str(tmp_path), "deck", dev("lenovo-legion-go-2-z2e"), root=str(tmp_path / "none"))
    ids = {t["id"]: t for t in found["tools"]}
    assert set(ids) == {"simpledeckytdp", "legiongo2companion", "lsfg-vk", "powertools"}
    assert ids["powertools"].get("disabled") is True
    assert stackmod.active_ids(found) == ["simpledeckytdp", "legiongo2companion", "lsfg-vk"]


def test_paths_and_home_paths(decky_home, tmp_path):
    root = tmp_path / "root"
    unit = root / "etc/systemd/system/multi-user.target.wants/hhd@deck.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("")
    (root / "usr/lib/steamos-manager").mkdir(parents=True)
    user_home = tmp_path / "home"
    (user_home / "lsfg").mkdir(parents=True)
    home = decky_home(["Decky LSFG-VK"])
    found = stackmod.detect(REG, home, str(user_home), "deck", dev("valve-steam-deck-oled"), root=str(root))
    ids = {t["id"]: t for t in found["tools"]}
    assert set(ids) == {"hhd", "steam-native", "lsfg-vk"}
    assert ids["lsfg-vk"]["home_paths_found"] == ["lsfg"]


def test_selection_prefers_plugins_and_manual_wins(decky_home, tmp_path):
    detected = {"tools": [{"id": "steam-native"}, {"id": "simpledeckytdp"}, {"id": "lsfg-vk"}], "os": {}}
    chosen = stackmod.select(REG, detected, {})
    assert chosen == {"power": "simpledeckytdp", "framegen": "lsfg-vk", "upscaler": "none", "fan": "none"}
    chosen = stackmod.select(REG, detected, {"power": "steam-native", "framegen": "none"})
    assert chosen["power"] == "steam-native" and chosen["framegen"] == "none"


def test_conflict_rules():
    two = {"tools": [{"id": "simpledeckytdp"}, {"id": "powercontrol"}], "os": {}}
    texts = [c["kind"] for c in stackmod.conflicts(REG, two, dev("lenovo-legion-go"))]
    assert texts == ["multiple_power"]
    lego = {"tools": [{"id": "legotdp"}, {"id": "steam-native"}], "os": {}}
    kinds = [c["kind"] for c in stackmod.conflicts(REG, lego, dev("lenovo-legion-go"))]
    assert kinds == ["legotdp_reapply"]
    none = {"tools": [], "os": {}}
    generic = devmod.generic_profile({})
    result = stackmod.conflicts(REG, none, generic)
    assert [c["kind"] for c in result] == ["no_power"] and "SimpleDeckyTDP" in result[0]["text"]
    assert stackmod.conflicts(REG, none, dev("valve-steam-deck-oled")) == []


# Deck Verified normalising


def test_normalise_fixture(dv_fixture):
    recs = [deckverified.normalise(r) for r in dv_fixture["reports"]]
    assert len(recs) == 6
    first = recs[0]
    assert first["device_reported"] == "Lenovo Legion Go S"
    assert first["frame_gen"]["tool"] == "lsfg-vk" and first["display"]["vrr"] is True
    assert first["source_url"].startswith("https://github.com/DeckSettings/")
    fsr4 = next(r for r in recs if r["upscaler"]["name"] == "FSR 4")
    assert fsr4["device_reported"] == "Lenovo Legion Go"
    assert recs[4]["display"]["fps_cap"] == 48 and recs[4]["scaling"]["game_resolution"] == "1280x800"
    assert recs[0]["in_game"]["preset"] == "Custom"


def test_normalise_coerces_and_tolerates_missing():
    rec = deckverified.normalise({"data": {"tdp_limit": "12 W", "frame_limit": 40, "disable_frame_limit": "On"}})
    assert rec["power"]["tdp_w"] == 12 and rec["display"]["fps_cap"] is None
    empty = deckverified.normalise({})
    assert empty["power"]["tdp_w"] is None and empty["votes"] == 0


# Ranking, validation, translation


def test_device_match_levels():
    mine = dev("lenovo-legion-go-2-z2e")
    assert recommend.device_match(REG, "Lenovo Legion Go 2", mine) == "exact"
    assert recommend.device_match(REG, "Lenovo Legion Go 2", dev("lenovo-legion-go-2-z2")) == "variant"
    assert recommend.device_match(REG, "Lenovo Legion Go S", mine) == "family"
    assert recommend.device_match(REG, "MSI Claw A8", mine) == "same_apu"
    assert recommend.device_match(REG, "Valve Steam Deck OLED", mine) == "steam_deck"
    assert recommend.device_match(REG, "GPD Win 4", mine) == "other_handheld"
    assert recommend.device_match(REG, "ASUS ROG Ally X", mine) == "other_handheld"


def test_rank_order_match_then_recency_then_votes():
    def r(match_dev, date, votes):
        return {"device_reported": match_dev, "report_date": date, "votes": votes}

    mine = dev("lenovo-legion-go-2-z2e")
    recs = [r("Valve Steam Deck OLED", "2026-10-01T00:00:00Z", 50), r("Lenovo Legion Go S", "2024-01-01T00:00:00Z", 9),
            r("Lenovo Legion Go S", "2026-09-01T00:00:00Z", 0), r("Lenovo Legion Go 2", "2025-01-01T00:00:00Z", 0),
            r("Lenovo Legion Go S", "2026-08-01T00:00:00Z", 3)]
    for rec in recs:
        rec["device_match"] = recommend.device_match(REG, rec["device_reported"], mine)
    ranked = recommend.rank(recs, NOW)
    assert [(x["device_reported"], x["votes"]) for x in ranked] == [
        ("Lenovo Legion Go 2", 0), ("Lenovo Legion Go S", 3), ("Lenovo Legion Go S", 0),
        ("Lenovo Legion Go S", 9), ("Valve Steam Deck OLED", 50)]


def base_rec(**over):
    rec = recommend.fallback(dev("valve-steam-deck-lcd"), "medium")
    rec.update(source="deckverified", device_match="exact")
    for key, value in over.items():
        rec[key] = value
    return rec


def test_validate_clamps_tdp_and_drops_bad_refresh():
    deck = dev("valve-steam-deck-lcd")
    out = recommend.validate(base_rec(power={"tdp_w": 25, "gpu_clock_mhz": None},
                                      display={"refresh_hz": 120, "fps_cap": None, "vrr": None}), deck, {})
    assert out["power"]["tdp_w"] == 15 and out["display"]["refresh_hz"] is None
    assert len(out["flags"]) == 2
    out = recommend.validate(base_rec(power={"tdp_w": 2, "gpu_clock_mhz": None}), deck, {})
    assert out["power"]["tdp_w"] == 4


def test_fps_cap_rules_with_and_without_vrr():
    deck = dev("valve-steam-deck-lcd")
    bad = recommend.validate(base_rec(display={"refresh_hz": None, "fps_cap": 45, "vrr": None}), deck, {})
    assert any("Try 30" in f for f in bad["flags"])
    ok = recommend.validate(base_rec(display={"refresh_hz": None, "fps_cap": 30, "vrr": None}), deck, {})
    assert ok["flags"] == []
    go2 = dev("lenovo-legion-go-2-z2e")
    vrr_ok = recommend.validate(base_rec(display={"refresh_hz": None, "fps_cap": 45, "vrr": True}), go2, {})
    assert vrr_ok["flags"] == []
    vrr_low = recommend.validate(base_rec(display={"refresh_hz": None, "fps_cap": 25, "vrr": True}), go2, {})
    assert any("VRR range" in f for f in vrr_low["flags"])
    no_vrr = recommend.validate(base_rec(display={"refresh_hz": None, "fps_cap": 30, "vrr": True}), deck, {})
    assert no_vrr["display"]["vrr"] is False


def test_fsr4_never_recommended(dv_fixture):
    rec = deckverified.normalise(dv_fixture["reports"][4])
    rec["device_match"] = "exact"
    out = recommend.validate(rec, dev("lenovo-legion-go"), {})
    assert out["upscaler"]["name"] is None
    assert not any("4" in s["value"] and "Resolution" in s["value"] for s in out["in_game"]["settings"])
    assert any("FSR 4" in f for f in out["flags"])


def test_requires_tool_note():
    rec = base_rec(frame_gen={"tool": "lsfg-vk", "mode": None})
    out = recommend.validate(rec, dev("valve-steam-deck-lcd"), {"framegen": "none"})
    assert out["frame_gen"]["requires"] == "lsfg-vk"
    out = recommend.translate(out, REG, dev("valve-steam-deck-lcd"), {"framegen": "none"})
    assert "Requires Decky LSFG-VK." in out["lines"]["frame_gen"]
    ok = recommend.validate(rec, dev("valve-steam-deck-lcd"), {"framegen": "lsfg-vk"})
    assert "requires" not in ok["frame_gen"]


@pytest.mark.parametrize(
    "power,device_id,watts,expected",
    [
        ("steam-native", "valve-steam-deck-lcd", 10, "Set TDP Limit to 10 W in Steam, Quick Access, Performance."),
        ("simpledeckytdp", "lenovo-legion-go-2-z2e", 15, "Set TDP (Watts) to 15 in SimpleDeckyTDP."),
        ("legotdp", "lenovo-legion-go", 17, "Select Balanced (15 W) in LeGoTDP, or set SPL (Sustained) to 17 W."),
        ("legotdp", "lenovo-legion-go-s-z1e", 20, "Select Balanced (18 W) in LeGoTDP, or set SPL (Sustained) to 20 W."),
        ("none", "lenovo-legion-go", 12, "Set the TDP to 12 W. No power tool is selected."),
    ],
)
def test_power_vocabulary(power, device_id, watts, expected):
    rec = base_rec(power={"tdp_w": watts, "gpu_clock_mhz": None})
    out = recommend.translate(rec, REG, dev(device_id), {"power": power})
    assert out["lines"]["power"][0] == expected


@pytest.mark.parametrize(
    "device_id,workload,tdp,cap",
    [
        ("valve-steam-deck-lcd", "medium", 10, 30),
        ("valve-steam-deck-lcd", "light", 7, 60),
        ("valve-steam-deck-oled", "medium", 10, 45),
        ("lenovo-legion-go-2-z2e", "heavy", 20, 30),
        ("lenovo-legion-go-2-z2e", "medium", 16, 45),
        ("lenovo-legion-go", "medium", 15, 36),
    ],
)
def test_fallback(device_id, workload, tdp, cap):
    rec = recommend.fallback(dev(device_id), workload)
    assert rec["power"]["tdp_w"] == tdp and rec["display"]["fps_cap"] == cap
    assert rec["notes"].startswith("General guidance, not game-specific.")
    assert recommend.validate(rec, dev(device_id), {})["flags"] == []


def test_build_puts_fallback_last_and_scores_confidence(dv_fixture):
    reports = [deckverified.normalise(r) for r in dv_fixture["reports"]]
    recs = recommend.build(reports, REG, dev("lenovo-legion-go-s-z1e"), {"power": "steam-native"}, "medium", False, NOW)
    assert recs[-1]["source"] == "fallback" and len(recs) == 7
    assert recs[0]["device_match"] == "exact"
    assert recs[0]["confidence"] == "high"
    shortcut = recommend.build(reports, REG, dev("lenovo-legion-go-s-z1e"), {}, "medium", True, NOW)
    assert {r["confidence"] for r in shortcut} == {"low"}


# Cache


def test_cache_ttl_and_clear(tmp_path):
    now = {"t": 1000.0}
    cache = SourceCache(str(tmp_path), now=lambda: now["t"])
    cache.put("deckverified", "app:1:build:", {"reports": []})
    data, stored = cache.get("deckverified", "app:1:build:")
    assert cache.fresh(stored)
    now["t"] += TTL + 1
    assert not cache.fresh(stored)
    assert cache.get("deckverified", "app:2:build:") is None
    assert cache.clear() == 1


# Service


def make_service(tmp_path, device_root, capture="synthetic-legion-go-2-z2e", fetch=None, plugins=None):
    events = []

    async def emit(name, payload):
        events.append((name, payload))

    home = tmp_path / "homebrew"
    for i, name in enumerate(plugins or []):
        folder = home / "plugins" / f"p{i}"
        folder.mkdir(parents=True)
        (folder / "plugin.json").write_text(json.dumps({"name": name}))
    calls = []

    def default_fetch(appid, name):
        calls.append((appid, name))
        return copy.deepcopy(fetch) if fetch is not None else {"reports": []}

    service = AdvisorService(
        settings_dir=str(tmp_path / "settings"), runtime_dir=str(tmp_path / "runtime"), plugin_dir=PLUGIN,
        decky_home=str(home), user_home=str(tmp_path / "user"), user="deck", version="0.1.0", emit=emit,
        logger=logging.getLogger("test"), root=device_root(capture), fetch_reports=default_fetch,
    )
    service.detect()
    return service, calls, events


def test_service_end_to_end(tmp_path, device_root, dv_fixture):
    service, calls, _ = make_service(tmp_path, device_root, fetch=dv_fixture, plugins=["SimpleDeckyTDP"])
    view = _run(service.set_game(1091500, "Cyberpunk 2077", build_id=123))
    assert view["device"]["id"] == "lenovo-legion-go-2-z2e" and view["device"]["how"] == "detected"
    assert view["stack"]["selected"]["power"] == "simpledeckytdp"
    recs = view["recommendations"]
    assert recs[-1]["source"] == "fallback" and len(recs) == 7
    assert recs[0]["device_match"] == "family"
    assert all(r["lines"] for r in recs)
    assert calls == [(1091500, None)]
    _run(service.set_game(1091500, "Cyberpunk 2077", build_id=123))
    assert len(calls) == 1, "second load must come from the cache"
    _run(service.refresh())
    assert len(calls) == 2


def test_service_shortcut_uses_name_and_low_confidence(tmp_path, device_root, dv_fixture):
    service, calls, _ = make_service(tmp_path, device_root, fetch=dv_fixture)
    view = _run(service.set_game(3_000_000_000, "Cyberpunk 2077 (Heroic)"))
    assert calls == [(None, "Cyberpunk 2077 (Heroic)")]
    assert view["game"]["shortcut"] is True
    assert {r["confidence"] for r in view["recommendations"]} == {"low"}


def test_service_offline_serves_stale_cache(tmp_path, device_root, dv_fixture):
    service, calls, _ = make_service(tmp_path, device_root, fetch=dv_fixture)
    _run(service.set_game(1091500, "Cyberpunk 2077"))

    def offline(appid, name):
        raise PluginError(OFFLINE, "no network")

    service._fetch_reports = offline
    view = _run(service.refresh())
    assert view["source"]["cached"] is True and view["source"]["error"]["kind"] == "offline"
    assert len(view["recommendations"]) == 7


def test_service_offline_without_cache_falls_back(tmp_path, device_root):
    service, _, _ = make_service(tmp_path, device_root)

    def offline(appid, name):
        raise PluginError(OFFLINE, "no network")

    service._fetch_reports = offline
    view = _run(service.set_game(620, "Portal 2"))
    assert [r["source"] for r in view["recommendations"]] == ["fallback"]
    assert view["source"]["error"]["kind"] == "offline"


def test_service_settings_validation_and_effects(tmp_path, device_root, dv_fixture):
    service, calls, _ = make_service(tmp_path, device_root, fetch=dv_fixture)
    _run(service.set_game(1091500, "Cyberpunk 2077"))
    view = _run(service.save_settings({"device_override": "valve-steam-deck-oled"}))
    assert view["device"]["id"] == "valve-steam-deck-oled" and view["device"]["how"] == "override"
    view = _run(service.save_settings({"stack_overrides": {"power": "steam-native"}}))
    assert view["stack"]["selected"]["power"] == "steam-native"
    view = _run(service.save_settings({"workload": "heavy"}))
    assert view["recommendations"][-1]["workload"] == "heavy"
    view = _run(service.save_settings({"source_deckverified": False}))
    assert [r["source"] for r in view["recommendations"]] == ["fallback"]
    for bad in ({"device_override": "nope"}, {"workload": "extreme"}, {"stack_overrides": {"power": "lsfg-vk"}},
                {"stack_overrides": {"teleport": "auto"}}):
        with pytest.raises(ValueError):
            _run(service.save_settings(bad))


def test_service_no_game_shows_fallback(tmp_path, device_root):
    service, _, _ = make_service(tmp_path, device_root, capture="synthetic-unknown-handheld")
    view = service.view()
    assert view["device"]["generic"] is True and view["game"] is None
    assert [r["source"] for r in view["recommendations"]] == ["fallback"]
    assert [c["kind"] for c in view["conflicts"]] == ["no_power"]


def test_view_without_a_game_sends_finished_cards(tmp_path, device_root):
    # The panel reads lines and compat_section on every card. Before 0.7.1 the
    # no-game card skipped validation and translation, and the panel crashed.
    service, _, _ = make_service(tmp_path, device_root)
    view = service.view()
    assert view["game"] is None
    recs = view["recommendations"]
    assert [r["source"] for r in recs] == ["fallback"]
    assert recs[0]["lines"]["power"], "general guidance must have its power line"
    assert "compat_section" in recs[0] and "flags" in recs[0]


def test_deck_verified_refusal_is_not_called_a_credentials_problem(monkeypatch):
    class Refused:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return type("R", (), {"status": 403})()

    monkeypatch.setattr(deckverified, "HttpClient", Refused)
    with pytest.raises(deckverified.PluginError) as info:
        deckverified.fetch(1091500, None)
    message = info.value.message
    assert "Deck Verified turned the request away (HTTP 403)" in message
    assert "credentials" not in message and "whitelist" not in message


def test_view_has_update_info_before_any_check(tmp_path, device_root):
    # The Updates section needs the version and install link from the start,
    # not only after the first GitHub check.
    service, _, _ = make_service(tmp_path, device_root)
    assert service.update_info is None
    update = service.view()["update"]
    assert update is not None and update["current"] == "0.1.0"
    assert set(update) >= {"install_url", "checked_at", "check_failed", "available"}
