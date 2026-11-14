"""Framework-independent synchronization and local-history API."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from .api import DriveNotFoundError, ReadOnlyDrive, folder_id
from .history import HistoryStore, sync_history
from .model import ExportNotReady, Snapshot
from .repository import DriveRepository


class AAOSDriveClient:
    """Coordinate complete imports, without owning credentials or HTTP sessions.

    The low-level constructor accepts a repository and an initialized optional
    HistoryStore. Use from_google_drive for automatic history initialization.
    Persist accepted_head in the host application to retain rollback protection
    across restarts; restore it through the factory's accepted_head argument.
    """

    def __init__(self, repository: DriveRepository, history: HistoryStore | None = None,
                 *, executor=asyncio.to_thread):
        self.repository = repository
        self.history = history
        self.executor = executor
        self._lock = asyncio.Lock()
        self._initialize_history = False

    @classmethod
    def from_google_drive(cls, session: aiohttp.ClientSession, token_provider, vehicle_folder: str,
                          *, history_path: str | Path | None = None,
                          expected_identity: dict | None = None, accepted_head: dict | None = None,
                          executor=asyncio.to_thread) -> AAOSDriveClient:
        """Use a caller-owned aiohttp session and async access-token provider.

        Google OAuth consent and token refresh remain the caller's responsibility.
        No credential is written to the local history database.
        """
        repository = DriveRepository(ReadOnlyDrive(session, token_provider), folder_id(vehicle_folder),
                                     executor, expected_identity)
        repository.accepted_head = dict(accepted_head) if accepted_head else None
        history = HistoryStore(history_path) if history_path is not None else None
        client = cls(repository, history, executor=executor)
        client._initialize_history = history is not None
        return client

    @property
    def snapshot(self) -> Snapshot | None:
        return self.repository.snapshot

    @property
    def accepted_head(self) -> dict | None:
        head = self.repository.accepted_head
        return deepcopy(head) if head else None

    async def refresh(self) -> Snapshot:
        """Read the latest complete generation and retain old data on failure.

        Publication races are retried three times. A generation is accepted only
        after every required archive is validated and local history is complete.
        """
        async with self._lock:
            if self._initialize_history:
                await self.executor(self.history.initialize)
                self._initialize_history = False
            for attempt in range(3):
                try:
                    snapshot = await self.repository.refresh(accept=False)
                    if self.history is not None:
                        await sync_history(self.history, self.repository, snapshot, self.executor)
                    break
                except (ExportNotReady, DriveNotFoundError):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2 ** attempt)
            self.repository.accept_snapshot(snapshot)
            snapshot.checked_at = datetime.now(timezone.utc)
            if snapshot.previous_identity is not None:
                self.repository.expected_identity = {
                    key: snapshot.manifest.raw[key] for key in ("datasetId", "vehicleId")
                }
            return snapshot

    async def _query(self, method: str, *args) -> Any:
        async with self._lock:
            if self.history is None:
                raise ValueError("Configure history_path to query complete recorded history")
            if self._initialize_history:
                await self.executor(self.history.initialize)
                self._initialize_history = False
            if not (await self.executor(self.history.state))["generation_id"]:
                raise ValueError("Import a complete generation before querying history")
            return await self.executor(getattr(self.history, method), *args)

    async def history_fields(self) -> dict:
        return await self._query("overview")

    async def list_trips(self, period: str = "") -> list[dict]:
        return await self._query("summaries", period)

    async def get_trip(self, trip_id: str = "") -> dict:
        """Return the exact original trip, including its raw sample arrays."""
        return await self._query("trip", trip_id)

    async def get_history(self, field: str, *, start: int | None = None, end: int | None = None,
                          limit: int = 2000, cursor: dict | None = None,
                          trip_id: str | None = None) -> dict:
        """Return timestamped readings and a generation-bound next_cursor."""
        return await self._query("points", field, start, end, limit, cursor, trip_id)
