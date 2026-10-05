import asyncio
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from . import bootstrap
from .fixtures import FakeDrive, day_document
from custom_components.aaos_drive.const import TELEMETRY_FIELDS
from custom_components.aaos_drive.history import HistoryStore, sync_history, statistic_id
from custom_components.aaos_drive.model import Artifact, InvalidExport
from custom_components.aaos_drive.repository import DriveRepository


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = HistoryStore(Path(self.temp.name) / "history.sqlite")
        self.store.initialize()
        self.drive = FakeDrive()
        self.repo = DriveRepository(self.drive, "car", asyncio.to_thread)
        self.snapshot = await self.repo.refresh()
        await sync_history(self.store, self.repo, self.snapshot, asyncio.to_thread)

    async def test_imports_old_month_and_current_day_and_full_records(self):
        info = self.store.overview()
        self.assertEqual(info["trip_count"], 2)
        points = self.store.points("telemetry.powerKw")["points"]
        self.assertEqual([p["trip_id"] for p in points], ["dataset-a-1", "dataset-a-2"])
        self.assertEqual([p["value"] for p in points], [-3.2, -3.2])
        self.assertEqual(self.store.trip("dataset-a-2"), self.drive.day["trips"][0])
        self.assertEqual(len(self.store.summaries("2026-09")), 1)

    async def test_all_telemetry_fields_even_unsupported_have_history(self):
        fields = {f["field"] for f in self.store.overview()["fields"]}
        self.assertTrue({f"telemetry.{key}" for key in TELEMETRY_FIELDS} <= fields)
        self.assertEqual([p["value"] for p in self.store.points("telemetry.chargePortOpen")["points"]], [None,None])
        self.assertEqual([p["value"] for p in self.store.points("telemetry.chargePortConnected")["points"]], [False,False])
        self.assertEqual([p["value"] for p in self.store.points("telemetry.gearSelection")["points"]], [999,999])
        self.assertEqual([p["value"] for p in self.store.points("telemetry.powerSource")["points"]], ["vehicle_sensor"]*2)

    async def test_route_weather_trip_measures_and_static_metadata(self):
        self.assertEqual(len(self.store.points("route.latitude")["points"]), 4)
        self.assertEqual(len(self.store.points("weather.temperatureC")["points"]), 2)
        self.assertEqual([p["value"] for p in self.store.points("trip.distanceKm")["points"]], [1.2,1.2])
        self.assertEqual(self.store.points("vehicle.identity.make")["points"][0]["value"], "Example")
        self.assertEqual(self.store.points("month.2026-09.energyKwh")["points"][0]["value"], -0.01)
        self.assertEqual(self.store.points("index.week:2026-W40.distanceKm")["points"][0]["value"], 1.2)

    async def test_range_and_cursor_do_not_lose_points(self):
        first = self.store.points("route.latitude",limit=1)
        collected = first["points"][:]
        while first["next_cursor"]:
            first = self.store.points("route.latitude",limit=1,cursor=first["next_cursor"])
            collected.extend(first["points"])
        self.assertEqual(collected, self.store.points("route.latitude")["points"])
        end = collected[1]["time"]
        self.assertEqual(len(self.store.points("route.latitude",end=end)["points"]), 2)
        self.assertEqual(self.store.points("route.latitude",start=end,end=end)["points"], [collected[1]])

    async def test_trip_filter_and_pagination_never_mix_trips(self):
        page = self.store.points("route.latitude", limit=1, trip_id="dataset-a-1")
        next_page = self.store.points("route.latitude", limit=1, cursor=page["next_cursor"], trip_id="dataset-a-1")
        self.assertEqual([p["trip_id"] for p in page["points"]+next_page["points"]], ["dataset-a-1"]*2)
        self.assertIsNone(next_page["next_cursor"])
        with self.assertRaises(InvalidExport):
            self.store.points("route.latitude", cursor=page["next_cursor"], trip_id="dataset-a-2")
        with self.assertRaises(InvalidExport):
            self.store.points("telemetry.speedKph", cursor=page["next_cursor"], trip_id="dataset-a-1")
        with self.assertRaises(InvalidExport):
            self.store.points("telemetry.speedKph", trip_id="missing")

    async def test_trip_index_pages_ranges_and_counts(self):
        page = self.store.trip_index(limit=1)
        self.assertEqual(page["trip_count"], 2)
        self.assertEqual(page["trips"][0]["trip_id"], "dataset-a-2")
        old = self.store.trip_index(limit=1, cursor=page["next_cursor"])
        self.assertEqual(old["trips"][0]["trip_id"], "dataset-a-1")
        self.assertIsNone(old["next_cursor"])
        current = page["trips"][0]
        self.assertEqual(current["route_count"], 2)
        self.assertEqual(current["telemetry_count"], 1)
        self.assertLessEqual(current["sample_start"], current["started_at"])
        self.assertGreaterEqual(current["sample_end"], current["ended_at"])
        selected = self.store.trip_index(start=current["started_at"], end=current["ended_at"])
        self.assertEqual(selected["trip_count"], 1)
        self.assertEqual(self.store.trip_index(start=current["ended_at"]+1)["trip_count"], 0)
        with self.assertRaises(InvalidExport):
            self.store.trip_index(start=1, cursor=page["next_cursor"])

    async def test_trip_cursor_is_invalidated_by_new_generation(self):
        page = self.store.trip_index(limit=1)
        self.drive.publish(2)
        snapshot = await self.repo.refresh()
        await sync_history(self.store, self.repo, snapshot, asyncio.to_thread)
        with self.assertRaises(InvalidExport):
            self.store.trip_index(cursor=page["next_cursor"])

    async def test_unchanged_refresh_and_restart_do_not_duplicate_samples(self):
        before = self.store.overview()
        self.drive.downloads.clear()
        await sync_history(self.store, self.repo, self.snapshot, asyncio.to_thread)
        self.assertEqual(self.drive.downloads, [])
        reopened = HistoryStore(self.store.path)
        reopened.initialize()
        self.assertEqual(reopened.overview(), before)

    async def test_new_generation_reuses_content_and_records_metadata_once(self):
        self.drive.publish(2)
        snapshot = await self.repo.refresh()
        self.drive.downloads.clear()
        await sync_history(self.store, self.repo, snapshot, asyncio.to_thread)
        self.assertFalse(any(name.endswith(".zip") for name in self.drive.downloads))
        self.assertEqual(len(self.store.points("telemetry.speedKph")["points"]), 2)
        self.assertEqual(len(self.store.points("vehicle.identity.make")["points"]), 2)
        cursor = {"generation_id": "g1-fixture", "at": 0,"id": 0}
        with self.assertRaises(InvalidExport):
            self.store.points("telemetry.speedKph",cursor=cursor)

    async def test_failed_archive_import_does_not_publish_partial_generation(self):
        before = self.store.overview()
        self.drive.publish(2,include_history=False)
        snapshot = await self.repo.refresh()
        # New content requires a fresh download. A late Drive disappearance must not erase old history.
        artifact = next(a for a in snapshot.manifest.artifacts if a.kind=="day_archive")
        snapshot.manifest.raw["totalTripCount"] = 99
        with self.assertRaises(InvalidExport):
            await sync_history(self.store,self.repo,snapshot,asyncio.to_thread)
        self.assertEqual(self.store.overview(), before)
        self.assertEqual(len(self.store.points("telemetry.speedKph")["points"]), 2)

    async def test_removals_follow_latest_complete_generation(self):
        self.drive.publish(2,include_history=False)
        snapshot = await self.repo.refresh()
        await sync_history(self.store,self.repo,snapshot,asyncio.to_thread)
        self.assertEqual(self.store.overview()["trip_count"],1)
        self.assertEqual(len(self.store.points("telemetry.speedKph")["points"]),1)
        with self.assertRaises(InvalidExport):self.store.trip("dataset-a-1")

    async def test_duplicate_trip_ids_roll_back_active_generation(self):
        before=self.store.overview()
        artifact=Artifact("test","day_archive","2026-10-01","V3/Artifacts/test.zip",1,"b"*64,1)
        trip=copy.deepcopy(self.store.trip("dataset-a-1"))
        self.store.stage(artifact,[trip])
        altered=copy.deepcopy(self.snapshot)
        object.__setattr__(altered.manifest,"artifacts",(*altered.manifest.artifacts,artifact))
        altered.manifest.raw["totalTripCount"]=3
        with self.assertRaises(InvalidExport):self.store.complete(altered,{})
        self.assertEqual(self.store.overview(),before)

    async def test_hourly_numeric_values_use_recording_time_no_binary_means(self):
        stats=self.store.hourly()
        self.assertEqual(len(stats["telemetry.powerKw"]),2)
        self.assertEqual(stats["telemetry.powerKw"][0]["mean"],-3.2)
        self.assertEqual(stats["telemetry.powerKw"][0]["time"]%3600000,0)
        self.assertNotIn("telemetry.recordedAt",stats)
        self.assertNotIn("telemetry.gearSelection",stats)
        self.assertNotIn("telemetry.chargePortConnected",stats)
        self.assertEqual(stats["trip.efficiencyKwhPer100Km"][0]["mean"],-0.01/1.2*100)

    async def test_multiple_samples_null_duplicates_and_unknown_future_fields(self):
        trip=copy.deepcopy(self.store.trip("dataset-a-2"))
        trip["tripId"]="extra"
        trip["telemetry"]=[{"recordedAt":trip["startedAt"],"speedKph":10,"futureField":{"value":"first"}},
                           {"recordedAt":trip["startedAt"],"speedKph":None,"futureField":{"value":"second"}},
                           {"recordedAt":trip["startedAt"]+1000,"speedKph":30,"futureField":{"value":None}}]
        artifact=Artifact("test","day_archive","2026-10-01","V3/Artifacts/test.zip",1,"c"*64,1)
        self.store.stage(artifact,[trip])
        altered=copy.deepcopy(self.snapshot)
        object.__setattr__(altered.manifest,"artifacts",(artifact,))
        altered.manifest.raw["totalTripCount"]=1
        self.store.complete(altered,{})
        p=self.store.points("telemetry.futureField.value",limit=1)
        q=self.store.points("telemetry.futureField.value",limit=1,cursor=p["next_cursor"])
        self.assertEqual([p["points"][0]["value"],q["points"][0]["value"]],["first","second"])
        self.assertEqual(self.store.trip("extra"),trip)
        self.assertEqual(self.store.hourly()["telemetry.speedKph"][0]["mean"],20)

    async def test_invalid_queries_rejected_and_fields_parameterized(self):
        for kwargs in ({"limit":0},{"start":-1},{"start":20,"end":10},{"cursor":{"id":-1,"at":0,"generation_id":"g1-fixture"}}):
            with self.assertRaises(InvalidExport):self.store.points("telemetry.powerKw",**kwargs)
        self.assertEqual(self.store.points("telemetry.'; DROP TABLE trips; --")["points"],[])
        self.assertEqual(self.store.overview()["trip_count"],2)

    async def test_empty_generation_is_valid_history(self):
        self.drive.publish(2,empty=True)
        snapshot=await self.repo.refresh()
        await sync_history(self.store,self.repo,snapshot,asyncio.to_thread)
        self.assertEqual(self.store.overview()["trip_count"],0)
        self.assertEqual(self.store.points("telemetry.speedKph")["points"],[])

    async def test_statistics_checkpoint_and_identifiers(self):
        self.assertTrue(self.store.state()["statistics_pending"])
        self.store.statistics_done({"telemetry.speedKph":{"digest":"test","hours":[1]}})
        self.assertFalse(self.store.state()["statistics_pending"])
        self.assertEqual(self.store.statistics_state()["telemetry.speedKph"]["hours"],[1])
        self.assertNotEqual(statistic_id("entry","trip.distanceKm"),statistic_id("entry2","trip.distanceKm"))
        self.assertNotEqual(statistic_id("entry","a.b"),statistic_id("entry","a_b"))
        self.assertRegex(statistic_id("01K74QSKRQF7R15VTP18TGW284","telemetry.speedKph"),r"^aaos_drive:01k74qskrqf7r15vtp18tgw284_telemetry_speedkph_[a-f0-9]{8}$")
        self.assertNotIn("__",statistic_id("ENTRY","telemetry.future__field..value"))
