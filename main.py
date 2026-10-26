"""Decky entry point. A thin adapter over advisor.service.AdvisorService.

This plugin is read only. It never writes to Steam, other plugins, system
services or game files. tools/check_readonly.py enforces that in tools/gate.py.
"""

import os

import decky

from plugin_core.service import error_result
from advisor.service import AdvisorService


def _version() -> str:
    return os.environ.get("DECKY_PLUGIN_VERSION", "0.0.0")


class Plugin:
    service: AdvisorService

    async def _main(self):
        self.service = AdvisorService(
            settings_dir=decky.DECKY_PLUGIN_SETTINGS_DIR,
            runtime_dir=decky.DECKY_PLUGIN_RUNTIME_DIR,
            plugin_dir=decky.DECKY_PLUGIN_DIR,
            decky_home=decky.DECKY_HOME,
            user_home=decky.DECKY_USER_HOME,
            user=decky.DECKY_USER,
            version=_version(),
            emit=decky.emit,
            logger=decky.logger,
        )
        await self.service.start()
        decky.logger.info("tuning-advisor started")

    async def _unload(self):
        await self.service.stop()

    async def _uninstall(self):
        await self.service.uninstall()

    async def get_view(self):
        return self.service.view()

    async def set_game(self, appid, name, build_id=None, shortcut=False, launch_options="", compat_tool=""):
        try:
            view = await self.service.set_game(appid, name, build_id, shortcut, launch_options or "", compat_tool or "")
            return {"ok": True, "view": view}
        except Exception as exc:  # noqa: BLE001
            return error_result(exc)

    async def set_current_compat(self, launch_options="", compat_tool=""):
        """Current values read by the frontend. Shown and merged, never written back."""
        self.service.set_current_compat(launch_options or "", compat_tool or "")
        return {"ok": True, "view": self.service.view()}

    async def refresh(self):
        try:
            return {"ok": True, "view": await self.service.refresh()}
        except Exception as exc:  # noqa: BLE001
            return error_result(exc)

    async def redetect(self):
        return {"ok": True, "view": await self.service.redetect()}

    async def save_settings(self, values):
        try:
            return {"ok": True, "view": await self.service.save_settings(values)}
        except ValueError as err:
            return {"ok": False, "message": str(err)}

    async def set_secret(self, name, value):
        try:
            return {"ok": True, "view": self.service.set_secret(name, value)}
        except ValueError as err:
            return {"ok": False, "message": str(err)}

    async def clear_secret(self, name):
        try:
            return {"ok": True, "view": self.service.clear_secret(name)}
        except ValueError as err:
            return {"ok": False, "message": str(err)}

    async def set_pcgw_password(self, value):
        try:
            return {"ok": True, "view": await self.service.set_pcgw_password(value)}
        except ValueError as err:
            return {"ok": False, "message": str(err)}

    async def list_models(self, provider):
        return await self.service.list_models(provider)

    async def generate_ai(self):
        """Only ever called by the Generate button. Output is display only."""
        try:
            return {"ok": True, "view": await self.service.generate_ai()}
        except Exception as exc:  # noqa: BLE001
            return error_result(exc)

    async def import_from_file(self):
        return self.service.import_from_file()

    async def delete_import_file(self):
        return self.service.delete_import_file()

    async def clear_cache(self):
        return self.service.clear_cache()

    async def check_update(self, force=False):
        return await self.service.check_update(force)
