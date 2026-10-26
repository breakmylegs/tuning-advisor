"""ProtonDB index and PCGamingWiki sources. No live calls."""

import asyncio
import copy
import gzip
import json
import logging
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from advisor import pcgw, protondb, recommend, registry as regmod
from advisor.service import AdvisorService
from plugin_core.errors import PluginError

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = regmod.load(os.path.join(PLUGIN, "registry"))
PASSWORD = "bot" + "p" * 30


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def index_bytes(apps, dump="oct1_2026", schema=1):
    lines = [json.dumps({"schema": schema, "dump": dump, "apps": len(apps)})]
    lines += [f"{app}\t{json.dumps(entry)}" for app, entry in sorted(apps.items())]
    return gzip.compress(("\n".join(lines) + "\n").encode("utf-8"))


ENTRY = {"n": 40, "works": 30, "handheld": 3, "title": "Example", "reports": [
    {"t": 1790000000, "device": "Handheld with Ryzen Z2 Extreme", "apu": "AMD Ryzen Z2 Extreme", "verdict": "yes",
     "variant": "ge", "proton": "GE-Proton10-34", "launch": "~/lsfg %command%", "notes": "Smooth at 40 fps"},
    {"t": 1789000000, "device": "Steam Deck LCD", "apu": "AMD Aerith (Van Gogh)", "verdict": "no",
     "variant": "official", "proton": "9.0-4", "launch": None, "notes": "Crashes in menu"},
    {"t": 1788000000, "device": "Steam Deck OLED", "apu": "AMD Sephiroth", "verdict": "yes",
     "variant": "experimental", "proton": None, "launch": None, "notes": None},
]}


# ProtonDB index


def test_index_download_lookup_refresh_and_fallback(tmp_path):
    now = {"t": 1_000_000.0}
    calls = []

    def fetch(url):
        calls.append(url)
        return index_bytes({"1091500": ENTRY, "620": ENTRY})

    idx = protondb.ProtonDbIndex(str(tmp_path), "https://example.invalid/i.gz", fetch=fetch, now=lambda: now["t"])
    assert idx.ensure()["dump"] == "oct1_2026" and len(calls) == 1
    assert idx.lookup(1091500)["n"] == 40 and idx.lookup(9) is None
    assert idx.lookup(62) is None, "a prefix of another app ID must not match"
    os.utime(idx.path, (now["t"], now["t"]))
    idx.ensure()
    assert len(calls) == 1, "fresh index must not download again"

    now["t"] += protondb.REFRESH_AFTER + 1

    def offline(url):
        raise PluginError("offline", "no network")

    idx._fetch = offline
    assert idx.ensure()["dump"] == "oct1_2026", "a failed refresh keeps the old index"


def test_lookup_matches_the_whole_app_id(tmp_path):
    # Lines out of order, so "6200" comes before "620". Only an exact ID plus tab finds 620.
    lines = [json.dumps({"schema": 1, "dump": "x"}), "6200\t" + json.dumps({"n": 1}), "620\t" + json.dumps({"n": 2})]
    idx = protondb.ProtonDbIndex(str(tmp_path), "u", fetch=lambda url: gzip.compress("\n".join(lines).encode()))
    idx.ensure()
    assert idx.lookup(620) == {"n": 2} and idx.lookup(6200) == {"n": 1} and idx.lookup(62) is None


def test_bad_download_is_rejected_and_old_index_kept(tmp_path):
    idx = protondb.ProtonDbIndex(str(tmp_path), "u", fetch=lambda url: index_bytes({"1": ENTRY}))
    idx.ensure()
    idx._fetch = lambda url: index_bytes({"1": ENTRY}, schema=99)
    idx._now = lambda: 10 ** 12
    assert idx.ensure()["schema"] == 1 and idx.lookup(1)
    fresh = protondb.ProtonDbIndex(str(tmp_path / "new"), "u", fetch=lambda url: b"not gzip")
    os.makedirs(tmp_path / "new")
    with pytest.raises(Exception):
        fresh.ensure()
    no_url = protondb.ProtonDbIndex(str(tmp_path / "new"), "", fetch=lambda url: b"")
    with pytest.raises(PluginError) as info:
        no_url.ensure()
    assert "does not know" in info.value.message


@pytest.mark.parametrize("variant,proton,tool,version", [
    ("ge", "GE-Proton10-34", "Glorious Eggroll Proton (GE)", "10-34"),
    ("official", "9.0-4", "Steam Proton", "9.0-4"),
    ("official", "Proton 10.0-4", "Steam Proton", "10.0-4"),
    ("official", None, "Steam Proton", "default"),
    ("experimental", None, "Steam Proton", "experimental"),
    ("native", None, "Native Linux", ""),
    ("notListed", None, None, None),
])
def test_compat_fields(variant, proton, tool, version):
    assert protondb.compat_fields(variant, proton) == (tool, version)


