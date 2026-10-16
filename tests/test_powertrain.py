"""Import the app's additive powertrain contract without mixing fuel and battery energy."""

import asyncio
import json
import re
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from . import bootstrap, ha_stub
from .fixtures import FakeDrive, fuel_day
from custom_components.aaos_drive.binary_sensor import AAOSBinarySensor
from custom_components.aaos_drive.const import FUEL_USAGE_FIELDS, FUEL_USAGE_MEASUREMENTS
from custom_components.aaos_drive.history import HistoryStore, sync_history
from custom_components.aaos_drive.measurements import car_sensor, dashboard_field, series_info
from custom_components.aaos_drive.repository import DriveRepository
from custom_components.aaos_drive.sensor import AAOSSensor


class PowertrainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.history = HistoryStore(Path(temporary.name) / "history.sqlite")
        self.history.initialize()
        self.drive = FakeDrive(uniform=True, include_history=False, latest_day=fuel_day())
        self.repo = DriveRepository(self.drive, "car", asyncio.to_thread)
        self.snapshot = await self.repo.refresh()
        await sync_history(self.history, self.repo, self.snapshot, asyncio.to_thread)
        self.coordinator = SimpleNamespace(data=self.snapshot, last_update_success=True,
            fields_with_data=self.history.fields_with_data(),
            entry=SimpleNamespace(unique_id="vehicle-a:dataset-a", entry_id="entry"))

    async def test_fuel_sensors_have_units_and_boolean_states_with_recorded_metadata(self):
        level = AAOSSensor(self.coordinator, "telemetry.fuelLevelLiters")
        self.assertEqual(level.native_value, 39.6)
        self.assertEqual(level._attr_native_unit_of_measurement, "L")
        self.assertEqual(level._attr_device_class, "volume_storage")
        economy = AAOSSensor(self.coordinator, "telemetry.fuelConsumptionLitersPer100Km")
        self.assertEqual(economy.native_value, 6)
        self.assertEqual(economy._attr_native_unit_of_measurement, "L/100 km")
        self.assertEqual(economy._attr_state_class, "measurement")
        attrs = economy.extra_state_attributes
        self.assertEqual(attrs["vehicle_type"], "HYBRID")
        self.assertEqual(attrs["vehicle_type_source"], "aaos_fuel_and_traction_battery")
        self.assertEqual(attrs["recorded_at_unix_ms"], self.snapshot.telemetry["recordedAt"])
        for field in ("fuelLevelLow", "fuelDoorOpen"):
            self.assertIs(AAOSBinarySensor(self.coordinator, "telemetry."+field, field).is_on, False)
            self.assertIn("telemetry."+field, self.coordinator.fields_with_data)
        self.assertFalse(car_sensor("telemetry.vehicleType"))
        self.assertFalse(car_sensor("telemetry.vehicleTypeSource"))

    def test_every_current_app_fuel_summary_field_is_supported(self):
        source = bootstrap.ROOT.parent / "AAOS logging/app/src/main/kotlin/com/example/triplogger/sync/PowertrainJsonContract.kt"
        if not source.exists():
            self.skipTest("Adjacent Android logger source is not available")
        published = set(re.findall(r'\.put\("(\w+)"', source.read_text()))
        self.assertEqual(published, set(FUEL_USAGE_FIELDS) - {"coveragePercent"})

    async def test_trip_fuel_coverage_and_engine_metrics_preserve_the_original_export(self):
        original = self.drive.day["trips"][0]
        self.assertEqual(self.history.trip(), original)
        self.assertNotIn("coveragePercent", original["fuelUsage"])
        summary = self.history.summaries()[0]
        self.assertAlmostEqual(summary["fuelUsage"]["coveragePercent"], 50)
        self.assertEqual(summary["fuelUsage"]["movingFuelLiters"], 0.004)
        self.assertEqual(summary["fuelUsage"]["engineRunningSeconds"], 2)
        self.assertEqual(summary["fuelUsage"]["engineObservedSeconds"], 4)
        self.assertEqual(summary["fuelUsage"]["engineOffMovingSeconds"], 2)
        self.assertIs(summary["fuelUsage"]["includesStationaryFuel"], False)
        self.assertEqual(summary["energyKwh"], -0.01)  # Battery charging stays signed and separate.
        for field in FUEL_USAGE_MEASUREMENTS:
            key = "trip.fuelUsage."+field
            self.assertTrue(dashboard_field(key))
            self.assertFalse(car_sensor(key))
            page = self.history.points(key)
            self.assertEqual(len(page["points"]), 1)
            self.assertEqual(page["points"][0]["time"], original["endedAt"])
        self.assertEqual(series_info("trip.fuelUsage.movingFuelLiters")["statistic_unit"], "L")
        self.assertEqual(series_info("trip.fuelUsage.engineRunningSeconds")["statistic_unit"], "s")
        choice = self.history.trip_index()["trips"][0]
        self.assertEqual(choice["vehicle_type"], "HYBRID")
        self.assertEqual(choice["fuel_usage"], summary["fuelUsage"])

    async def test_missing_fuel_and_unmeasured_battery_energy_are_not_zero(self):
        self.drive.publish(2, uniform=True, include_history=False,
                           latest_day=fuel_day("FUEL", missing=True, energy_source="unknown"))
        snapshot = await self.repo.refresh()
        await sync_history(self.history, self.repo, snapshot, asyncio.to_thread)
        self.coordinator.data = snapshot
        for field in ("fuelLevelLiters", "fuelCapacityLiters", "fuelConsumptionLitersPer100Km"):
            self.assertIsNone(AAOSSensor(self.coordinator, "telemetry."+field).native_value)
        for field in ("fuelLevelLow", "fuelDoorOpen"):
            self.assertIsNone(AAOSBinarySensor(self.coordinator, "telemetry."+field, field).is_on)
        self.assertEqual(self.history.trip()["energyKwh"], 0.0)  # Original preserved.
        summary = self.history.summaries()[0]
        self.assertIsNone(summary["energyKwh"])
        self.assertIsNone(summary["efficiencyKwhPer100Km"])
        self.assertIsNone(summary["fuelUsage"]["movingFuelLiters"])
        self.assertIsNone(summary["fuelUsage"]["engineRunningSeconds"])
        self.assertEqual(summary["fuelUsage"]["engineObservedSeconds"], 0)
        stats = self.history.hourly()
        self.assertNotIn("trip.energyKwh", stats)
        self.assertNotIn("trip.fuelUsage.movingFuelLiters", stats)
        self.assertNotIn("telemetry.fuelConsumptionLitersPer100Km", stats)

    async def test_hourly_fuel_measurements_do_not_average_warnings_or_fabricate_totals(self):
        stats = self.history.hourly()
        self.assertEqual(stats["telemetry.fuelConsumptionLitersPer100Km"][0]["mean"], 6)
        self.assertEqual(stats["trip.fuelUsage.movingFuelLiters"][0]["mean"], 0.004)
        self.assertAlmostEqual(stats["trip.fuelUsage.coveragePercent"][0]["mean"], 50)
        self.assertNotIn("telemetry.fuelLevelLow", stats)
        self.assertNotIn("telemetry.fuelDoorOpen", stats)
        self.assertNotIn("telemetry.vehicleType", stats)

    async def test_zero_fuel_is_recorded_and_a_tank_drop_does_not_create_missing_fuel(self):
        day = fuel_day()
        for point in day["trips"][0]["telemetry"]:
            point["fuelConsumptionLitersPer100Km"] = 0.0
        usage = day["trips"][0]["fuelUsage"]
        usage.update(movingFuelLiters=0.0, movingConsumptionLitersPer100Km=0.0)
        self.drive.publish(2, uniform=True, include_history=False, latest_day=day)
        snapshot = await self.repo.refresh()
        await sync_history(self.history, self.repo, snapshot, asyncio.to_thread)
        self.assertEqual(self.history.points("trip.fuelUsage.movingFuelLiters")["points"][0]["value"], 0)
        for point in day["trips"][0]["telemetry"]:
            point["fuelConsumptionLitersPer100Km"] = None
        usage.update(movingFuelLiters=None, movingConsumptionLitersPer100Km=None, coveredDistanceKm=0.0)
        self.drive.publish(3, uniform=True, include_history=False, latest_day=day)
        snapshot = await self.repo.refresh()
        await sync_history(self.history, self.repo, snapshot, asyncio.to_thread)
        self.assertLess(self.history.trip()["telemetry"][-1]["fuelLevelLiters"], self.history.trip()["telemetry"][0]["fuelLevelLiters"])
        self.assertIsNone(self.history.points("trip.fuelUsage.movingFuelLiters")["points"][0]["value"])

    async def test_upgrade_rebuilds_cached_summaries_without_downloading_or_duplicating_data(self):
        before = self.history.overview()
        with self.history.connect() as db:
            db.execute("DELETE FROM meta WHERE key='processing_version'")
            db.execute("UPDATE records SET data=? WHERE kind='trip'", (json.dumps({"energyKwh": 0}),))
            db.execute("DELETE FROM fields WHERE field LIKE 'trip.fuelUsage.%'")
        self.history.statistics_done({})
        self.drive.downloads.clear()
        self.history.initialize()
        await sync_history(self.history, self.repo, self.snapshot, asyncio.to_thread)
        self.assertEqual(self.drive.downloads, [])
        self.assertTrue(self.history.state()["statistics_pending"])
        self.assertEqual(self.history.overview()["trip_count"], before["trip_count"])
        self.assertEqual(self.history.overview()["record_count"], before["record_count"])
        self.assertEqual(self.history.points("trip.energyKwh")["points"][0]["value"], -0.01)
        self.assertAlmostEqual(self.history.points("trip.fuelUsage.coveragePercent")["points"][0]["value"], 50)
        self.assertEqual(self.history.trip(), self.drive.day["trips"][0])
        self.history.statistics_done({})
        self.history.initialize()
        self.assertFalse(self.history.state()["statistics_pending"])

