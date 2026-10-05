"""Read a single complete V3 generation without mixing generations."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import re

from .model import Artifact, InvalidExport, Manifest, Snapshot, archive_trips, finite, integer, json_object, trip_summary


class DriveRepository:
    def __init__(self, drive, vehicle_folder: str, executor, expected_identity: dict | None = None):
        self.drive = drive
        self.vehicle_folder = vehicle_folder
        self.executor = executor
        self.expected_identity = expected_identity or {}
        self.accepted_head: dict | None = None
        self.snapshot: Snapshot | None = None
        self._manifest_hash: str | None = None
        self._files: dict[str, dict] = {}
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_bytes = 0

    async def _artifact_bytes(self, artifact: Artifact, files: dict[str, dict]) -> bytes:
        if artifact.sha256 in self._cache:
            self._cache.move_to_end(artifact.sha256)
            data = self._cache[artifact.sha256]
        else:
            remote = files.get(artifact.name)
            if not remote:
                raise InvalidExport("A committed artifact is not visible yet; retry later")
            data = await self.drive.download(remote["id"])
            await self.executor(artifact.verify, data)
            # Bound retained compressed data to 32 MiB; larger archives are read on demand.
            if len(data) <= 32 * 1024 * 1024:
                while self._cache and self._cache_bytes + len(data) > 32 * 1024 * 1024:
                    _, removed = self._cache.popitem(last=False)
                    self._cache_bytes -= len(removed)
                self._cache[artifact.sha256] = data
                self._cache_bytes += len(data)
        await self.executor(artifact.verify, data)
        return data

    async def refresh(self) -> Snapshot:
        sync = await self.drive.child_folder(self.vehicle_folder, "Sync")
        root = await self.drive.child_folder(sync, "V3")
        commits_id = await self.drive.child_folder(root, "Commits")
        artifacts_id = await self.drive.child_folder(root, "Artifacts")
        candidates = []
        for file in await self.drive.children(commits_id):
            match = re.fullmatch(r"commit-(\d{20})-([A-Za-z0-9_-]+)\.json", file.get("name", ""))
            if match:
                candidates.append((int(match[1]), file))
        if not candidates:
            raise InvalidExport("No committed V3 generation; synchronize AAOS Logging first")
        newest = max(sequence for sequence, _ in candidates)
        head_files = [file for sequence, file in candidates if sequence == newest]
        if len(head_files) != 1:
            raise InvalidExport("Ambiguous latest generation sequence")
        head = head_files[0]
        raw = await self.drive.download(head["id"], limit=16 * 1024 * 1024)
        manifest = await self.executor(Manifest.parse, raw, head["name"])
        manifest_hash = hashlib.sha256(raw).hexdigest()
        if any(manifest.raw.get(key) != value for key, value in self.expected_identity.items()):
            raise InvalidExport("The selected folder contains a different vehicle or dataset")
        if self.accepted_head:
            sequence = self.accepted_head["sequence"]
            if newest < sequence or newest == sequence and manifest_hash != self.accepted_head["manifest_hash"]:
                raise InvalidExport("Drive returned an older or altered committed generation")
        if self.snapshot:
            previous = self.snapshot.manifest.raw
            if any(manifest.raw[k] != previous[k] for k in ("datasetId", "vehicleId")):
                raise InvalidExport("Drive dataset or vehicle identity changed")
            if newest < previous["generationSequence"]:
                raise InvalidExport("Drive returned an older generation; retaining the last snapshot")
            if newest == previous["generationSequence"] and manifest_hash != self._manifest_hash:
                raise InvalidExport("An immutable commit changed")
        files = {}
        for file in await self.drive.children(artifacts_id):
            if file["name"] in files:
                raise InvalidExport("Duplicate artifact filenames")
            files[file["name"]] = file
        # Validate every referenced artifact, including historical archives. Never publish a partial head.
        for artifact in manifest.artifacts:
            remote = files.get(artifact.name)
            if not remote or str(remote.get("size")) != str(artifact.size):
                raise InvalidExport("Committed artifact is missing or has a different size")
            checksum = remote.get("sha256Checksum")
            if checksum:
                if checksum != artifact.sha256:
                    raise InvalidExport("Committed artifact checksum mismatch")
            else:
                await self._artifact_bytes(artifact, files)
        catalog_artifact = next(a for a in manifest.artifacts if a.kind == "catalog")
        catalog = await self.executor(json_object, await self._artifact_bytes(catalog_artifact, files))
        await self.executor(validate_catalog, catalog, manifest)
        archives = [a for a in manifest.artifacts if a.kind in {"day_archive", "month_archive"} and a.trip_count]
        trip = None
        if archives:
            latest = max(archives, key=lambda a: a.period)
            trips = await self.executor(archive_trips, await self._artifact_bytes(latest, files), latest, manifest.raw["datasetId"])
            trip = max(trips, key=lambda t: (t.get("endedAt") or t["startedAt"], t["startedAt"], t["tripId"]))
            if (trip.get("endedAt") or trip["startedAt"]) != manifest.raw["latestTripEndTimestamp"]:
                raise InvalidExport("Latest trip does not match the committed snapshot")
        elif manifest.raw["totalTripCount"]:
            raise InvalidExport("Missing detailed trip archives")
        snapshot = Snapshot(manifest, catalog, trip, datetime.now(timezone.utc))
        self.snapshot, self._manifest_hash, self._files = snapshot, manifest_hash, files
        self.accepted_head = {"sequence": newest, "manifest_hash": manifest_hash}
        return snapshot

    async def archive(self, snapshot: Snapshot, artifact: Artifact) -> list[dict]:
        data = await self._artifact_bytes(artifact, self._files)
        return await self.executor(archive_trips, data, artifact, snapshot.manifest.raw["datasetId"])

    async def trips(self, snapshot: Snapshot, period: str = "", summaries_only: bool = False) -> list[dict]:
        if period and not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", period):
            raise InvalidExport("Period must be YYYY-MM or YYYY-MM-DD")
        result = []
        for artifact in snapshot.manifest.artifacts:
            if artifact.kind not in {"day_archive", "month_archive"}:
                continue
            if period and not (artifact.period.startswith(period) or period.startswith(artifact.period)):
                continue
            data = await self._artifact_bytes(artifact, self._files)
            trips = await self.executor(archive_trips, data, artifact, snapshot.manifest.raw["datasetId"])
            if len(period) == 10:
                # Monthly ZIPs group by start day in the export's timezone.
                from zoneinfo import ZoneInfo
                from .model import timestamp
                trips = [t for t in trips if timestamp(t["startedAt"]).astimezone(ZoneInfo(snapshot.manifest.raw["timeZone"])).date().isoformat() == period]
            result.extend([trip_summary(t) for t in trips] if summaries_only else trips)
        if len({t["tripId"] for t in result}) != len(result):
            raise InvalidExport("Duplicate trip IDs across committed archives")
        return sorted(result, key=lambda t: (t["startedAt"], t["tripId"]))

    async def trip(self, snapshot: Snapshot, trip_id: str) -> dict:
        if not trip_id:
            if snapshot.trip is None:
                raise InvalidExport("No trips in this dataset")
            return snapshot.trip
        if snapshot.trip and snapshot.trip["tripId"] == trip_id:
            return snapshot.trip
        for artifact in sorted(snapshot.manifest.artifacts, key=lambda a: a.period or "", reverse=True):
            if artifact.kind not in {"day_archive", "month_archive"}:
                continue
            data = await self._artifact_bytes(artifact, self._files)
            trips = await self.executor(archive_trips, data, artifact, snapshot.manifest.raw["datasetId"])
            for trip in trips:
                if trip["tripId"] == trip_id:
                    return trip
        raise InvalidExport("Trip ID was not found in the selected committed snapshot")

    async def index(self, snapshot: Snapshot, logical_key: str) -> dict:
        artifact = next((a for a in snapshot.manifest.artifacts if a.key == logical_key and a.kind in {"week_index", "month_index", "catalog"}), None)
        if artifact is None:
            raise InvalidExport("Index key is not in this committed snapshot; inspect Get committed catalog")
        return await self.executor(json_object, await self._artifact_bytes(artifact, self._files))


def validate_catalog(catalog: dict, manifest: Manifest) -> None:
    if catalog.get("format") != "aaos-triplog-generation-catalog" or catalog.get("formatVersion") != 3:
        raise InvalidExport("Unsupported generation catalog")
    if any(catalog.get(k) != manifest.raw[k] for k in ("datasetId", "vehicleId", "timeZone", "tripSchemaVersion")):
        raise InvalidExport("Catalog identity does not match commit")
    if catalog.get("generatedAt") != manifest.raw["generatedAt"]:
        raise InvalidExport("Catalog generation time does not match commit")
    if not isinstance(catalog.get("vehicle"), dict) or not isinstance(catalog.get("months"), list):
        raise InvalidExport("Missing vehicle or month metadata")
    months = catalog["months"]
    if len({m.get("month") for m in months if isinstance(m, dict)}) != len(months):
        raise InvalidExport("Invalid or duplicate catalog months")
    by_path = {a.path: a for a in manifest.artifacts}
    for month in months:
        if not isinstance(month, dict) or not re.fullmatch(r"\d{4}-\d{2}", month.get("month", "")):
            raise InvalidExport("Invalid catalog month")
        if not integer(month.get("tripCount")) or any(not finite(month.get(k)) for k in ("distanceKm", "energyKwh", "drivingTimeMs")):
            raise InvalidExport("Invalid month measures")
        reference = month.get("artifact", {})
        if not isinstance(reference, dict):
            raise InvalidExport("Invalid month reference")
        artifact = by_path.get(reference.get("relativePath"))
        if not artifact or artifact.kind not in {"month_archive", "month_index"} or artifact.period != month["month"] or artifact.trip_count != month["tripCount"]:
            raise InvalidExport("Catalog month reference mismatch")
        if reference.get("sha256") != artifact.sha256 or reference.get("size") != artifact.size:
            raise InvalidExport("Catalog checksum reference mismatch")
    if sum(m["tripCount"] for m in months) != manifest.raw["totalTripCount"]:
        raise InvalidExport("Catalog total trip count mismatch")
