"""Exercise actual staged history imports across publisher changes and failures."""

import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from . import bootstrap, ha_stub
from .fixtures import FakeDrive, day_document
from custom_components.aaos_drive.coordinator import AAOSCoordinator
from custom_components.aaos_drive.history import HistoryStore
from custom_components.aaos_drive.repository import DriveRepository


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.history = HistoryStore(Path(temporary.name) / "history.sqlite")
        self.history.initialize()
        self.drive = FakeDrive()
        self.repo = DriveRepository(self.drive, "car", asyncio.to_thread)
        self.store = SimpleNamespace(async_save=AsyncMock())
        self.entry = SimpleNamespace(options={}, entry_id="entry", unique_id="vehicle-a:dataset-a")
        self.hass = SimpleNamespace(async_add_executor_job=asyncio.to_thread, state="starting")
        self.coordinator = AAOSCoordinator(self.hass, self.entry, self.repo, self.store, self.history)
        self.sleep = AsyncMock()
        patcher = patch("custom_components.aaos_drive.coordinator.asyncio.sleep", self.sleep)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_current_app_uniform_days_and_later_trip_import_after_upgrade(self):
        await self.coordinator._async_update_data()
        latest = day_document("2026-10-14", "dataset-a-3", start=1791968400000)
        latest["trips"][0]["telemetry"][0].update(powerSignalDirection="REVERSED", powerKw=4.5)
        latest["trips"][0]["powerSignalDirection"] = "REVERSED"
        self.drive.publish(2, uniform=True, latest_day=latest)
        snapshot = await self.coordinator._async_update_data()
        self.assertEqual(snapshot.manifest.raw["generationSequence"], 2)
        self.assertEqual(self.history.state()["generation_id"], "g2-fixture")
        self.assertEqual(self.history.trip()["tripId"], "dataset-a-3")
        self.assertEqual(self.history.trip("dataset-a-1")["tripId"], "dataset-a-1")
        self.assertEqual(snapshot.values()["telemetry.powerKw"], 4.5)  # Already normalized by the logger.
        self.assertEqual(snapshot.values()["telemetry.powerSignalDirection"], "REVERSED")
        self.assertEqual(snapshot.catalog["mergedDatasetIds"], ["previous-dataset"])
        self.assertEqual(self.history.points("telemetry.powerSignalDirection")["points"][-1]["value"], "REVERSED")
        self.assertEqual(self.history.overview()["trip_count"], 2)

    async def test_power_correction_updates_same_trip_and_times_without_new_trip_count(self):
        await self.coordinator._async_update_data()
        latest = day_document("2026-10-04", "dataset-a-2")
        latest["trips"][0].update(energyKwh=0.01, powerSignalDirection="REVERSED")
        latest["trips"][0]["telemetry"][0].update(powerKw=3.2, powerSignalDirection="REVERSED")
        self.drive.publish(2, latest_day=latest)
        snapshot = await self.coordinator._async_update_data()
        self.assertEqual(snapshot.values()["telemetry.powerKw"], 3.2)
        self.assertEqual(self.history.trip()["energyKwh"], 0.01)
        self.assertEqual(self.history.hourly()["telemetry.powerKw"][-1]["mean"], 3.2)
        self.assertEqual(self.history.overview()["trip_count"], 2)
        self.assertTrue(self.history.state()["statistics_pending"])

    async def test_new_commit_during_staging_retries_without_publishing_old_head(self):
        stage = self.history.stage
        published = False

        def publish_while_staging(artifact, trips):
            nonlocal published
            stage(artifact, trips)
            if not published:
                published = True
                self.assertIsNone(self.history.state()["generation_id"])
                self.assertIsNone(self.repo.accepted_head)
                self.drive.publish(2, uniform=True)

        with patch.object(self.history, "stage", publish_while_staging):
            snapshot = await self.coordinator._async_update_data()
        self.assertEqual(snapshot.manifest.raw["generationId"], "g2-fixture")
        self.assertEqual(self.history.state()["generation_id"], "g2-fixture")
        self.assertEqual(self.repo.accepted_head["sequence"], 2)
        self.store.async_save.assert_awaited_once()
        self.sleep.assert_awaited_once()

    async def test_missing_file_visibility_recovers_in_the_same_refresh(self):
        children = self.drive.children
        listings = 0

        async def delayed_artifact(parent):
            nonlocal listings
            files = await children(parent)
            if parent == "artifacts":
                listings += 1
                if listings == 1:
                    return [file for file in files if not file["name"].startswith("month-archive")]
            return files

        with patch.object(self.drive, "children", delayed_artifact):
            snapshot = await self.coordinator._async_update_data()
        self.assertEqual(snapshot.manifest.raw["generationSequence"], 1)
        self.assertEqual(listings, 2)
        self.sleep.assert_awaited_once()

    async def test_exhausted_missing_files_retain_history_head_and_snapshot(self):
        before = await self.coordinator._async_update_data()
        previous_head = dict(self.repo.accepted_head)
        self.store.async_save.reset_mock()
        self.drive.publish(2)
        self.drive.folder_lists["artifacts"] = []
        with self.assertRaises(ha_stub.UpdateFailed):
            await self.coordinator._async_update_data()
        self.assertEqual(self.history.state()["generation_id"], "g1-fixture")
        self.assertIs(self.repo.snapshot, before)
        self.assertEqual(self.repo.accepted_head, previous_head)
        self.store.async_save.assert_not_awaited()
        self.assertEqual(self.sleep.await_count, 2)

    async def test_restart_imports_latest_head_and_repeat_refresh_has_no_duplicates(self):
        await self.coordinator._async_update_data()
        self.drive.publish(3, uniform=True)
        restarted = DriveRepository(self.drive, "car", asyncio.to_thread)
        restarted.accepted_head = dict(self.repo.accepted_head)
        coordinator = AAOSCoordinator(self.hass, self.entry, restarted, self.store, self.history)
        await coordinator._async_update_data()
        await coordinator._async_update_data()
        self.assertEqual(self.history.state()["generation_id"], "g3-fixture")
        self.assertEqual(self.history.overview()["trip_count"], 2)
        self.assertEqual(len(self.history.points("telemetry.speedKph")["points"]), 2)

    async def test_invalid_historical_archive_never_advances_accepted_head(self):
        before = await self.coordinator._async_update_data()
        self.drive.publish(2, uniform=True)
        filename = next(name for name in self.drive.blobs if name.startswith("day-2026-09"))
        self.drive.blobs[filename] = b"corrupted detailed archive"
        with self.assertRaises(ha_stub.UpdateFailed):
            await self.coordinator._async_update_data()
        self.assertIs(self.repo.snapshot, before)
        self.assertEqual(self.repo.accepted_head["sequence"], 1)
        self.assertEqual(self.history.state()["generation_id"], "g1-fixture")
        self.sleep.assert_not_awaited()
