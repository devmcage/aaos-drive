import asyncio
from datetime import timezone
from enum import IntEnum
import importlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from . import bootstrap, ha_stub
from .fixtures import FakeDrive, day_document, fuel_day
from custom_components.aaos_drive.history import HistoryStore, sync_history, statistic_id
from custom_components.aaos_drive.repository import DriveRepository


class StatisticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.history=HistoryStore(Path(self.temp.name)/"history.sqlite")
        self.history.initialize()
        self.repo=DriveRepository(FakeDrive(),"car",asyncio.to_thread)
        snapshot=await self.repo.refresh()
        await sync_history(self.history,self.repo,snapshot,asyncio.to_thread)
        self.recorder=SimpleNamespace(async_clear_statistics=Mock(),async_block_till_done=AsyncMock())
        self.add=Mock()
        self.native_add=Mock()
        self.unit_update=Mock()
        ha_stub.module("homeassistant.components.recorder",get_instance=lambda hass:self.recorder)
        ha_stub.module("homeassistant.components.recorder.models",StatisticMeanType=IntEnum("MeanType",{"ARITHMETIC":1}))
        ha_stub.module("homeassistant.components.recorder.statistics",async_add_external_statistics=self.add,async_import_statistics=self.native_add,async_update_statistics_metadata=self.unit_update)
        self.entry=SimpleNamespace(entry_id="entry1",title="Test car",unique_id="vehicle-a:dataset-a")
        self.registry_entries=[SimpleNamespace(platform="aaos_drive",domain="sensor",entity_id=entity_id,
                                              unique_id=self.entry.unique_id+":"+field)
                               for field,entity_id in (("telemetry.speedKph","sensor.car_speed"),("telemetry.powerKw","sensor.car_power"))]
        registry=SimpleNamespace()
        self.er=ha_stub.module("homeassistant.helpers.entity_registry",async_get=lambda _:registry,
                              async_entries_for_config_entry=lambda _, entry_id:self.registry_entries)
        self.module=importlib.import_module("custom_components.aaos_drive.statistics")
        # Replace imported bindings so every test gets its own recorder and queue.
        self.module.get_instance=lambda hass:self.recorder
        self.module.async_add_external_statistics=self.add
        self.module.async_import_statistics=self.native_add
        self.module.async_update_statistics_metadata=self.unit_update
        self.module.er=self.er
        self.module.native_hour_cutoff=lambda: 2**63-1
        self.hass=SimpleNamespace(async_add_executor_job=asyncio.to_thread)

    async def test_historical_hourly_import_has_current_metadata_and_recorded_times(self):
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        power=[call for call in self.add.call_args_list if call.args[1]["statistic_id"]==statistic_id("entry1","telemetry.powerKw")]
        self.assertEqual(len(power),1)
        metadata,rows=power[0].args[1:]
        self.assertEqual(metadata["source"],"aaos_drive")
        self.assertEqual(metadata["unit_of_measurement"],"kW")
        self.assertIn("unit_class",metadata)
        self.assertIn("mean_type",metadata)
        self.assertNotIn("has_mean",metadata)
        self.assertFalse(metadata["has_sum"])
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]["start"].tzinfo,timezone.utc)
        self.assertEqual(rows[0]["start"].month,9)
        self.assertEqual(rows[1]["start"].month,10)
        self.assertEqual(rows[0]["mean"],-3.2)
        self.recorder.async_block_till_done.assert_awaited_once()
        self.assertFalse(self.history.state()["statistics_pending"])

    async def test_fuel_units_and_observed_trip_metrics_reach_recorder_separately_from_battery(self):
        self.repo.drive.publish(2, uniform=True, include_history=False, latest_day=fuel_day())
        snapshot = await self.repo.refresh()
        await sync_history(self.history, self.repo, snapshot, asyncio.to_thread)
        self.registry_entries.extend(SimpleNamespace(platform="aaos_drive",domain="sensor",entity_id=entity,
            unique_id=self.entry.unique_id+":"+field) for field,entity in (
                ("telemetry.fuelLevelLiters","sensor.fuel_remaining"),
                ("telemetry.fuelConsumptionLitersPer100Km","sensor.fuel_economy")))
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        native={call.args[1]["statistic_id"]:call for call in self.native_add.call_args_list}
        self.assertEqual(native["sensor.fuel_remaining"].args[1]["unit_of_measurement"],"L")
        self.assertEqual(native["sensor.fuel_economy"].args[1]["unit_of_measurement"],"L/100 km")
        self.assertEqual(native["sensor.fuel_economy"].args[2][0]["mean"],6)
        external={call.args[1]["statistic_id"]:call for call in self.add.call_args_list}
        moving=external[statistic_id("entry1","trip.fuelUsage.movingFuelLiters")]
        self.assertEqual(moving.args[1]["unit_of_measurement"],"L")
        self.assertFalse(moving.args[1]["has_sum"])
        self.assertEqual(moving.args[2][0]["mean"],0.004)
        self.assertEqual(external[statistic_id("entry1","trip.energyKwh")].args[2][0]["mean"],-0.01)

    async def test_repeat_and_new_generation_unchanged_measurements_do_not_requeue(self):
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.add.reset_mock()
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.add.assert_not_called()
        self.repo.drive.publish(2)
        snapshot=await self.repo.refresh()
        await sync_history(self.history,self.repo,snapshot,asyncio.to_thread)
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.add.assert_not_called()

    async def test_upgrade_corrects_legacy_fuel_units_without_deleting_history(self):
        self.repo.drive.publish(2, uniform=True, include_history=False, latest_day=fuel_day())
        snapshot = await self.repo.refresh()
        await sync_history(self.history,self.repo,snapshot,asyncio.to_thread)
        self.registry_entries.append(SimpleNamespace(platform="aaos_drive",domain="sensor",entity_id="sensor.my_fuel",
            unique_id=self.entry.unique_id+":telemetry.fuelConsumptionLitersPer100Km"))
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        old=self.history.statistics_state()
        for record in old.values():
            record.pop("unit",None)
        self.history.statistics_done(old)
        with self.history.connect() as db:
            self.history.put(db,"statistics_pending",True)
        self.recorder.async_clear_statistics.reset_mock()
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        fixed={call.args[1] for call in self.unit_update.call_args_list}
        self.assertEqual(fixed,{"sensor.my_fuel",statistic_id("entry1","telemetry.fuelConsumptionLitersPer100Km"),
                                statistic_id("entry1","trip.fuelUsage.movingConsumptionLitersPer100Km")})
        self.assertTrue(all(call.kwargs=={"new_unit_of_measurement":"L/100 km","new_unit_class":None} for call in self.unit_update.call_args_list))
        self.recorder.async_clear_statistics.assert_not_called()
        self.unit_update.reset_mock()
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.unit_update.assert_not_called()

    async def test_current_app_power_correction_replaces_native_and_external_hours(self):
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.add.reset_mock()
        self.native_add.reset_mock()
        latest=day_document("2026-10-04","dataset-a-2")
        latest["trips"][0]["telemetry"][0].update(powerKw=3.2,powerSignalDirection="REVERSED")
        latest["trips"][0].update(energyKwh=0.01,powerSignalDirection="REVERSED")
        self.repo.drive.publish(2,uniform=True,latest_day=latest)
        snapshot=await self.repo.refresh()
        await sync_history(self.history,self.repo,snapshot,asyncio.to_thread)
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        native=[call for call in self.native_add.call_args_list if call.args[1]["statistic_id"]=="sensor.car_power"]
        external=[call for call in self.add.call_args_list if call.args[1]["statistic_id"]==statistic_id("entry1","telemetry.powerKw")]
        self.assertEqual(len(native),1)
        self.assertEqual(len(external),1)
        self.assertEqual(native[0].args[2][-1]["mean"],3.2)
        self.assertEqual(external[0].args[2][-1]["mean"],3.2)
        self.assertFalse(self.history.state()["statistics_pending"])

    async def test_removed_hours_clear_only_affected_owned_statistics(self):
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.repo.drive.publish(2,include_history=False)
        snapshot=await self.repo.refresh()
        await sync_history(self.history,self.repo,snapshot,asyncio.to_thread)
        self.add.reset_mock()
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.assertTrue(self.recorder.async_clear_statistics.called)
        for call in self.recorder.async_clear_statistics.call_args_list:
            self.assertTrue(all(identifier.startswith("aaos_drive:entry1_") or identifier in {"sensor.car_speed","sensor.car_power"} for identifier in call.args[0]))
        self.assertTrue(all(len(call.args[2])==1 for call in self.add.call_args_list))

    async def test_failed_queue_retains_pending_marker_for_retry(self):
        self.recorder.async_block_till_done.side_effect=RuntimeError("recorder failed")
        with self.assertRaises(RuntimeError):
            await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.assertTrue(self.history.state()["statistics_pending"])
        self.assertEqual(self.history.statistics_state(),{})

    async def test_native_history_uses_the_owned_sensor_entity_id(self):
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        calls=[call for call in self.native_add.call_args_list if call.args[1]["statistic_id"]=="sensor.car_speed"]
        self.assertEqual(len(calls),1)
        metadata,rows=calls[0].args[1:]
        self.assertEqual(metadata["source"],"recorder")
        self.assertEqual(metadata["unit_of_measurement"],"km/h")
        self.assertIsNone(metadata["name"])
        self.assertEqual([row["start"].month for row in rows],[9,10])
        self.assertTrue(all(row["start"].minute==0 and row["start"].tzinfo==timezone.utc for row in rows))
        self.assertEqual(self.history.statistics_state()["telemetry.speedKph"]["native_statistic_id"],"sensor.car_speed")

    async def test_upgrade_backfills_native_ids_without_a_changed_drive_generation(self):
        from unittest.mock import patch
        with patch.object(self.module,"native_statistic_ids",return_value={}):
            await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.assertFalse(self.history.state()["statistics_pending"])
        self.add.reset_mock()
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.assertTrue(self.native_add.called)
        self.add.assert_not_called()
        self.native_add.reset_mock()
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.native_add.assert_not_called()

    async def test_renamed_sensor_gets_native_history_without_guessing_its_name(self):
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.registry_entries[0].entity_id="sensor.user_chosen_speed_name"
        self.native_add.reset_mock()
        self.add.reset_mock()
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.assertEqual({call.args[1]["statistic_id"] for call in self.native_add.call_args_list},{"sensor.user_chosen_speed_name"})
        self.add.assert_not_called()

    async def test_removing_source_hours_clears_only_its_owned_native_entities(self):
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.repo.drive.publish(2,include_history=False)
        snapshot=await self.repo.refresh()
        await sync_history(self.history,self.repo,snapshot,asyncio.to_thread)
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        native={identifier for call in self.recorder.async_clear_statistics.call_args_list for identifier in call.args[0] if identifier.startswith("sensor.")}
        self.assertEqual(native,{"sensor.car_speed","sensor.car_power"})

    async def test_native_import_ignores_foreign_or_metadata_sensor_entries(self):
        self.registry_entries.extend([
            SimpleNamespace(platform="other",domain="sensor",entity_id="sensor.foreign",unique_id=self.entry.unique_id+":telemetry.speedKph"),
            SimpleNamespace(platform="aaos_drive",domain="sensor",entity_id="sensor.foreign_identity",unique_id="other:telemetry.speedKph"),
            SimpleNamespace(platform="aaos_drive",domain="sensor",entity_id="sensor.month",unique_id=self.entry.unique_id+":month.2026-10.distanceKm"),
        ])
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.assertEqual({call.args[1]["statistic_id"] for call in self.native_add.call_args_list},{"sensor.car_speed","sensor.car_power"})

    async def test_recent_hours_are_retried_when_recorder_summary_has_finished(self):
        hours=self.history.hourly()["telemetry.speedKph"]
        self.module.native_hour_cutoff=lambda: hours[0]["time"]-1
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.native_add.assert_not_called()
        self.assertFalse(self.history.state()["statistics_pending"])
        self.add.reset_mock()
        self.module.native_hour_cutoff=lambda: hours[-1]["time"]
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.assertTrue(self.native_add.called)
        self.add.assert_not_called()

    async def test_uppercase_home_assistant_ulid_passes_recorder_identifier_rules(self):
        import re
        self.entry.entry_id="01K74QSKRQF7R15VTP18TGW284"
        # Recorder's actual external identifier rule (HA 2026.9), rather than an accepting mock.
        valid=re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_):(?!_)[\da-z_]+(?<!_)$")
        def validate(hass,metadata,rows):
            self.assertIsNotNone(valid.fullmatch(metadata["statistic_id"]))
            self.assertEqual(metadata["source"],metadata["statistic_id"].split(":")[0])
        self.add.side_effect=validate
        await self.module.sync_statistics(self.hass,self.entry,self.history)
        self.assertTrue(self.add.called)
        self.assertTrue(self.native_add.called)

    async def test_local_energy_upgrade_corrects_or_removes_only_affected_statistics(self):
        import json
        from .test_energy import zero_power_day
        for missing in (False, True):
            with self.subTest(missing=missing):
                day = zero_power_day()
                if missing:
                    day['trips'][0]['telemetry'][30]['batteryEnergyWh'] = None
                self.repo.drive.publish(2 if not missing else 3, uniform=True, include_history=False, latest_day=day)
                snapshot = await self.repo.refresh()
                await sync_history(self.history, self.repo, snapshot, asyncio.to_thread)
                with self.history.connect() as db:
                    self.history.put(db, 'processing_version', 2)
                    self.history.put(db, 'statistics_pending', True)
                    for row_id, data in db.execute("SELECT id,data FROM records WHERE kind='telemetry'"):
                        point = json.loads(data)
                        point.update(powerKw=0, powerSource='vehicle_sensor')
                        db.execute('UPDATE records SET data=? WHERE id=?', (json.dumps(point), row_id))
                    for row_id, data in db.execute("SELECT id,data FROM records WHERE kind='trip'"):
                        summary = json.loads(data)
                        summary.update(energyKwh=0, efficiencyKwhPer100Km=0)
                        db.execute('UPDATE records SET data=? WHERE id=?', (json.dumps(summary), row_id))
                await self.module.sync_statistics(self.hass, self.entry, self.history)
                self.assertEqual(self.history.hourly()['telemetry.powerKw'][0]['mean'], 0)
                self.recorder.async_clear_statistics.reset_mock()
                self.native_add.reset_mock()
                self.add.reset_mock()
                self.history.initialize()
                await self.module.sync_statistics(self.hass, self.entry, self.history)
                native = {call.args[1]['statistic_id']: call for call in self.native_add.call_args_list}
                external = {call.args[1]['statistic_id']: call for call in self.add.call_args_list}
                self.assertNotIn('sensor.car_speed', native)
                if missing:
                    cleared = {key for call in self.recorder.async_clear_statistics.call_args_list for key in call.args[0]}
                    self.assertIn('sensor.car_power', cleared)
                    self.assertIn(statistic_id('entry1', 'telemetry.powerKw'), cleared)
                    self.assertIn(statistic_id('entry1', 'trip.energyKwh'), cleared)
                    self.assertNotIn('sensor.car_speed', cleared)
                    self.assertNotIn('sensor.car_power', native)
                else:
                    self.assertEqual(native['sensor.car_power'].args[2][0]['mean'], 36)
                    self.assertEqual(external[statistic_id('entry1', 'trip.energyKwh')].args[2][0]['mean'], .6)
                self.assertFalse(self.history.state()['statistics_pending'])
