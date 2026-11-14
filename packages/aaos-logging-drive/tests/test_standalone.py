"""Run against an installed wheel; no HA stubs or integration source required."""

import asyncio
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

from aaos_logging_drive import (
    AAOSDriveClient, DriveAuthError, DriveRepository, ExportNotReady,
    HistoryStore, InvalidExport, capacity_telemetry, review_energy,
)


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


class MemoryDrive:
    """One synthetic V3 generation, served through the public transport interface."""

    def __init__(self):
        self.publish(1)

    def publish(self, sequence):
        self.files = {}
        self.descriptors = []

        def artifact(key, kind, period, content):
            name = key.replace(":", "-") + (".zip" if kind == "day_archive" else ".json")
            value = {"logicalKey": key, "logicalType": kind, "period": period,
                     "relativePath": "V3/Artifacts/"+name, "size": len(content),
                     "sha256": hashlib.sha256(content).hexdigest(), "tripCount": 1,
                     "mimeType": "application/zip" if kind == "day_archive" else "application/json"}
            self.files[name] = content
            self.descriptors.append(value)
            return value

        start = 1791090000000
        self.trip = {"tripId": "synthetic-1", "startedAt": start, "endedAt": start+60000,
            "storageUnitSystem": "metric", "distanceKm": 1, "energyKwh": .02,
            "energySource": "vehicle_sensor", "vehicleType": "ELECTRIC", "route": [],
            "telemetry": [{"recordedAt": start+i*2000, "speedKph": sequence*10,
                "batteryCurrentCapacityWh": 72000, "batteryNominalCapacityWh": 75000,
                "powerKw": 1.2, "powerSource": "vehicle_sensor"} for i in range(3)]}
        day = {"format": "aaos-triplog-day", "formatVersion": 1, "tripSchemaVersion": 17,
               "datasetId": "synthetic-dataset", "date": "2026-10-04", "timestampUnit": "unix_ms",
               "storageUnitSystem": "metric", "powerSignConvention": "positive_consumption_negative_regeneration",
               "trips": [self.trip]}
        stream = io.BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            archive.writestr("2026-10-04.json", encoded(day))
        daily = artifact("day:2026-10-04", "day_archive", "2026-10-04", stream.getvalue())
        month = artifact("month:2026-10", "month_index", "2026-10", encoded({"days": [daily]}))
        catalog = {"format": "aaos-triplog-generation-catalog", "formatVersion": 3,
            "tripSchemaVersion": 17, "timeZone": "Europe/Amsterdam",
            "datasetId": "synthetic-dataset", "vehicleId": "synthetic-car", "generatedAt": start+120000,
            "vehicle": {}, "months": [{"month": "2026-10", "tripCount": 1, "distanceKm": 1,
                "energyKwh": .02, "drivingTimeMs": 60000, "artifact": month}]}
        artifact("catalog", "catalog", None, encoded(catalog))
        self.head = f"commit-{sequence:020d}-synthetic-{sequence}.json"
        self.files[self.head] = encoded({"format": "aaos-triplog-drive-generation", "formatVersion": 3,
            "tripSchemaVersion": 17, "datasetId": "synthetic-dataset", "vehicleId": "synthetic-car",
            "timeZone": "Europe/Amsterdam", "generationSequence": sequence,
            "generationId": f"synthetic-{sequence}", "generatedAt": start+120000,
            "latestTripEndTimestamp": start+60000, "totalTripCount": 1, "artifacts": self.descriptors})

    async def child_folder(self, parent, name):
        return {("car", "Sync"): "sync", ("sync", "V3"): "v3",
                ("v3", "Commits"): "commits", ("v3", "Artifacts"): "artifacts"}[(parent, name)]

    async def children(self, parent):
        if parent == "commits":
            return [{"id": self.head, "name": self.head}]
        return [{"id": name, "name": name, "size": str(len(content)),
                 "sha256Checksum": hashlib.sha256(content).hexdigest()}
                for name, content in self.files.items() if name != self.head]

    async def download(self, file_id, limit=None):
        return self.files[file_id]