def test_normalise_and_device_match():
    recs = protondb.normalise(ENTRY, 1091500)
    assert [r["source"] for r in recs] == ["protondb"] * 3
    first = recs[0]
    assert first["source_url"] == "https://www.protondb.com/app/1091500"
    assert first["frame_gen"]["tool"] == "lsfg-vk" and first["power"]["tdp_w"] is None
    assert recs[1]["notes"].startswith("Reported not working") and recs[1]["works"] is False
    go2 = REG.device("lenovo-legion-go-2-z2e")
    assert recommend.device_match(REG, first["device_reported"], go2, first["apu_reported"]) == "same_apu"
    xax = REG.device("asus-rog-xbox-ally-x")
    assert recommend.chip(xax["apu"]) == recommend.chip("AMD Ryzen Z2 Extreme"), "AI in the name is the same chip"
    deck = REG.device("valve-steam-deck-oled")
    assert recommend.device_match(REG, recs[1]["device_reported"], deck, recs[1]["apu_reported"]) == "family"
    summary = protondb.summary(ENTRY, {"dump": "oct1_2026"})
    assert summary["share"] == 75 and "ODbL" in summary["attribution"]


# PCGamingWiki


class FakeWiki:
    def __init__(self):
        self.requests = []
        self.sessions = set()
        self.grant = True
        self.status = 200
        self.rows = {"Video": [{"title": {"Page": "Cyberpunk 2077", "Upscaling": "DLSS,FSR 3.1,XeSS",
                                          "FrameGen": "DLSS FG,FSR 3", "HDR": "true", "RayTracing": "true",
                                          "Ultrawide": "true"}}],
                     "GameData": [{"title": {"Type": "config", "Platform": "Windows",
                                             "Paths": "%LOCALAPPDATA%\\CD Projekt Red\\Cyberpunk 2077,{{p|game}}\\r6"}},
                                  {"title": {"Type": "saves", "Platform": "Windows", "Paths": "%USERPROFILE%\\Saved Games"}}]}
        state = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, status, payload, cookie=None):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode() if length else ""
                query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                form = dict(urllib.parse.parse_qsl(body))
                state.requests.append({"method": method, "query": query, "form": form,
                                       "headers": {k.lower(): v for k, v in self.headers.items()}})
                if state.status != 200:
                    return self._send(state.status, {"error": "x"})
                cookie = self.headers.get("Cookie", "")
                if query.get("action") == "query" and query.get("meta") == "tokens":
                    return self._send(200, {"query": {"tokens": {"logintoken": "tok+\\"}}}, "pcgw_session=pre; Path=/")
                if form.get("action") == "login":
                    if form.get("lgpassword") == PASSWORD and form.get("lgtoken") == "tok+\\":
                        sid = f"s{len(state.sessions)}"
                        state.sessions.add(sid)
                        return self._send(200, {"login": {"result": "Success"}}, f"pcgw_session={sid}; Path=/")
                    return self._send(200, {"login": {"result": "Failed", "reason": "Incorrect password"}})
                if query.get("action") == "cargoquery":
                    signed_in = any(f"pcgw_session={s}" in cookie for s in state.sessions)
                    if not signed_in or not state.grant:
                        return self._send(200, {"error": {"code": "permissiondenied", "info": "no"}})
                    table = query["tables"].split(",")[1]
                    return self._send(200, {"cargoquery": state.rows.get(table, [])})
                return self._send(404, {"error": "route"})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def client(self, username="Me@advisor", password=PASSWORD, ua="test-agent/1"):
        return pcgw.PcgwClient(username, password, ua, base_url=self.url)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def wiki():
    server = FakeWiki()
    yield server
    server.stop()


def test_pcgw_login_and_game(wiki):
    data = wiki.client().game(1091500, None)
    assert data["page"] == "Cyberpunk 2077" and data["url"].endswith("/wiki/Cyberpunk_2077")
    assert data["upscaling"] == ["DLSS", "FSR 3.1", "XeSS"] and data["frame_gen"] == ["DLSS FG", "FSR 3"]
    assert [f["type"] for f in data["files"]] == ["config", "saves"] and len(data["files"][0]["paths"]) == 2
    cargo = [r for r in wiki.requests if r["query"].get("action") == "cargoquery"]
    assert cargo[0]["query"]["where"] == 'Game.Steam_AppID HOLDS "1091500"'
    assert cargo[0]["query"]["tables"] == "Game,Video" and "Infobox_game" not in json.dumps(cargo)
    assert all(r["headers"]["user-agent"] == "test-agent/1" for r in wiki.requests)
    login = next(r for r in wiki.requests if r["form"].get("action") == "login")
    assert login["method"] == "POST" and login["form"]["lgname"] == "Me@advisor"


def test_pcgw_errors_are_plain(wiki):
    with pytest.raises(PluginError) as info:
        wiki.client(password="wrong").game(620, None)
    assert info.value.message == pcgw.HINT_LOGIN and PASSWORD not in info.value.message
    wiki.grant = False
    with pytest.raises(PluginError) as info:
        wiki.client().game(620, None)
    assert info.value.message == pcgw.HINT_GRANT
    logins = [r for r in wiki.requests if r["form"].get("action") == "login"]
    assert len(logins) == 3, "one login, one re-login on permissiondenied, then give up (plus the failed one)"
    wiki.status = 429
    with pytest.raises(PluginError) as info:
        wiki.client().game(620, None)
    assert info.value.message == pcgw.HINT_429
    with pytest.raises(PluginError):
        pcgw.PcgwClient("", "", "ua", base_url=wiki.url).game(620, None)


