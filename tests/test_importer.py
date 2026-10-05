import asyncio
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import unittest
from zipfile import ZipFile

from . import bootstrap
from .fixtures import FakeDrive, day_document, encoded, generation, zipped
from custom_components.aaos_drive.const import BINARY_FIELDS, READ_SCOPE, TELEMETRY_FIELDS, readonly_grant
from custom_components.aaos_drive.model import Artifact, InvalidExport, Manifest, archive_trips, json_object, timestamp, trip_summary
from custom_components.aaos_drive.repository import DriveRepository


class RepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.drive = FakeDrive()
        self.repo = DriveRepository(self.drive, "car", asyncio.to_thread)

    async def test_latest_readings_and_all_history(self):
        snapshot = await self.repo.refresh()
        values = snapshot.values()
        self.assertEqual(values["dataset.totalTripCount"], 2)
        self.assertAlmostEqual(values["dataset.distanceKm"], 2.4)
        self.assertEqual(values["telemetry.powerKw"], -3.2)
        self.assertIs(values["telemetry.chargePortConnected"], False)
        self.assertIsNone(values["telemetry.chargePortOpen"])
        self.assertEqual(values["telemetry.gearSelection"], 999)
        self.assertEqual(values["telemetry.wheelTickLeftFront"], 2**40)
        self.assertEqual(values["vehicle.specifications.exteriorDimensionsMm.height"], 1500)
        self.assertEqual(values["vehicle.specifications.evConnectorTypes"][0]["code"], 1)
        trips = await self.repo.trips(snapshot)
        self.assertEqual([t["tripId"] for t in trips], ["dataset-a-1", "dataset-a-2"])
        old = await self.repo.trip(snapshot, "dataset-a-1")
        self.assertEqual(len(old["telemetry"]), 1)
        self.assertEqual(len(old["route"]), 2)
        self.assertEqual(len(old["weatherSamples"]), 1)

    async def test_staging_files_without_commit_ignored(self):
        self.drive.blobs["uncommitted.json"] = b"staging"
        snapshot = await self.repo.refresh()
        self.assertEqual(snapshot.manifest.raw["generationSequence"], 1)
        self.assertNotIn("uncommitted.json", self.drive.downloads)

    async def test_metadata_verified_for_historical_artifacts(self):
        for file in self.drive.folder_lists["artifacts"]:
            if file["name"].startswith("month-archive"):
                file["sha256Checksum"] = "0" * 64
        with self.assertRaisesRegex(InvalidExport, "checksum"):
            await self.repo.refresh()
        self.assertIsNone(self.repo.snapshot)

    async def test_missing_new_head_retains_previous_snapshot(self):
        before = await self.repo.refresh()
        self.drive.publish(2)
        self.drive.folder_lists["artifacts"] = [f for f in self.drive.folder_lists["artifacts"] if not f["name"].startswith("month-archive")]
        with self.assertRaisesRegex(InvalidExport, "missing"):
            await self.repo.refresh()
        self.assertIs(self.repo.snapshot, before)
        self.assertEqual(self.repo.accepted_head["sequence"], 1)
        self.drive.publish(2)
        after = await self.repo.refresh()
        self.assertEqual(after.manifest.raw["generationSequence"], 2)

    async def test_reject_rollback_across_restart(self):
        await self.repo.refresh()
        self.drive.publish(2)
        await self.repo.refresh()
        persisted = self.repo.accepted_head
        restarted = DriveRepository(self.drive, "car", asyncio.to_thread)
        restarted.accepted_head = persisted
        self.drive.publish(1)
        with self.assertRaisesRegex(InvalidExport, "older"):
            await restarted.refresh()

    async def test_reject_mutated_same_sequence_commit(self):
        await self.repo.refresh()
        raw = json.loads(self.drive.commit)
        raw["generatedAt"] += 1
        self.drive.commit = encoded(raw)
        with self.assertRaisesRegex(InvalidExport, "altered"):
            await self.repo.refresh()

    async def test_reject_persisted_identity_mismatch_on_first_read(self):
        self.repo.expected_identity = {"vehicleId": "another-car"}
        with self.assertRaisesRegex(InvalidExport, "different"):
            await self.repo.refresh()
        self.assertIsNone(self.repo.snapshot)

    async def test_missing_sha_downloads_all_artifacts(self):
        for file in self.drive.folder_lists["artifacts"]:
            file.pop("sha256Checksum")
        await self.repo.refresh()
        self.assertTrue(set(self.drive.blobs).issubset(set(self.drive.downloads)))

    async def test_corruption_detected_without_remote_sha(self):
        for file in self.drive.folder_lists["artifacts"]:
            file.pop("sha256Checksum")
        target = next(n for n in self.drive.blobs if n.startswith("month-archive"))
        data = bytearray(self.drive.blobs[target])
        data[-1] ^= 1
        self.drive.blobs[target] = bytes(data)
        with self.assertRaisesRegex(InvalidExport, "SHA-256"):
            await self.repo.refresh()

    async def test_repeat_refresh_uses_verified_artifact_cache(self):
        await self.repo.refresh()
        count = len(self.drive.downloads)
        await self.repo.refresh()
        self.assertEqual(len(self.drive.downloads) - count, 1)

    async def test_empty_vehicle_yields_unknown_readings_and_zero_totals(self):
        self.drive.publish(2, empty=True)
        snapshot = await self.repo.refresh()
        self.assertIsNone(snapshot.trip)
        self.assertEqual(snapshot.values()["dataset.totalTripCount"], 0)
        self.assertIsNone(snapshot.values()["telemetry.batteryPercent"])

    async def test_period_filter_and_complete_trip_id(self):
        snapshot = await self.repo.refresh()
        self.assertEqual(len(await self.repo.trips(snapshot, "2026-09")), 1)
        self.assertEqual(len(await self.repo.trips(snapshot, "2026-09-02")), 1)
        self.assertEqual(await self.repo.trips(snapshot, "2026-09-03"), [])
        self.assertEqual((await self.repo.trip(snapshot, ""))["tripId"], "dataset-a-2")
        with self.assertRaises(InvalidExport):
            await self.repo.trip(snapshot, "missing")

    async def test_summary_action_omits_large_arrays_but_preserves_measures(self):
        snapshot = await self.repo.refresh()
        summaries = await self.repo.trips(snapshot, summaries_only=True)
        self.assertEqual(len(summaries), 2)
        for summary in summaries:
            self.assertNotIn("telemetry", summary)
            self.assertEqual(summary["telemetryCount"], 1)
            self.assertEqual(summary["routePointCount"], 2)
            self.assertEqual(summary["durationSeconds"], 60)
            self.assertEqual(summary["energyKwh"], -0.01)

    async def test_week_index_available_by_committed_key(self):
        snapshot = await self.repo.refresh()
        week = await self.repo.index(snapshot, "week:2026-W40")
        self.assertEqual(week["tripCount"], 1)
        with self.assertRaises(InvalidExport):
            await self.repo.index(snapshot, "unknown")

    async def test_catalog_identity_rejected(self):
        # Change the catalog and its descriptor consistently; its dataset still must match the commit.
        manifest = json.loads(self.drive.commit)
        descriptor = next(a for a in manifest["artifacts"] if a["logicalType"] == "catalog")
        name = descriptor["relativePath"].rsplit("/", 1)[-1]
        document = json.loads(self.drive.blobs[name])
        document["datasetId"] = "wrong"
        data = encoded(document)
        descriptor.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.drive.blobs[name] = data
        for file in self.drive.folder_lists["artifacts"]:
            if file["name"] == name:
                file.update(size=str(len(data)), sha256Checksum=descriptor["sha256"])
        self.drive.commit = encoded(manifest)
        with self.assertRaisesRegex(InvalidExport, "identity"):
            await self.repo.refresh()


