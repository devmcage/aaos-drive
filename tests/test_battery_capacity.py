"""Capacity is paired recorded evidence, not an inferred/certified health measurement."""

import asyncio
import copy
import tempfile
import json
from zipfile import ZipFile
from pathlib import Path
from types import SimpleNamespace
import unittest

from . import bootstrap, ha_stub
from .fixtures import FakeDrive, day_document
from custom_components.aaos_drive.battery_capacity import capacity_telemetry, NOTICE
from custom_components.aaos_drive.history import HistoryStore, sync_history
from custom_components.aaos_drive.measurements import series_info
from custom_components.aaos_drive.repository import DriveRepository
from custom_components.aaos_drive.sensor import AAOSSensor


class CapacityMathTests(unittest.TestCase):
    def test_missing_invalid_and_over_100_remain_honest(self):
        for bad in (None, False, True, 0, -1, float("nan"), float("inf"), 10**1000):
            for current, nominal in ((bad, 75000), (72000, bad)):
                sample = {"batteryCurrentCapacityWh": current, "batteryNominalCapacityWh": nominal,
                          "batteryCapacityRetentionPercent": 100, "batteryPercent": 40, "batteryEnergyWh": 30000}
                self.assertIsNone(capacity_telemetry(sample)["batteryCapacityRetentionPercent"])
        self.assertEqual(capacity_telemetry({"batteryCurrentCapacityWh": 78000, "batteryNominalCapacityWh": 75000})["batteryCapacityRetentionPercent"], 104)
        self.assertIsNone(capacity_telemetry({"batteryCurrentCapacityWh": 1e300, "batteryNominalCapacityWh": 1e-300})["batteryCapacityRetentionPercent"])


class CapacityIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = HistoryStore(Path(temporary.name) / "history.sqlite")
        self.store.initialize()

    async def load(self, document):
        self.drive = FakeDrive(uniform=True, include_history=False, latest_day=document)
        self.repo = DriveRepository(self.drive, "car", asyncio.to_thread)
        snapshot = await self.repo.refresh()
        await sync_history(self.store, self.repo, snapshot, asyncio.to_thread)
        coordinator = SimpleNamespace(data=snapshot, last_update_success=True, fields_with_data=self.store.fields_with_data(),
                                     entry=SimpleNamespace(unique_id="vehicle-a:dataset-a", entry_id="entry"))
        return snapshot, coordinator

    async def test_raw_capacities_sensors_and_history_keep_exact_recorded_times_and_original_trip(self):
        document = day_document("2026-10-04", "dataset-a-2")
        sample = document["trips"][0]["telemetry"][0]
        sample.update(batteryCurrentCapacityWh=72000, batteryNominalCapacityWh=75000,
                      batteryCapacityRetentionPercent=12, batteryTemperatureC=20)
        original = copy.deepcopy(document["trips"][0])
        snapshot, coordinator = await self.load(document)
        current = AAOSSensor(coordinator, "telemetry.batteryCurrentCapacityWh")
        retention = AAOSSensor(coordinator, "telemetry.batteryCapacityRetentionPercent")
        self.assertEqual(current.native_value, 72000)
        self.assertEqual(current._attr_native_unit_of_measurement, "Wh")
        self.assertEqual(retention.native_value, 96)
        self.assertEqual(retention._attr_native_unit_of_measurement, "%")
        self.assertIsNone(retention._attr_device_class)  # Not the battery charge percentage.
        self.assertEqual(retention._attr_state_class, "measurement")
        self.assertFalse(retention.extra_state_attributes["is_verified_state_of_health"])
        self.assertEqual(retention.extra_state_attributes["capacity_description"], NOTICE)
        self.assertEqual(retention.extra_state_attributes["recorded_at_unix_ms"], sample["recordedAt"])
        page = self.store.points("telemetry.batteryCapacityRetentionPercent")["points"]
        self.assertEqual(page[0]["value"], 96)
        self.assertEqual(page[0]["time"], sample["recordedAt"])
        self.assertEqual(self.store.trip(), original)
        self.assertEqual(snapshot.trip, original)
        self.assertEqual(series_info("telemetry.batteryCapacityRetentionPercent")["name"], "Estimated battery capacity retention")
        self.assertEqual(series_info("telemetry.batteryNominalCapacityWh")["statistic_unit"], "Wh")

    async def test_missing_current_capacity_does_not_reuse_an_older_pair(self):
        document = day_document("2026-10-04", "dataset-a-2")
        last = document["trips"][0]["telemetry"][0]
        first = dict(last, recordedAt=last["recordedAt"] - 2000, batteryCurrentCapacityWh=72000, batteryNominalCapacityWh=75000)
        last.update(batteryCurrentCapacityWh=None, batteryNominalCapacityWh=75000, batteryCapacityRetentionPercent=99)
        document["trips"][0]["telemetry"] = [first, last]
        snapshot, coordinator = await self.load(document)
        self.assertIsNone(AAOSSensor(coordinator, "telemetry.batteryCapacityRetentionPercent").native_value)
        self.assertEqual([p["value"] for p in self.store.points("telemetry.batteryCapacityRetentionPercent")["points"]], [96, None])
        self.assertIsNone(snapshot.telemetry["batteryCurrentCapacityWh"])

    async def test_cached_history_is_reprocessed_locally_without_rewriting_original_exports(self):
        document = day_document("2026-10-04", "dataset-a-2")
        document["trips"][0]["telemetry"][0].update(batteryCurrentCapacityWh=72000, batteryNominalCapacityWh=75000)
        await self.load(document)
        original = self.store.trip()
        with self.store.connect() as db:
            db.execute("UPDATE records SET data=json_remove(data, '$.batteryCapacityRetentionPercent') WHERE kind='telemetry'")
            self.store.put(db, "processing_version", 3)
        self.store.initialize()
        self.assertEqual(self.store.points("telemetry.batteryCapacityRetentionPercent")["points"][0]["value"], 96)
        self.assertEqual(self.store.trip(), original)

    async def test_actual_car_generated_export_is_understood_without_capacity_guessing(self):
        fixture = bootstrap.ROOT.parent / "AAOS logging/build/qa/battery-capacity-export.zip"
        if not fixture.exists():
            self.skipTest("Run the adjacent car's capacity export device test first")
        with ZipFile(fixture) as archive:
            day_path = next(path for path in archive.namelist() if "/days/" in path and path.endswith(".json"))
            document = json.loads(archive.read(day_path))
        snapshot, coordinator = await self.load(document)
        self.assertEqual(AAOSSensor(coordinator, "telemetry.batteryCurrentCapacityWh").native_value, 72000)
        self.assertEqual(AAOSSensor(coordinator, "telemetry.batteryNominalCapacityWh").native_value, 75000)
        self.assertEqual(AAOSSensor(coordinator, "telemetry.batteryCapacityRetentionPercent").native_value, 96)
        self.assertEqual(self.store.trip()["telemetry"], document["trips"][0]["telemetry"])
