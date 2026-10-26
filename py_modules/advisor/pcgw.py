"""PCGamingWiki, optional. Upscaler and frame generation support, and where a
game keeps its config and save files.

Since August 2026 the Cargo API needs a bot password (Special:BotPasswords,
with the grant "Create, query and delete data through the Cargo extension")
and the MediaWiki login flow. `Infobox_game` is now `Game`. 60 requests a
minute, and a 429 blocks the IP for 60 seconds, so each game costs two
queries and the answer is cached for 7 days. Content is CC BY-NC-SA: shown
with attribution and a link, never used commercially.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from plugin_core.errors import AUTH, BAD_RESPONSE, HTTP_ERROR, PluginError
from plugin_core.http import HttpClient, parse_base_url

BASE = "https://www.pcgamingwiki.com"
API = "w/api.php"
SOURCE = "pcgw"
ATTRIBUTION = "From PCGamingWiki, CC BY-NC-SA."

HINT_LOGIN = ("PCGamingWiki rejected the sign-in. Use the bot user name shown at Special:BotPasswords, "
              "such as YourName@advisor, and the bot password it gave you.")
HINT_GRANT = ("The bot password cannot run Cargo queries. In Special:BotPasswords, give it the grant "
              "\"Create, query and delete data through the Cargo extension\".")
HINT_429 = "PCGamingWiki is rate limiting this device. Wait a minute and try again."
HINT_403 = "PCGamingWiki blocked the request. Try again later."

SAFE_NAME = re.compile(r"^[^\"\\]{1,200}$")


def user_agent(version: str, monorepo: str) -> str:
    where = f"https://github.com/{monorepo}" if monorepo else "decky-plugins"
    return f"decky-tuning-advisor/{version} ({where}) python-urllib"


def split_list(value: Any) -> list[str]:
    """Cargo returns list fields as one comma-delimited string."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


class PcgwClient:
    def __init__(self, username: str, password: str, ua: str, base_url: str = BASE, timeout: float = 15.0):
        self.username = username
        self.password = password
        self.http = HttpClient(parse_base_url(base_url), timeout=timeout, use_cookies=True,
                               headers={"User-Agent": ua})
        self._logged_in = False
        self._lock = threading.Lock()

    def _check(self, res) -> dict[str, Any]:
        if res.status == 429:
            raise PluginError(HTTP_ERROR, "429", 429, hint=HINT_429)
        if res.status == 403:
            raise PluginError(AUTH, "403", 403, hint=HINT_403)
        if res.status >= 400:
            raise PluginError(HTTP_ERROR, str(res.status), res.status,
                              hint=f"PCGamingWiki returned HTTP {res.status}. Try again later.")
        data = res.json()
        if not isinstance(data, dict):
            raise PluginError(BAD_RESPONSE, "shape")
        return data

    def login(self) -> None:
        if not self.username or not self.password:
            raise PluginError(AUTH, "no credentials", hint="Enter your PCGamingWiki bot user name and bot password first.")
        self.http.clear_cookies()
        token = self._check(self.http.get(API, params={"action": "query", "meta": "tokens", "type": "login",
                                                        "format": "json"}))
        lgtoken = ((token.get("query") or {}).get("tokens") or {}).get("logintoken")
        if not lgtoken:
            raise PluginError(BAD_RESPONSE, "no token", hint="PCGamingWiki did not return a login token. Try again later.")
        result = self._check(self.http.post(API, form={"action": "login", "lgname": self.username,
                                                       "lgpassword": self.password, "lgtoken": lgtoken,
                                                       "format": "json"}))
        if (result.get("login") or {}).get("result") != "Success":
            raise PluginError(AUTH, "login failed", hint=HINT_LOGIN)
        self._logged_in = True

    def cargo(self, tables: str, fields: str, where: str, join_on: str = "", limit: int = 20) -> list[dict[str, Any]]:
        params = {"action": "cargoquery", "tables": tables, "fields": fields, "where": where, "limit": limit,
                  "format": "json"}
        if join_on:
            params["join_on"] = join_on
        with self._lock:
            if not self._logged_in:
                self.login()
            data = self._check(self.http.get(API, params=params))
            error = (data.get("error") or {}).get("code")
            if error == "permissiondenied" and self._logged_in:
                # The session may have expired. Sign in once more, then give up.
                self.login()
                data = self._check(self.http.get(API, params=params))
                error = (data.get("error") or {}).get("code")
        if error == "permissiondenied":
            raise PluginError(AUTH, "permissiondenied", hint=HINT_GRANT)
        if error:
            raise PluginError(BAD_RESPONSE, str(error)[:40], hint="PCGamingWiki could not run the query. Try again later.")
        return [row.get("title") or {} for row in data.get("cargoquery") or [] if isinstance(row, dict)]

    def game(self, appid: int | None, name: str | None) -> dict[str, Any] | None:
        """Blocking. Two queries: video features, then config and save paths."""
        if appid:
            where = f'Game.Steam_AppID HOLDS "{int(appid)}"'
        elif name and SAFE_NAME.match(name):
            where = f'Game._pageName="{name}"'
        else:
            return None
        video = self.cargo("Game,Video", "Game._pageName=Page,Video.Upscaling=Upscaling,Video.Frame_gen=FrameGen,"
                           "Video.HDR=HDR,Video.Ray_tracing=RayTracing,Video.Ultrawidescreen=Ultrawide",
                           where, join_on="Game._pageID=Video._pageID", limit=1)
        if not video:
            return None
        row = video[0]
        page = str(row.get("Page") or "")
        paths = self.cargo("Game,GameData", "GameData.Type=Type,GameData.Platform=Platform,GameData.Paths=Paths",
                           where, join_on="Game._pageID=GameData._pageID", limit=20)
        return {
            "page": page,
            "url": "https://www.pcgamingwiki.com/wiki/" + page.replace(" ", "_") if page else "",
            "upscaling": split_list(row.get("Upscaling")),
            "frame_gen": split_list(row.get("FrameGen")),
            "hdr": str(row.get("HDR") or "") or None,
            "ray_tracing": str(row.get("RayTracing") or "") or None,
            "ultrawide": str(row.get("Ultrawide") or "") or None,
            "files": [{"type": str(p.get("Type") or ""), "platform": str(p.get("Platform") or ""),
                       "paths": split_list(p.get("Paths"))[:6]}
                      for p in paths if p.get("Paths")][:10],
            "attribution": ATTRIBUTION,
        }


def upscaler_family(name: str) -> str:
    """"AMD FidelityFX Super Resolution 2" and "FSR 3.1" are both "fsr"."""
    text = name.casefold().replace("fidelityfx super resolution", "fsr").replace("super resolution", "")
    for vendor in ("amd", "intel", "nvidia"):
        text = text.replace(vendor, "")
    return re.sub(r"[^a-z]", "", text)[:4]


def upscaler_supported(name: str, listed: list[str]) -> bool:
    """True when the wiki lists the upscaler by family (FSR, DLSS, XeSS), or lists none."""
    return not listed or upscaler_family(name) in {upscaler_family(s) for s in listed}
