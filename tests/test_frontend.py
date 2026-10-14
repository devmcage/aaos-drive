"""Test the authenticated refresh/status bridge without a browser or live Drive."""

import asyncio
from datetime import datetime, timezone
import importlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from . import bootstrap, ha_stub


class FrontendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        def command(schema):
            def decorate(function):
                function.schema = schema
                return function
            return decorate

        def admin(function):
            function.requires_admin = True
            return function

        self.ws = SimpleNamespace(websocket_command=command, require_admin=admin,
                                  async_response=lambda fn: fn, async_register_command=Mock())
        self.panel = AsyncMock()
        loaded = SimpleNamespace(LOADED="loaded")
        additions = {
            "homeassistant.components.websocket_api": self.ws,
            "homeassistant.components.http": SimpleNamespace(StaticPathConfig=lambda *args: args),
            "homeassistant.components.panel_custom": SimpleNamespace(async_register_panel=self.panel),
        }
        modules = patch.dict(sys.modules, additions)
        modules.start()
        self.addCleanup(modules.stop)
        state = patch.object(sys.modules["homeassistant.config_entries"], "ConfigEntryState", loaded, create=True)
        state.start()
        self.addCleanup(state.stop)
        self.module = importlib.import_module("custom_components.aaos_drive.frontend")
        self.module = importlib.reload(self.module)
        self.now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        self.target = SimpleNamespace(lock=asyncio.Lock(), last_update_success=True,
            data=self.snapshot("g1"), last_checked_at=self.now, statistics_error=None,
            entry=SimpleNamespace(data={"folder_id":"car"}))
        self.entry = SimpleNamespace(domain="aaos_drive", state="loaded", runtime_data=self.target)
        self.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: self.entry))
        self.connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
        self.message = {"id": 1, "config_entry_id": "vehicle"}

    def snapshot(self, generation):
        return SimpleNamespace(manifest=SimpleNamespace(raw={"generationId": generation,
            "latestTripEndTimestamp": 1791968460000,"totalTripCount":2,"generationSequence":1}), checked_at=self.now)

    async def test_refresh_waits_for_import_before_returning_new_generation(self):
        async def update():
            async with self.target.lock:
                self.connection.send_result.assert_not_called()
                self.target.data = self.snapshot("g2")

        self.target.async_refresh = AsyncMock(side_effect=update)
        await asyncio.wait_for(self.module.refresh(self.hass, self.connection, self.message), 1)
        self.target.async_refresh.assert_awaited_once()
        result = self.connection.send_result.call_args.args[1]
        self.assertEqual(result["generation_id"], "g2")
        self.assertEqual(result["last_checked_at"], self.now.isoformat())
        self.assertTrue(self.module.refresh.requires_admin)

    async def test_failed_refresh_reports_error_and_keeps_old_local_history(self):
        async def fail():
            self.target.last_update_success = False

        self.target.async_refresh = AsyncMock(side_effect=fail)
        await self.module.refresh(self.hass, self.connection, self.message)
        self.connection.send_result.assert_not_called()
        self.assertEqual(self.connection.send_error.call_args.args[1], "drive_refresh_failed")
        await self.module.status(self.hass, self.connection, self.message)
        result = self.connection.send_result.call_args.args[1]
        self.assertEqual(result["generation_id"], "g1")
        self.assertFalse(result["drive_available"])
        self.assertTrue(self.module.status.requires_admin)

    async def test_status_waits_for_the_coordinator_lock(self):
        async with self.target.lock:
            task = asyncio.create_task(self.module.status(self.hass, self.connection, self.message))
            await asyncio.sleep(0)
            self.connection.send_result.assert_not_called()
        await task
        self.connection.send_result.assert_called_once()

    async def test_unloaded_vehicle_cannot_be_refreshed(self):
        self.entry.state = "not_loaded"
        self.target.async_refresh = AsyncMock()
        with self.assertRaises(ha_stub.HomeAssistantError):
            await self.module.refresh(self.hass, self.connection, self.message)
        self.target.async_refresh.assert_not_awaited()

    async def test_setup_registers_status_refresh_and_local_brand_assets(self):
        self.hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
        await self.module.async_setup_frontend(self.hass)
        commands = [call.args[1] for call in self.ws.async_register_command.call_args_list]
        self.assertIn(self.module.status, commands)
        self.assertIn(self.module.refresh, commands)
        paths = self.hass.http.async_register_static_paths.call_args.args[0]
        self.assertEqual({path[0] for path in paths}, {"/aaos_drive/history.js", "/aaos_drive/icon.png"})
