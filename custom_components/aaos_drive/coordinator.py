"""Refresh safely and keep the last validated snapshot on failure."""

import asyncio
from datetime import timedelta
import logging
import sqlite3

import aiohttp

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.core import CoreState
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DriveAuthError
from .const import DEFAULT_SCAN_MINUTES, NAME
from .model import InvalidExport
from .api import DriveError
from .history import sync_history


class AAOSCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, repository, store, history=None):
        super().__init__(hass, logging.getLogger(__name__), config_entry=entry, name=NAME,
                         update_interval=timedelta(minutes=entry.options.get("scan_minutes", DEFAULT_SCAN_MINUTES)))
        self.repository = repository
        self.entry = entry
        self.store = store
        self.lock = asyncio.Lock()
        self.history = history
        self.fields_with_data = None
        self.visibility_generation = None
        self.statistics_error = None
        self.saved_head = repository.accepted_head

    async def _async_update_data(self):
        try:
            async with self.lock:
                snapshot = await self.repository.refresh()
                if self.history is not None:
                    await sync_history(self.history, self.repository, snapshot, self.hass.async_add_executor_job)
                    if self.visibility_generation != snapshot.manifest.raw["generationId"]:
                        fields_with_data = await self.hass.async_add_executor_job(self.history.fields_with_data)
                    else:
                        fields_with_data = self.fields_with_data
                if self.saved_head != self.repository.accepted_head:
                    await self.store.async_save(self.repository.accepted_head)
                    self.saved_head = dict(self.repository.accepted_head)
                if self.history is not None:
                    self.fields_with_data = fields_with_data
                    self.visibility_generation = snapshot.manifest.raw["generationId"]
                if self.history is not None and self.hass.state is CoreState.running:
                    await self._async_statistics()
                return snapshot
        except DriveAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (DriveError, InvalidExport, aiohttp.ClientError, TimeoutError, ValueError, OSError, sqlite3.Error) as err:
            raise UpdateFailed(str(err)) from err

    async def _async_statistics(self):
        from .statistics import sync_statistics
        try:
            await sync_statistics(self.hass, self.entry, self.history)
            self.statistics_error = None
        except Exception as err:
            # Raw history is already complete. Retry a failed Recorder import next poll.
            self.statistics_error = "Historical statistics import failed; retry on next refresh"
            self.logger.warning("AAOS statistics import failed: %s", err)

    async def async_statistics_after_start(self, *_):
        async with self.lock:
            await self._async_statistics()
