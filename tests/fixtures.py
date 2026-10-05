"""Synthetic exports matching the Android app's V3 and trip-schema-17 writers."""

import copy
import hashlib
import io
import json
from zipfile import ZipFile, ZIP_DEFLATED

from . import bootstrap
from custom_components.aaos_drive.const import TELEMETRY_FIELDS


def encoded(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


def zipped(files):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def day_document(date, trip_id, start=1791090000000):
    sample = {key: None for key in TELEMETRY_FIELDS}
    sample.update(recordedAt=start + 60000, speedKph=0.0, powerKw=-3.2,
                  batteryPercent=72.5, chargePortConnected=False, absActive=False,
                  wheelTickLeftFront=2**40, gearSelection=999, powerSource="vehicle_sensor")
    trip = {
        "tripId": trip_id, "localId": 1, "startedAt": start, "endedAt": start + 60000,
        "storageUnitSystem": "metric", "distanceKm": 1.2, "energyKwh": -0.01,
        "energySource": "vehicle_sensor", "averageSpeedKph": 72.0, "maxSpeedKph": 80.0,
        "maxAccelerationG": 0.1, "maxBrakingG": 0.2, "maxLateralG": 0.3,
        "startLat": 52.0, "startLon": 5.0, "endLat": 52.01, "endLon": 5.01,
        "routeKey": "route-a", "weather": None,
        "weatherSamples": [{"temperatureC": 10.0, "windKph": 15.0, "precipitationMm": 0.5,
                            "capturedAt": start + 30000, "latitude": 52.0, "longitude": 5.0}],
        "telemetry": [sample],
        "route": [{"recordedAt": start, "latitude": 52.0, "longitude": 5.0},
                  {"recordedAt": start + 60000, "latitude": 52.01, "longitude": 5.01}],
    }
    return {"format": "aaos-triplog-day", "formatVersion": 1, "tripSchemaVersion": 17,
            "date": date, "bucketTimeZone": "Europe/Amsterdam", "timestampUnit": "unix_ms",
            "storageUnitSystem": "metric", "powerSignConvention": "positive_consumption_negative_regeneration",
            "datasetId": "dataset-a", "carName": "Test car", "generatedAt": start + 120000, "trips": [trip]}


def generation(sequence=1, include_history=True, empty=False):
    blobs, descriptors = {}, []

    def artifact(key, kind, period, data, count):
        sha = hashlib.sha256(data).hexdigest()
        name = f"{kind.replace('_', '-')}-{period + '-' if period else ''}{sha}.{'zip' if kind.endswith('archive') else 'json'}"
        descriptor = {"logicalKey": key, "logicalType": kind, "period": period,
                      "relativePath": f"V3/Artifacts/{name}", "mimeType": "application/zip" if kind.endswith("archive") else "application/json",
                      "size": len(data), "sha256": sha, "tripCount": count}
        blobs[name] = data
        descriptors.append(descriptor)
        return descriptor

    months = []
    latest = day_document("2026-10-04", "dataset-a-2")
    if not empty:
        day = artifact("day:2026-10-04", "day_archive", "2026-10-04", zipped({"2026-10-04.json": encoded(latest)}), 1)
        week = artifact("week:2026-W40", "week_index", "2026-W40", encoded({"format": "aaos-triplog-generation-week", "days": [day], "tripCount": 1, "distanceKm": 1.2}), 1)
        month = artifact("month:2026-10", "month_index", "2026-10", encoded({"format": "aaos-triplog-generation-month", "days": [day], "weeks": [week]}), 1)
        months.append({"month": "2026-10", "tripCount": 1, "distanceKm": 1.2, "energyKwh": -0.01,
                       "drivingTimeMs": 60000, "artifact": month})
        if include_history:
            old = day_document("2026-09-02", "dataset-a-1", start=1788343200000)
            old_archive = artifact("archive:2026-09", "month_archive", "2026-09", zipped({
                "days/2026-09-02.json": encoded(old), "month.json": encoded({"tripCount": 1}),
                "manifest.json": encoded({"format": "aaos-triplog-month-archive"}), "README.md": b"AAOS Logging",
            }), 1)
            months.insert(0, {"month": "2026-09", "tripCount": 1, "distanceKm": 1.2, "energyKwh": -0.01, "drivingTimeMs": 60000, "artifact": old_archive})
    total = sum(month["tripCount"] for month in months)
    catalog = {"format": "aaos-triplog-generation-catalog", "formatVersion": 3, "tripSchemaVersion": 17,
               "datasetId": "dataset-a", "vehicleId": "vehicle-a", "timeZone": "Europe/Amsterdam", "carName": "Test car",
               "vehicle": {"configuredName": "Test car", "identity": {"make": "Example", "model": "EV", "modelYear": 2026},
                           "specifications": {"nominalEvBatteryCapacityWh": 75000, "evConnectorTypes": [{"code": 1, "name": "TYPE_2"}],
                                              "exteriorDimensionsMm": {"height": 1500}}, "readableStaticProperties": [123]},
               "months": months, "generatedAt": 1791090120000}
    artifact("catalog", "catalog", None, encoded(catalog), total)
    manifest = {"format": "aaos-triplog-drive-generation", "formatVersion": 3, "tripSchemaVersion": 17,
                "datasetId": "dataset-a", "vehicleId": "vehicle-a", "generationId": f"g{sequence}-fixture",
                "generationSequence": sequence, "previousGenerationId": None, "generatedAt": 1791090120000,
                "timeZone": "Europe/Amsterdam", "totalTripCount": total,
                "latestTripEndTimestamp": latest["trips"][0]["endedAt"] if total else None,
                "snapshotSha256": "a" * 64, "artifacts": sorted(descriptors, key=lambda a: a["logicalKey"])}
    filename = f"commit-{sequence:020d}-g{sequence}-fixture.json"
    return filename, encoded(manifest), blobs, latest


class FakeDrive:
    def __init__(self, sequence=1, **kwargs):
        self.downloads = []
        self.publish(sequence, **kwargs)

    def publish(self, sequence, **kwargs):
        self.filename, self.commit, self.blobs, self.day = generation(sequence, **kwargs)
        self.folder_lists = {
            "car": [{"id": "sync", "name": "Sync", "mimeType": "application/vnd.google-apps.folder"}],
            "sync": [{"id": "v3", "name": "V3", "mimeType": "application/vnd.google-apps.folder"}],
            "v3": [{"id": "commits", "name": "Commits", "mimeType": "application/vnd.google-apps.folder"},
                   {"id": "artifacts", "name": "Artifacts", "mimeType": "application/vnd.google-apps.folder"}],
            "commits": [{"id": "head", "name": self.filename}],
            "artifacts": [{"id": name, "name": name, "size": str(len(data)), "sha256Checksum": hashlib.sha256(data).hexdigest()}
                          for name, data in self.blobs.items()],
        }

    async def children(self, parent):
        return copy.deepcopy(self.folder_lists[parent])

    async def child_folder(self, parent, name):
        matches = [f for f in self.folder_lists[parent] if f["name"] == name]
        if len(matches) != 1:
            from custom_components.aaos_drive.model import InvalidExport
            raise InvalidExport("Folder missing")
        return matches[0]["id"]

    async def download(self, file_id, limit=None):
        self.downloads.append(file_id)
        return self.commit if file_id == "head" else self.blobs[file_id]
