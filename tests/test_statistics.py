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
from .fixtures import FakeDrive
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
        ha_stub.module("homeassistant.components.recorder",get_instance=lambda hass:self.recorder)
        ha_stub.module("homeassistant.components.recorder.models",StatisticMeanType=IntEnum("MeanType",{"ARITHMETIC":1}))
        ha_stub.module("homeassistant.components.recorder.statistics",async_add_external_statistics=self.add,async_import_statistics=self.native_add)
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
