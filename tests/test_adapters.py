import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from . import bootstrap, ha_stub
from .fixtures import FakeDrive
from custom_components.aaos_drive.binary_sensor import AAOSBinarySensor, StaleSensor
from custom_components.aaos_drive.button import RefreshButton
from custom_components.aaos_drive.config_flow import OAuth2FlowHandler
from custom_components.aaos_drive.const import READ_SCOPE
from custom_components.aaos_drive.coordinator import AAOSCoordinator
from custom_components.aaos_drive.device_tracker import LoggedPosition
from custom_components.aaos_drive.model import InvalidExport
from custom_components.aaos_drive.repository import DriveRepository
from custom_components.aaos_drive.sensor import AAOSSensor, async_setup_entry as setup_sensors, remove_legacy_entities


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.snapshot = await DriveRepository(FakeDrive(), "car", asyncio.to_thread).refresh()
        self.entry = SimpleNamespace(unique_id="vehicle-a:dataset-a", title="Test car", options={}, data={"dataset_id": "dataset-a", "vehicle_id": "vehicle-a"})
        self.coordinator = SimpleNamespace(entry=self.entry, data=self.snapshot, last_update_success=True)

    async def test_boolean_null_is_unknown_and_false_remains_false(self):
        missing = AAOSBinarySensor(self.coordinator, "telemetry.chargePortOpen", "Port open")
        false = AAOSBinarySensor(self.coordinator, "telemetry.chargePortConnected", "Connected")
        self.assertIsNone(missing.is_on)
        self.assertIs(false.is_on, False)

    async def test_units_timestamps_and_enum_encoding(self):
        power = AAOSSensor(self.coordinator, "telemetry.powerKw")
        self.assertEqual(power.native_value, -3.2)
        self.assertEqual(power._attr_native_unit_of_measurement, "kW")
        recorded = AAOSSensor(self.coordinator, "telemetry.recordedAt")
        self.assertEqual(recorded.native_value.tzinfo, timezone.utc)
        enum = AAOSSensor(self.coordinator, "telemetry.gearSelection")
        self.assertEqual(enum.native_value, 999)
        self.assertIn("raw AAOS", enum.extra_state_attributes["value_encoding"])
        duration = AAOSSensor(self.coordinator, "dataset.drivingTimeMs")
        self.assertEqual(duration.native_value, 120)
        self.assertEqual(duration.extra_state_attributes["raw_value"], 120000)
        efficiency = AAOSSensor(self.coordinator, "trip.efficiencyKwhPer100Km")
        self.assertEqual(efficiency._attr_native_unit_of_measurement, "kWh/100 km")

    async def test_static_lists_preserve_original_records(self):
        sensor = AAOSSensor(self.coordinator, "vehicle.specifications.evConnectorTypes")
        self.assertEqual(sensor.native_value, 1)
        self.assertEqual(sensor.extra_state_attributes["raw_value"], [{"code": 1, "name": "TYPE_2"}])

    async def test_device_sensor_discovery_excludes_periods_and_metadata(self):
        from unittest.mock import Mock, patch
        self.coordinator.async_add_listener = Mock(return_value=lambda: None)
        self.entry.async_on_unload = Mock()
        self.entry.runtime_data = self.coordinator
        added = []
        with patch("custom_components.aaos_drive.sensor.remove_legacy_entities"):
            await setup_sensors(SimpleNamespace(), self.entry, added.extend)
        keys = {entity.key for entity in added}
        self.assertIn("telemetry.speedKph", keys)
        self.assertIn("weather.temperatureC", keys)
        self.assertIn("route.latitude", keys)
        self.assertFalse(any(key.startswith(("month.", "trip.", "vehicle.", "dataset.")) for key in keys))
        self.assertNotIn("telemetry.recordedAt", keys)
        self.assertNotIn("telemetry.powerSource", keys)
        self.assertNotIn("telemetry.chargePortConnected", keys)
        speed=next(entity for entity in added if entity.key=="telemetry.speedKph")
        self.assertEqual(speed._attr_state_class,"measurement")
        gear=next(entity for entity in added if entity.key=="telemetry.gearSelection")
        self.assertIsNone(gear._attr_state_class)

    async def test_upgrade_removes_only_owned_obsolete_sensor_entities(self):
        import sys
        from unittest.mock import Mock, patch
        self.entry.entry_id = "entry1"
        prefix = self.entry.unique_id + ":"
        entries = [SimpleNamespace(platform=platform, domain=domain, unique_id=unique_id, entity_id=entity_id)
                   for platform, domain, unique_id, entity_id in [
                       ("aaos_drive", "sensor", prefix+"month.2026-10.distanceKm", "sensor.month"),
                       ("aaos_drive", "sensor", prefix+"vehicle.identity.make", "sensor.make"),
                       ("aaos_drive", "sensor", prefix+"trip.distanceKm", "sensor.trip"),
                       ("aaos_drive", "sensor", prefix+"dataset.totalTripCount", "sensor.dataset"),
                       ("aaos_drive", "sensor", prefix+"telemetry.recordedAt", "sensor.time"),
                       ("aaos_drive", "sensor", prefix+"telemetry.speedKph", "sensor.speed"),
                       ("other", "sensor", prefix+"month.distanceKm", "sensor.other"),
                       ("aaos_drive", "button", prefix+"dataset.refresh", "button.refresh"),
                       ("aaos_drive", "sensor", "different:month.distanceKm", "sensor.different"),
                   ]]
        registry = SimpleNamespace(async_remove=Mock())
        fake = SimpleNamespace(async_get=lambda _: registry, async_entries_for_config_entry=lambda r, entry_id: entries)
        with patch.dict(sys.modules, {"homeassistant.helpers.entity_registry": fake}):
            remove_legacy_entities(SimpleNamespace(), self.entry)
        removed = {call.args[0] for call in registry.async_remove.call_args_list}
        self.assertEqual(removed, {"sensor.month", "sensor.make", "sensor.trip", "sensor.dataset", "sensor.time"})

    async def test_read_failure_makes_entities_unavailable_but_refresh_retry_possible(self):
        self.coordinator.last_update_success = False
        self.assertFalse(AAOSSensor(self.coordinator, "telemetry.powerKw").available)
        button = RefreshButton(self.coordinator)
        self.coordinator.async_refresh = AsyncMock()
        self.assertTrue(button.available)
        with self.assertRaises(ha_stub.HomeAssistantError):
            await button.async_press()

    async def test_position_includes_recording_time(self):
        tracker = LoggedPosition(self.coordinator)
        self.assertEqual((tracker.latitude, tracker.longitude), (52.01, 5.01))
        self.assertTrue(tracker.available)
        self.assertEqual(tracker.extra_state_attributes["recorded_at_unix_ms"], self.snapshot.trip["endedAt"])

    async def test_stale_is_based_on_recorded_time_not_last_poll(self):
        self.snapshot.telemetry["recordedAt"] = int((datetime.now(timezone.utc) - timedelta(hours=48)).timestamp() * 1000)
        self.snapshot.checked_at = datetime.now(timezone.utc)
        self.assertTrue(StaleSensor(self.coordinator).is_on)
        self.entry.options = {"stale_hours": 72}
        self.assertFalse(StaleSensor(self.coordinator).is_on)

    async def test_oauth_flow_requests_readonly_and_rejects_broad_grants(self):
        flow = OAuth2FlowHandler()
        self.assertEqual(flow.extra_authorize_data["scope"], READ_SCOPE)
        result = await flow.async_oauth_create_entry({"token": {"scope": f"{READ_SCOPE} https://www.googleapis.com/auth/drive.file", "refresh_token": "test"}})
        self.assertEqual(result["reason"], "readonly_required")
        result = await flow.async_oauth_create_entry({"token": {"scope": READ_SCOPE}})
        self.assertEqual(result["reason"], "refresh_token_required")

    async def test_coordinator_does_not_replace_last_state_when_import_fails(self):
        repository = SimpleNamespace(accepted_head=None, refresh=AsyncMock(side_effect=InvalidExport("missing artifact")))
        store = SimpleNamespace(async_save=AsyncMock())
        coordinator = AAOSCoordinator(SimpleNamespace(), self.entry, repository, store)
        coordinator.data = self.snapshot
        with self.assertRaises(ha_stub.UpdateFailed):
            await coordinator._async_update_data()
        self.assertIs(coordinator.data, self.snapshot)
        store.async_save.assert_not_awaited()

    async def test_history_failure_retries_before_persisting_accepted_head(self):
        from unittest.mock import Mock, patch
        repository = DriveRepository(FakeDrive(), "car", asyncio.to_thread)
        store = SimpleNamespace(async_save=AsyncMock())
        history = SimpleNamespace(fields_with_data=Mock(return_value={"telemetry.speedKph"}))
        hass = SimpleNamespace(async_add_executor_job=asyncio.to_thread, state="starting")
        coordinator = AAOSCoordinator(hass, self.entry, repository, store, history)
        with patch("custom_components.aaos_drive.coordinator.sync_history", side_effect=InvalidExport("incomplete history")):
            with self.assertRaises(ha_stub.UpdateFailed):
                await coordinator._async_update_data()
        store.async_save.assert_not_awaited()
        self.assertIsNone(coordinator.saved_head)
        with patch("custom_components.aaos_drive.coordinator.sync_history", new=AsyncMock()):
            await coordinator._async_update_data()
        store.async_save.assert_awaited_once_with(repository.accepted_head)
        self.assertEqual(coordinator.saved_head,repository.accepted_head)
        # Recorder import must wait for CoreState.running, not merely a starting server.
        coordinator._async_statistics=AsyncMock()
        with patch("custom_components.aaos_drive.coordinator.sync_history", new=AsyncMock()):
            await coordinator._async_update_data()
        coordinator._async_statistics.assert_not_awaited()

    async def test_historical_visibility_is_cached_until_the_drive_generation_changes(self):
        from unittest.mock import Mock, patch
        repository = DriveRepository(FakeDrive(), "car", asyncio.to_thread)
        history = SimpleNamespace(fields_with_data=Mock(side_effect=[
            {"telemetry.speedKph"}, {"telemetry.speedKph", "telemetry.engineRpm"}]))
        hass = SimpleNamespace(async_add_executor_job=asyncio.to_thread, state="starting")
        coordinator = AAOSCoordinator(hass, self.entry, repository, SimpleNamespace(async_save=AsyncMock()), history)
        with patch("custom_components.aaos_drive.coordinator.sync_history", new=AsyncMock()):
            await coordinator._async_update_data()
            await coordinator._async_update_data()
            self.assertEqual(coordinator.fields_with_data, {"telemetry.speedKph"})
            history.fields_with_data.assert_called_once()
            repository.drive.publish(2)
            await coordinator._async_update_data()
        self.assertEqual(history.fields_with_data.call_count, 2)
        self.assertIn("telemetry.engineRpm", coordinator.fields_with_data)

    async def test_local_history_actions_work_during_drive_failure(self):
        import importlib.util
        import sys
        import types
        from unittest.mock import patch
        entries = sys.modules["homeassistant.config_entries"]
        oauth = sys.modules["homeassistant.helpers.config_entry_oauth2_flow"]
        loaded = "loaded"
        temporary_modules = {
            "homeassistant.const": types.SimpleNamespace(Platform=SimpleNamespace(SENSOR="sensor", BINARY_SENSOR="binary_sensor", BUTTON="button", DEVICE_TRACKER="device_tracker")),
            "homeassistant.helpers.storage": types.SimpleNamespace(Store=object),
            "homeassistant.helpers.start": types.SimpleNamespace(async_at_started=lambda *args: None),
            "custom_components.aaos_drive.frontend": types.SimpleNamespace(async_setup_frontend=AsyncMock()),
        }
        history = SimpleNamespace(trip=lambda _: {"tripId": "old-trip"}, summaries=lambda _: [{"tripId": "old-trip"}],
                                  state=lambda: {"generation_id": "last-complete"})
        coordinator = SimpleNamespace(history=history, lock=asyncio.Lock(), last_update_success=False, data=None)
        entry = SimpleNamespace(domain="aaos_drive", state=loaded, runtime_data=coordinator)
        handlers = {}
        hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: entry),
                               async_add_executor_job=asyncio.to_thread,
                               services=SimpleNamespace(async_register=lambda domain, action, handler, **kwargs: handlers.update({action: handler})))
        with patch.dict(sys.modules, temporary_modules), \
             patch.object(entries, "ConfigEntryState", SimpleNamespace(LOADED=loaded), create=True), \
             patch.object(oauth, "OAuth2Session", object, create=True), \
             patch.object(oauth, "async_get_config_entry_implementation", AsyncMock(), create=True):
            spec = importlib.util.spec_from_file_location("custom_components.aaos_drive._entrypoint_test", bootstrap.ROOT / "custom_components/aaos_drive/__init__.py")
            spec.submodule_search_locations = None
            integration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(integration)
            await integration.async_setup(hass, {})
            for action, key in (("get_trip", "trip"), ("list_trips", "trips")):
                response = await handlers[action](SimpleNamespace(service=action, data={"config_entry_id": "vehicle"}))
                self.assertEqual(response["generation_id"], "last-complete")
                self.assertIn(key, response)
            with self.assertRaises(ha_stub.HomeAssistantError):
                await handlers["get_catalog"](SimpleNamespace(service="get_catalog", data={"config_entry_id": "vehicle"}))