class MemorySession:
    """aiohttp's public GET/context-manager shape, with no network access."""

    def __init__(self, drive):
        self.drive = drive
        self.calls = []

    def get(self, url, **options):
        self.calls.append((url, options))
        objects = {"blob"+str(index): name for index, name in enumerate(self.drive.files)}
        if options["params"].get("alt") == "media":
            data = self.drive.files[objects[url.rsplit("/", 1)[1]]]
        else:
            parent = options["params"]["q"].split("'")[1]
            folder = lambda identity, name: {"id": identity, "name": name, "mimeType": "application/vnd.google-apps.folder"}
            folders = {"car": [folder("sync", "Sync")], "sync": [folder("v3", "V3")],
                       "v3": [folder("commits", "Commits"), folder("artifacts", "Artifacts")]}
            if parent in folders:
                rows = folders[parent]
            else:
                rows = [{"id": identity, "name": name, "size": str(len(self.drive.files[name])),
                         "sha256Checksum": hashlib.sha256(self.drive.files[name]).hexdigest()}
                        for identity, name in objects.items() if (name == self.drive.head) == (parent == "commits")]
            data = encoded({"files": rows})

        class Response:
            status = 200

            def __init__(self):
                self.content = self

            async def iter_chunked(self, size):
                yield data

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        return Response()


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.history = HistoryStore(Path(self.temporary.name)/"history.sqlite")
        self.history.initialize()
        self.drive = MemoryDrive()
        self.client = AAOSDriveClient(DriveRepository(self.drive, "car"), self.history)

    async def test_complete_import_and_paginated_queries_work_without_home_assistant(self):
        await self.client.refresh()
        self.assertEqual((await self.client.history_fields())["trip_count"], 1)
        trips = await self.client.list_trips("2026-10")
        self.assertEqual(trips[0]["tripId"], "synthetic-1")
        first = await self.client.get_history("telemetry.speedKph", limit=2)
        second = await self.client.get_history("telemetry.speedKph", limit=2, cursor=first["next_cursor"])
        self.assertEqual([p["value"] for p in first["points"]+second["points"]], [10]*3)
        self.assertEqual(await self.client.get_trip(), self.drive.trip)
        self.assertFalse(any(name.startswith(("homeassistant", "custom_components")) for name in sys.modules))

    async def test_next_generation_replaces_data_without_duplicates(self):
        await self.client.refresh()
        old = (await self.client.get_history("telemetry.speedKph", limit=1))["next_cursor"]
        self.drive.publish(2)
        await self.client.refresh()
        await self.client.refresh()
        self.assertEqual(len(await self.client.list_trips()), 1)
        self.assertEqual([p["value"] for p in (await self.client.get_history("telemetry.speedKph"))["points"]], [20]*3)
        with self.assertRaises(InvalidExport):
            await self.client.get_history("telemetry.speedKph", limit=1, cursor=old)

    async def test_day_query_loads_timezone_in_the_default_executor(self):
        snapshot = await self.client.refresh()
        loop_thread = threading.get_ident()

        def load_zone(name):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            return ZoneInfo(name)

        with patch("aaos_logging_drive.repository.ZoneInfo", side_effect=load_zone) as resolve:
            trips = await self.client.repository.trips(snapshot, "2026-10-04")
            self.assertEqual([trip["tripId"] for trip in trips], ["synthetic-1"])
            resolve.assert_called_once_with("Europe/Amsterdam")

    async def test_invalid_generation_preserves_snapshot_history_and_checkpoint(self):
        before = await self.client.refresh()
        checkpoint = self.client.accepted_head
        self.drive.publish(2)
        self.drive.files["day-2026-10-04.zip"] = b"invalid archive"
        with self.assertRaises(InvalidExport):
            await self.client.refresh()
        self.assertIs(self.client.snapshot, before)
        self.assertEqual(self.client.accepted_head, checkpoint)
        self.assertEqual((await self.client.get_history("telemetry.speedKph"))["points"][0]["value"], 10)
        checkpoint["identity"]["datasetId"] = "changed-by-caller"
        self.assertEqual(self.client.accepted_head["identity"]["datasetId"], "synthetic-dataset")

    async def test_publication_race_retries_and_auth_failure_does_not(self):
        real = self.client.repository.refresh
        self.client.repository.refresh = AsyncMock(side_effect=[ExportNotReady("pending"), await real(accept=False)])
        with patch("aaos_logging_drive.client.asyncio.sleep", new=AsyncMock()) as sleep:
            await self.client.refresh()
            sleep.assert_awaited_once_with(1)
        before = self.client.snapshot
        self.client.repository.refresh = AsyncMock(side_effect=DriveAuthError("expired"))
        with self.assertRaises(DriveAuthError):
            await self.client.refresh()
        self.client.repository.refresh.assert_awaited_once()
        self.assertIs(self.client.snapshot, before)

    async def test_factory_is_lazy_and_offline_history_does_not_require_credentials(self):
        await self.client.refresh()
        client = AAOSDriveClient.from_google_drive(object(), AsyncMock(side_effect=AssertionError("No network")),
            "https://drive.google.com/drive/folders/car", history_path=self.history.path,
            accepted_head=self.client.accepted_head)
        self.assertEqual((await client.list_trips())[0]["tripId"], "synthetic-1")
        self.assertEqual(client.accepted_head, self.client.accepted_head)

    async def test_factory_uses_caller_token_and_readonly_http_without_persisting_credentials(self):
        session = MemorySession(self.drive)
        token = AsyncMock(return_value="synthetic-private-access-token")
        path = Path(self.temporary.name)/"factory.sqlite"
        client = AAOSDriveClient.from_google_drive(session, token, "car", history_path=path)
        self.assertFalse(path.exists())
        await client.refresh()
        self.assertEqual((await client.list_trips())[0]["tripId"], "synthetic-1")
        self.assertGreater(token.await_count, 0)
        self.assertTrue(all(call[1]["headers"]["Authorization"] == "Bearer synthetic-private-access-token" for call in session.calls))
        self.assertNotIn(b"synthetic-private-access-token", path.read_bytes())

    async def test_history_query_without_import_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "complete generation"):
            await self.client.list_trips()
        client = AAOSDriveClient(DriveRepository(self.drive, "car"))
        await client.refresh()
        with self.assertRaisesRegex(ValueError, "history_path"):
            await client.list_trips()

    def test_capacity_and_energy_functions_are_standalone(self):
        original = {"batteryCurrentCapacityWh": 72000, "batteryNominalCapacityWh": 75000}
        self.assertEqual(capacity_telemetry(original)["batteryCapacityRetentionPercent"], 96)
        self.assertNotIn("batteryCapacityRetentionPercent", original)
        self.assertEqual(review_energy(self.drive.trip).quality, "measured")


if __name__ == "__main__":
    unittest.main()