class ParserTests(unittest.TestCase):
    def test_negative_regeneration_and_no_divide_by_zero(self):
        trip = day_document("2026-10-04", "id")["trips"][0]
        self.assertAlmostEqual(trip_summary(trip)["efficiencyKwhPer100Km"], -0.01 / 1.2 * 100)
        trip["distanceKm"] = 0
        self.assertIsNone(trip_summary(trip)["efficiencyKwhPer100Km"])

    def test_timestamp_utc_and_invalid_values(self):
        self.assertEqual(timestamp(0).isoformat(), "1970-01-01T00:00:00+00:00")
        for value in (None, True, "123", -1, 10**100):
            self.assertIsNone(timestamp(value))

    def test_json_nonfinite_rejected(self):
        for data in (b'{"x":NaN}', b'{"x":Infinity}', b'[]', b'bad'):
            with self.assertRaises(InvalidExport):
                json_object(data)

    def test_no_write_scope_accepted(self):
        self.assertTrue(readonly_grant({"scope": READ_SCOPE}))
        for scope in ("", "https://www.googleapis.com/auth/drive.file", f"{READ_SCOPE} https://www.googleapis.com/auth/drive", f"{READ_SCOPE} https://www.googleapis.com/auth/drive.file"):
            self.assertFalse(readonly_grant({"scope": scope}))

    def test_commit_filename_sequence_checked(self):
        filename, raw, _, _ = generation()
        with self.assertRaisesRegex(InvalidExport, "disagree"):
            Manifest.parse(raw, filename.replace("00000000000000000001", "00000000000000000002"))

    def test_path_traversal_rejected(self):
        _, raw, _, _ = generation()
        artifact = json.loads(raw)["artifacts"][0]
        for path in ("../../secrets.yaml", "V3/Artifacts/../secret.zip", "https://example.com/data.zip"):
            artifact["relativePath"] = path
            with self.assertRaises(InvalidExport):
                Artifact.parse(artifact)

    def test_archive_does_not_extract_members(self):
        day = day_document("2026-10-04", "id")
        data = zipped({"2026-10-04.json": encoded(day), "../../secrets.yaml": b"ignored"})
        descriptor = Artifact("day:2026-10-04", "day_archive", "2026-10-04", "V3/Artifacts/test.zip", len(data), hashlib.sha256(data).hexdigest(), 1)
        self.assertEqual(archive_trips(data, descriptor, "dataset-a")[0]["tripId"], "id")

    def test_wrong_archive_dataset_rejected(self):
        _, raw, blobs, _ = generation()
        artifact = next(a for a in Manifest.parse(raw, "commit-00000000000000000001-g1-fixture.json").artifacts if a.kind == "day_archive")
        with self.assertRaisesRegex(InvalidExport, "dataset"):
            archive_trips(blobs[artifact.name], artifact, "other")

    def test_missing_archive_members_rejected(self):
        data = zipped({"README.md": b"empty"})
        descriptor = Artifact("day:2026-10-04", "day_archive", "2026-10-04", "V3/Artifacts/test.zip", len(data), hashlib.sha256(data).hexdigest(), 1)
        with self.assertRaisesRegex(InvalidExport, "count"):
            archive_trips(data, descriptor, "dataset-a")

    def test_all_android_export_fields_covered(self):
        source = bootstrap.ROOT.parent / "AAOS logging" / "app/src/main/kotlin/com/example/triplogger/sync/TelemetryJsonContract.kt"
        if not source.exists():
            self.skipTest("Adjacent Android logger source is not available")
        keys = set(re.findall(r'"(\w+)"\s+to\s+point\.', source.read_text()))
        self.assertEqual(set(TELEMETRY_FIELDS), keys)
        self.assertTrue(BINARY_FIELDS.issubset(keys))


if __name__ == "__main__":
    unittest.main()