def test_pcgw_name_lookup_refuses_quotes(wiki):
    assert wiki.client().game(None, 'Bad" OR 1=1') is None
    assert wiki.client().game(None, "Portal 2")["page"] == "Cyberpunk 2077"


def test_upscaler_family():
    assert pcgw.upscaler_supported("FSR 3.1", ["AMD FidelityFX Super Resolution 2"])
    assert not pcgw.upscaler_supported("FSR 3.1", ["DLSS", "Intel XeSS"])
    assert pcgw.upscaler_supported("XeSS", ["Intel XeSS 1.3"]) and pcgw.upscaler_supported("FSR", [])


# Service


def make_service(tmp_path, device_root, dv_fixture, wiki=None, fetch=None):
    async def emit(*_):
        pass

    factory = (lambda u, p, ua: pcgw.PcgwClient(u, p, ua, base_url=wiki.url)) if wiki else pcgw.PcgwClient
    service = AdvisorService(
        settings_dir=str(tmp_path / "s"), runtime_dir=str(tmp_path / "r"), plugin_dir=PLUGIN,
        decky_home=str(tmp_path / "h"), user_home=str(tmp_path / "home"), user="deck", version="0.4.0", emit=emit,
        logger=logging.getLogger("test"), root=device_root("synthetic-legion-go-2-z2e"),
        fetch_reports=lambda appid, name: copy.deepcopy(dv_fixture),
        protondb_fetch=fetch or (lambda url: index_bytes({"1091500": ENTRY})), pcgw_factory=factory,
    )
    os.makedirs(tmp_path / "r", exist_ok=True)
    service.protondb.url = "https://example.invalid/i.gz"
    service.detect()
    return service


def test_service_protondb_off_by_default_then_merged(tmp_path, device_root, dv_fixture):
    service = make_service(tmp_path, device_root, dv_fixture)
    view = _run(service.set_game(1091500, "Cyberpunk 2077"))
    assert view["protondb"]["enabled"] is False and not os.path.exists(service.protondb.path)
    assert {r["source"] for r in view["recommendations"]} == {"deckverified", "fallback"}
    view = _run(service.save_settings({"source_protondb": True}))
    sources = [r["source"] for r in view["recommendations"]]
    assert sources.count("protondb") == 3 and sources[-1] == "fallback"
    assert view["protondb"]["summary"]["share"] == 75 and view["protondb"]["dump"] == "oct1_2026"
    pdb = next(r for r in view["recommendations"] if r["source"] == "protondb" and r["device_match"] == "same_apu")
    assert pdb["compat_section"]["proton"]["recommended"] == "GE-Proton10-34"
    view = _run(service.set_game(3_000_000_000, "A shortcut"))
    assert "protondb" not in {r["source"] for r in view["recommendations"]}, "shortcuts have no Steam app ID"


def test_service_protondb_download_failure_is_reported(tmp_path, device_root, dv_fixture):
    def offline(url):
        raise PluginError("offline", "no network")

    service = make_service(tmp_path, device_root, dv_fixture, fetch=offline)
    _run(service.save_settings({"source_protondb": True}))
    view = _run(service.set_game(1091500, "Cyberpunk 2077"))
    assert view["protondb"]["error"]["kind"] == "offline"
    assert "deckverified" in {r["source"] for r in view["recommendations"]}


def test_service_pcgw_flow_cache_and_upscaler_flag(tmp_path, device_root, dv_fixture, wiki):
    service = make_service(tmp_path, device_root, dv_fixture, wiki=wiki)
    _run(service.set_game(1091500, "Cyberpunk 2077"))
    view = _run(service.save_settings({"source_pcgw": True, "pcgw_username": "Me@advisor"}))
    assert "bot user name" in view["pcgw"]["error"]["message"] and view["pcgw"]["has_password"] is False
    view = _run(service.set_pcgw_password(PASSWORD))
    assert view["pcgw"]["error"] is None and view["pcgw"]["data"]["page"] == "Cyberpunk 2077"
    assert PASSWORD not in json.dumps(view)
    # Deck Verified's fixture has an XeSS and an FSR 4 report. The wiki lists XeSS, so no flag for it.
    flags = [f for r in view["recommendations"] for f in r["flags"] if "PCGamingWiki does not list" in f]
    assert flags == []
    service.pcgw_data["upscaling"] = ["DLSS"]
    view = service.view()
    assert any("PCGamingWiki does not list XeSS" in f for r in view["recommendations"] for f in r["flags"])
    count = len(wiki.requests)
    _run(service.set_game(1091500, "Cyberpunk 2077"))
    assert len(wiki.requests) == count, "second load comes from the 7-day cache"
    assert service.view()["pcgw"]["cached"] is True
