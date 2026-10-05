"""Empty fields are hidden using the full archive without disabling their entities."""

import asyncio
from enum import Enum
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from . import bootstrap, ha_stub
from .fixtures import FakeDrive
from custom_components.aaos_drive.binary_sensor import AAOSBinarySensor, StaleSensor
from custom_components.aaos_drive.history import HistoryStore, sync_history
from custom_components.aaos_drive.repository import DriveRepository
from custom_components.aaos_drive.sensor import AAOSSensor


class Hider(Enum):
    INTEGRATION = "integration"
    USER = "user"


class VisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.history = HistoryStore(Path(temporary.name) / "history.sqlite")
        self.history.initialize()
        self.repository = DriveRepository(FakeDrive(), "car", asyncio.to_thread)
        self.snapshot = await self.repository.refresh()
        await sync_history(self.history, self.repository, self.snapshot, asyncio.to_thread)
        self.entry = SimpleNamespace(entry_id="entry1", unique_id="vehicle-a:dataset-a", title="Test car", options={})
        self.coordinator = SimpleNamespace(entry=self.entry, data=self.snapshot, last_update_success=True,
                                           fields_with_data=self.history.fields_with_data())
        self.records = {}
        self.registry = SimpleNamespace(async_get=self.records.get)
        def update(entity_id, **changes):
            record = self.records[entity_id]
            for key, value in changes.items():
                setattr(record, key, value)
            return record
        def update_options(entity_id, domain, options):
            record = self.records[entity_id]
            record.options = {**record.options, domain: options}
            return record
        self.registry.async_update_entity = Mock(side_effect=update)
        self.registry.async_update_entity_options = Mock(side_effect=update_options)
        registry_module = SimpleNamespace(async_get=lambda _: self.registry, RegistryEntryHider=Hider)
        self.registry_patch = patch.dict(sys.modules, {"homeassistant.helpers.entity_registry": registry_module})
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)

    def registered(self, field="telemetry.acceleratorPercent", hidden_by=None, binary=False):
        entity = AAOSBinarySensor(self.coordinator, field, "Boolean field") if binary else AAOSSensor(self.coordinator, field)
        entity.hass = SimpleNamespace()
        entity.entity_id = "binary_sensor.test" if binary else "sensor.test"
        self.records[entity.entity_id] = SimpleNamespace(entity_id=entity.entity_id,
            platform="aaos_drive", domain="binary_sensor" if binary else "sensor", config_entry_id=self.entry.entry_id,
            unique_id=entity._attr_unique_id, hidden_by=hidden_by, disabled_by=None,
            options={"sensor": {"precision": 2}, "aaos_drive": {"other_option": "keep"}})
        return entity, self.records[entity.entity_id]

    async def test_full_history_keeps_zero_false_and_historical_values_visible(self):
        coverage = self.history.fields_with_data()
        self.assertIn("telemetry.speedKph", coverage)  # Exactly zero in the fixture.
        self.assertIn("telemetry.chargePortConnected", coverage)  # Exactly false.
        self.assertNotIn("telemetry.acceleratorPercent", coverage)
        self.assertNotIn("telemetry.recordedAt", coverage)
        self.assertNotIn("telemetry.powerSource", coverage)
        self.assertFalse(any(field.startswith(("trip.", "month.", "vehicle.", "dataset.")) for field in coverage))
        # Latest trip is missing power, but an older trip still supplies readings.
        self.snapshot.telemetry["powerKw"] = None
        with self.history.connect() as db:
            db.execute("UPDATE records SET data=json_set(data,'$.powerKw',NULL) WHERE kind='telemetry' AND trip_id=?",
                       (self.snapshot.trip["tripId"],))
        self.coordinator.fields_with_data = self.history.fields_with_data()
        power = AAOSSensor(self.coordinator, "telemetry.powerKw")
        self.assertIsNone(power.native_value)
        self.assertTrue(power.entity_registry_visible_default)
        self.assertTrue(AAOSSensor(self.coordinator, "telemetry.speedKph").entity_registry_visible_default)
        self.assertTrue(AAOSBinarySensor(self.coordinator, "telemetry.chargePortConnected", "Port").entity_registry_visible_default)
        self.assertFalse(AAOSSensor(self.coordinator, "telemetry.acceleratorPercent").entity_registry_visible_default)

    async def test_invalid_numeric_boolean_and_unknown_text_are_not_readings(self):
        with self.history.connect() as db:
            db.execute("UPDATE records SET data=json_set(data,'$.acceleratorPercent','10','$.absActive',0,'$.futureText','unknown') WHERE kind='telemetry'")
        coverage = self.history.fields_with_data()
        self.assertNotIn("telemetry.acceleratorPercent", coverage)
        self.assertNotIn("telemetry.absActive", coverage)
        self.assertNotIn("telemetry.futureText", coverage)
        self.assertIn("telemetry.gearSelection", coverage)  # Unknown enum code is real data.

    async def test_superseded_or_staged_archives_do_not_affect_visibility(self):
        with self.history.connect() as db:
            db.execute("UPDATE records SET data=json_set(data,'$.engineRpm',700) WHERE kind='telemetry' AND trip_id='dataset-a-1'")
        self.assertIn("telemetry.engineRpm", self.history.fields_with_data())
        self.repository.drive.publish(2, include_history=False)
        snapshot = await self.repository.refresh()
        await sync_history(self.history, self.repository, snapshot, asyncio.to_thread)
        self.assertNotIn("telemetry.engineRpm", self.history.fields_with_data())
        with self.history.connect() as db:
            db.execute("INSERT INTO records(sha,trip_id,kind,position,at,data) VALUES (?,?,?,?,?,?)",
                       ("uncommitted", "pending", "telemetry", 0, 1791090000000, json.dumps({"engineRpm": 900})))
        self.assertNotIn("telemetry.engineRpm", self.history.fields_with_data())

    async def test_initial_setup_hides_once_and_preserves_options_and_enabled_state(self):
        entity, record = self.registered()
        with patch.object(ha_stub.CoordinatorEntity, "async_added_to_hass", new=AsyncMock(), create=True):
            await entity.async_added_to_hass()
        self.assertEqual(record.hidden_by, Hider.INTEGRATION)
        self.assertIsNone(record.disabled_by)
        self.assertEqual(record.options["sensor"], {"precision": 2})
        self.assertEqual(record.options["aaos_drive"]["other_option"], "keep")
        self.assertTrue(record.options["aaos_drive"]["initial_visibility_applied"])
        entity._sync_visibility()
        self.registry.async_update_entity.assert_called_once()
        self.registry.async_update_entity_options.assert_called_once()

    async def test_automatic_hidden_sensor_appears_on_later_reading_and_stays_visible(self):
        entity, record = self.registered(binary=True, field="telemetry.chargePortOpen")
        entity._sync_visibility()
        self.coordinator.fields_with_data.add(entity.key)
        with patch.object(ha_stub.CoordinatorEntity, "_handle_coordinator_update", new=Mock(), create=True) as update:
            entity._handle_coordinator_update()
        update.assert_called_once()
        self.assertIsNone(record.hidden_by)
        self.coordinator.fields_with_data.remove(entity.key)
        entity._sync_visibility()
        self.assertIsNone(record.hidden_by)

    async def test_user_visibility_changes_survive_refresh_and_restart(self):
        entity, record = self.registered()
        entity._sync_visibility()
        record.hidden_by = None  # User shows the empty sensor.
        entity._sync_visibility()
        restarted = AAOSSensor(self.coordinator, entity.key)
        restarted.hass, restarted.entity_id = entity.hass, entity.entity_id
        restarted._sync_visibility()
        self.assertIsNone(record.hidden_by)
        record.hidden_by = Hider.USER
        self.coordinator.fields_with_data.add(entity.key)
        restarted._sync_visibility()
        self.assertEqual(record.hidden_by, Hider.USER)

    async def test_existing_user_hidden_fields_and_other_entries_are_untouched(self):
        entity, record = self.registered(hidden_by=Hider.USER)
        entity._sync_visibility()
        self.assertEqual(record.hidden_by, Hider.USER)
        self.registry.async_update_entity.assert_not_called()
        for attribute, foreign_value in (("platform", "other"), ("unique_id", "foreign:telemetry.acceleratorPercent"),
                                         ("config_entry_id", "other-entry"), ("domain", "button")):
            entity, record = self.registered()
            setattr(record, attribute, foreign_value)
            self.registry.async_update_entity_options.reset_mock()
            entity._sync_visibility()
            self.registry.async_update_entity_options.assert_not_called()
            self.assertIsNone(record.hidden_by)

    async def test_diagnostics_stay_visible_and_snapshot_fallback_retains_zero_and_false(self):
        self.coordinator.fields_with_data = None
        self.assertTrue(AAOSSensor(self.coordinator, "telemetry.speedKph").entity_registry_visible_default)
        self.assertTrue(AAOSBinarySensor(self.coordinator, "telemetry.chargePortConnected", "Port").entity_registry_visible_default)
        self.assertFalse(AAOSSensor(self.coordinator, "telemetry.acceleratorPercent").entity_registry_visible_default)
        stale = StaleSensor(self.coordinator)
        self.assertTrue(stale.entity_registry_visible_default)
        stale._sync_visibility()  # Diagnostic never enters the entity registry visibility policy.
        self.registry.async_update_entity.assert_not_called()
