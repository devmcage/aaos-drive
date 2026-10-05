"""Strict, Home Assistant independent decoding of the logger's export contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
import hashlib
import io
import json
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any
from zipfile import BadZipFile, ZipFile

from .const import MAX_FILE_BYTES, MAX_ZIP_BYTES, TELEMETRY_FIELDS, TRIP_FIELDS, WEATHER_FIELDS


class InvalidExport(ValueError):
    """An export is inconsistent, incomplete or unsupported."""


def json_object(data: bytes) -> dict[str, Any]:
    def reject_constant(value):
        raise InvalidExport("Non-finite JSON number")

    try:
        result = json.loads(data, parse_constant=reject_constant)
    except (ValueError, UnicodeError) as err:
        raise InvalidExport("Invalid JSON document") from err
    if not isinstance(result, dict):
        raise InvalidExport("Expected a JSON object")
    return result


def integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def timestamp(value: Any) -> datetime | None:
    if not integer(value):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class Artifact:
    key: str
    kind: str
    period: str | None
    path: str
    size: int
    sha256: str
    trip_count: int

    @classmethod
    def parse(cls, item: dict) -> Artifact:
        if not isinstance(item, dict):
            raise InvalidExport("Invalid artifact descriptor")
        path, sha = item.get("relativePath", ""), item.get("sha256", "")
        if not isinstance(path, str) or not re.fullmatch(r"V3/Artifacts/[A-Za-z0-9_.-]+\.(json|zip)", path):
            raise InvalidExport("Invalid artifact path")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise InvalidExport("Invalid artifact checksum")
        if not integer(item.get("size")) or item["size"] > MAX_FILE_BYTES:
            raise InvalidExport("Artifact exceeds the 128 MiB import limit")
        if not integer(item.get("tripCount")):
            raise InvalidExport("Invalid artifact trip count")
        if not isinstance(item.get("logicalKey"), str) or not item["logicalKey"]:
            raise InvalidExport("Invalid artifact key")
        kinds = {"catalog", "day_archive", "month_archive", "week_index", "month_index"}
        if item.get("logicalType") not in kinds:
            raise InvalidExport("Unsupported artifact type")
        kind = item["logicalType"]
        if item.get("mimeType") != ("application/zip" if kind.endswith("archive") else "application/json"):
            raise InvalidExport("Artifact MIME type mismatch")
        period = item.get("period")
        pattern = {"day_archive": r"\d{4}-\d{2}-\d{2}", "month_archive": r"\d{4}-\d{2}",
                   "month_index": r"\d{4}-\d{2}", "week_index": r"\d{4}-W\d{2}"}.get(kind)
        if pattern and (not isinstance(period, str) or not re.fullmatch(pattern, period)):
            raise InvalidExport("Invalid artifact period")
        return cls(item["logicalKey"], kind, period, path, item["size"], sha, item["tripCount"])

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[1]

    def verify(self, data: bytes) -> None:
        if len(data) != self.size or hashlib.sha256(data).hexdigest() != self.sha256:
            raise InvalidExport("Artifact size or SHA-256 mismatch")


@dataclass(frozen=True)
class Manifest:
    raw: dict
    artifacts: tuple[Artifact, ...]

    @classmethod
    def parse(cls, data: bytes, filename: str) -> Manifest:
        raw = json_object(data)
        match = re.fullmatch(r"commit-(\d{20})-([A-Za-z0-9_-]+)\.json", filename)
        if not match or raw.get("format") != "aaos-triplog-drive-generation" or raw.get("formatVersion") != 3:
            raise InvalidExport("AAOS Logging Drive V3 commit required")
        if not integer(raw.get("generationSequence"), 1) or int(match[1]) != raw["generationSequence"] or match[2] != raw.get("generationId"):
            raise InvalidExport("Commit filename and generation disagree")
        for field in ("datasetId", "vehicleId", "timeZone"):
            if not isinstance(raw.get(field), str) or not raw[field]:
                raise InvalidExport("Missing commit identity")
        try:
            ZoneInfo(raw["timeZone"])
        except ZoneInfoNotFoundError as err:
            raise InvalidExport("Unknown export timezone") from err
        if not integer(raw.get("totalTripCount")) or not timestamp(raw.get("generatedAt")):
            raise InvalidExport("Invalid commit counts or time")
        if not integer(raw.get("tripSchemaVersion"), 1):
            raise InvalidExport("Invalid trip schema version")
        if raw.get("latestTripEndTimestamp") is not None and not timestamp(raw["latestTripEndTimestamp"]):
            raise InvalidExport("Invalid latest trip timestamp")
        if not isinstance(raw.get("artifacts"), list):
            raise InvalidExport("Missing artifacts")
        artifacts = tuple(Artifact.parse(item) for item in raw["artifacts"])
        if len({a.key for a in artifacts}) != len(artifacts) or len({a.path for a in artifacts}) != len(artifacts):
            raise InvalidExport("Duplicate artifacts")
        if sum(a.kind == "catalog" for a in artifacts) != 1:
            raise InvalidExport("Exactly one catalog is required")
        if sum(a.trip_count for a in artifacts if a.kind in {"day_archive", "month_archive"}) != raw["totalTripCount"]:
            raise InvalidExport("Manifest trip count mismatch")
        return cls(raw, artifacts)


def archive_trips(data: bytes, artifact: Artifact, dataset_id: str) -> list[dict]:
    """Read in memory; ZIP member names never become filesystem paths."""
    artifact.verify(data)
    trips: list[dict] = []
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10000 or any(i.file_size > MAX_FILE_BYTES for i in infos) or sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
                raise InvalidExport("Archive exceeds safe decompression limits")
            if len({i.filename for i in infos}) != len(infos):
                raise InvalidExport("Duplicate ZIP members")
            for info in infos:
                # Only the contract's day files carry trip data.
                if not re.fullmatch(r"(?:days/)?\d{4}-\d{2}-\d{2}\.json", info.filename):
                    continue
                document = json_object(archive.read(info))
                if document.get("format") != "aaos-triplog-day" or document.get("formatVersion") != 1 or document.get("datasetId") != dataset_id:
                    raise InvalidExport("Unexpected day format or dataset")
                if document.get("timestampUnit") != "unix_ms" or document.get("storageUnitSystem") != "metric":
                    raise InvalidExport("Unsupported timestamp or storage units")
                if document.get("powerSignConvention") != "positive_consumption_negative_regeneration":
                    raise InvalidExport("Unsupported power convention")
                date = document.get("date")
                if date != info.filename.rsplit("/", 1)[-1][:-5] or not isinstance(date, str):
                    raise InvalidExport("Day filename mismatch")
                if (artifact.kind == "day_archive" and date != artifact.period) or (artifact.kind == "month_archive" and date[:7] != artifact.period):
                    raise InvalidExport("Archive period mismatch")
                if not isinstance(document.get("trips"), list):
                    raise InvalidExport("Invalid trip collection")
                for trip in document["trips"]:
                    validate_trip(trip)
                    trips.append(trip)
    except (BadZipFile, RuntimeError, KeyError, OSError) as err:
        raise InvalidExport("Unreadable trip ZIP") from err
    if len(trips) != artifact.trip_count or len({t["tripId"] for t in trips}) != len(trips):
        raise InvalidExport("Archive trip count or identity mismatch")
    return trips


def validate_trip(trip: dict) -> None:
    if not isinstance(trip, dict) or not isinstance(trip.get("tripId"), str) or not trip["tripId"]:
        raise InvalidExport("Invalid trip identity")
    if trip.get("storageUnitSystem") != "metric" or not timestamp(trip.get("startedAt")):
        raise InvalidExport("Invalid trip units or start time")
    if trip.get("endedAt") is not None and (not timestamp(trip["endedAt"]) or trip["endedAt"] < trip["startedAt"]):
        raise InvalidExport("Invalid trip end time")
    for key, time_key in (("telemetry", "recordedAt"), ("route", "recordedAt"), ("weatherSamples", "capturedAt")):
        records = trip.get(key, [])
        if not isinstance(records, list) or any(not isinstance(r, dict) or not timestamp(r.get(time_key)) for r in records):
            raise InvalidExport("Invalid trip samples")


def flatten(value: dict, prefix: str = "") -> dict:
    """Keep every static field, including enum names/codes and lists."""
    out = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            out.update(flatten(item, path))
        else:
            out[path] = item
    return out


def trip_summary(trip: dict) -> dict:
    out = {k: v for k, v in trip.items() if k not in {"telemetry", "route", "weatherSamples", "weather"}}
    start, end = trip.get("startedAt"), trip.get("endedAt")
    out["durationSeconds"] = (end - start) / 1000 if integer(start) and integer(end) and end >= start else None
    distance, energy = trip.get("distanceKm"), trip.get("energyKwh")
    out["efficiencyKwhPer100Km"] = energy / distance * 100 if finite(distance) and distance > 0 and finite(energy) else None
    out.update(telemetryCount=len(trip.get("telemetry", [])), routePointCount=len(trip.get("route", [])), weatherSampleCount=len(trip.get("weatherSamples", [])))
    return out


@dataclass
class Snapshot:
    manifest: Manifest
    catalog: dict
    trip: dict | None
    checked_at: datetime

    @cached_property
    def telemetry(self) -> dict:
        records = self.trip.get("telemetry", []) if self.trip else []
        return max(records, key=lambda r: r["recordedAt"]) if records else {}

    @cached_property
    def weather(self) -> dict:
        records = self.trip.get("weatherSamples", []) if self.trip else []
        if records:
            return max(records, key=lambda r: r["capturedAt"])
        return (self.trip.get("weather") or {}) if self.trip else {}

    @cached_property
    def route(self) -> dict:
        records = self.trip.get("route", []) if self.trip else []
        return max(records, key=lambda r: r["recordedAt"]) if records else {}

    def values(self) -> dict:
        return self.readings

    @cached_property
    def readings(self) -> dict:
        telemetry, weather = self.telemetry, self.weather
        summary = trip_summary(self.trip) if self.trip else {}
        values = {f"telemetry.{k}": telemetry.get(k) for k in set(TELEMETRY_FIELDS) | telemetry.keys()}
        values.update({f"trip.{k}": summary.get(k) for k in set(TRIP_FIELDS) | summary.keys()})
        values.update({f"weather.{k}": weather.get(k) for k in set(WEATHER_FIELDS) | weather.keys()})
        values.update({f"route.{k}": self.route.get(k) for k in {"recordedAt", "latitude", "longitude"} | self.route.keys()})
        values.update({f"vehicle.{k}": v for k, v in flatten(self.catalog.get("vehicle", {})).items()})
        months = self.catalog.get("months", [])
        for month in months:
            for key, value in month.items():
                if key != "artifact":
                    values[f"month.{month['month']}.{key}"] = value
        values.update({
            "dataset.totalTripCount": self.manifest.raw["totalTripCount"],
            "dataset.distanceKm": sum(m["distanceKm"] for m in months),
            "dataset.energyKwh": sum(m["energyKwh"] for m in months),
            "dataset.drivingTimeMs": sum(m["drivingTimeMs"] for m in months),
            "dataset.generatedAt": self.manifest.raw["generatedAt"],
            "dataset.generationSequence": self.manifest.raw["generationSequence"],
            "dataset.tripSchemaVersion": self.manifest.raw["tripSchemaVersion"],
            "dataset.lastChecked": self.checked_at,
        })
        return values
