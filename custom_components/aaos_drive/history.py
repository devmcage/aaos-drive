"""Lossless local history of all committed trips, independent of Recorder retention.

All methods run in an executor. Downloads are staged by content hash; only a
fully validated generation becomes visible. OAuth credentials never enter this DB.
"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .const import BINARY_FIELDS, TELEMETRY_FIELDS, TRIP_FIELDS, WEATHER_FIELDS
from .measurements import car_sensor, series_info
from .model import InvalidExport, flatten, integer, trip_summary

ARRAYS = {"telemetry": "telemetry", "route": "route", "weatherSamples": "weather"}
KNOWN = {"telemetry": TELEMETRY_FIELDS, "weather": WEATHER_FIELDS,
         "trip": TRIP_FIELDS, "route": ("recordedAt", "latitude", "longitude")}
VISIBLE = "r.sha IN (SELECT sha FROM active) OR r.sha IN (SELECT sha FROM snapshots)"


def encoded(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise InvalidExport("Unsupported local AAOS history database version")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts(sha TEXT PRIMARY KEY, trip_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS active(sha TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS snapshots(sha TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS trips(sha TEXT, trip_id TEXT, started INTEGER, ended INTEGER, data TEXT,
                    PRIMARY KEY(sha,trip_id));
                CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, sha TEXT, trip_id TEXT,
                    kind TEXT, position INTEGER, at INTEGER, data TEXT);
                CREATE INDEX IF NOT EXISTS records_time ON records(kind,at,id);
                CREATE INDEX IF NOT EXISTS records_sha ON records(sha);
                CREATE TABLE IF NOT EXISTS fields(sha TEXT, field TEXT, PRIMARY KEY(sha,field));
                CREATE TABLE IF NOT EXISTS statistics(field TEXT PRIMARY KEY, data TEXT);
                PRAGMA user_version=1;
            """)

    @staticmethod
    def meta(db, key, default=None):
        row = db.execute("SELECT data FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def put(db, key, value):
        db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, encoded(value)))

    def state(self):
        with self.connect() as db:
            return {"generation_id": self.meta(db, "generation_id"),
                    "statistics_pending": self.meta(db, "statistics_pending", False)}

    def has_artifact(self, sha):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM artifacts WHERE sha=?", (sha,)).fetchone() is not None

    @staticmethod
    def record(db, sha, trip_id, kind, position, at, value, discovered=None):
        data = {key: None for key in KNOWN.get(kind, ())}
        data.update(flatten(value))
        db.execute("INSERT INTO records(sha,trip_id,kind,position,at,data) VALUES (?,?,?,?,?,?)",
                   (sha, trip_id, kind, position, at, encoded(data)))
        fields = {f"{kind}.{key}" for key in data}
        if discovered is not None:
            discovered.update(fields)
        else:
            db.executemany("INSERT OR IGNORE INTO fields VALUES (?,?)", ((sha, field) for field in fields))

    def stage(self, artifact, trips):
        with self.connect() as db:
            if db.execute("SELECT 1 FROM artifacts WHERE sha=?", (artifact.sha256,)).fetchone():
                return
            discovered = set()
            for trip in trips:
                trip_id = trip["tripId"]
                # Keep a complete original record for exact get_trip responses.
                db.execute("INSERT INTO trips VALUES (?,?,?,?,?)", (artifact.sha256, trip_id,
                           trip["startedAt"], trip.get("endedAt") or trip["startedAt"], encoded(trip)))
                self.record(db, artifact.sha256, trip_id, "trip", 0,
                            trip.get("endedAt") or trip["startedAt"], trip_summary(trip), discovered)
                for array, kind in ARRAYS.items():
                    for position, sample in enumerate(trip.get(array, [])):
                        at = sample["capturedAt" if kind == "weather" else "recordedAt"]
                        self.record(db, artifact.sha256, trip_id, kind, position, at, sample, discovered)
                if not trip.get("weatherSamples") and isinstance(trip.get("weather"), dict):
                    sample = trip["weather"]
                    at = sample.get("capturedAt") or trip.get("endedAt") or trip["startedAt"]
                    self.record(db, artifact.sha256, trip_id, "weather", 0, at, sample, discovered)
            db.executemany("INSERT INTO fields VALUES (?,?)", ((artifact.sha256, field) for field in discovered))
            db.execute("INSERT INTO artifacts VALUES (?,?)", (artifact.sha256, len(trips)))

    def complete(self, snapshot, indexes):
        manifest = snapshot.manifest.raw
        artifacts = [a for a in snapshot.manifest.artifacts if a.kind in {"day_archive", "month_archive"}]
        with self.connect() as db:
            identity = {key: manifest[key] for key in ("datasetId", "vehicleId")}
            if self.meta(db, "identity", identity) != identity:
                raise InvalidExport("Local history belongs to another vehicle or dataset")
            db.execute("DELETE FROM active")
            for artifact in artifacts:
                row = db.execute("SELECT trip_count FROM artifacts WHERE sha=?", (artifact.sha256,)).fetchone()
                if row is None or row[0] != artifact.trip_count:
                    raise InvalidExport("Historical archive has not been completely imported")
                db.execute("INSERT INTO active VALUES (?)", (artifact.sha256,))
            total, unique = db.execute("SELECT COUNT(*),COUNT(DISTINCT trip_id) FROM trips WHERE sha IN (SELECT sha FROM active)").fetchone()
            if total != manifest["totalTripCount"] or total != unique:
                raise InvalidExport("Historical trip identity or total count mismatch")
            sha = "snapshot:" + manifest["generationId"]
            if not db.execute("SELECT 1 FROM snapshots WHERE sha=?", (sha,)).fetchone():
                at = manifest["generatedAt"]
                self.record(db, sha, None, "vehicle", 0, at, snapshot.catalog.get("vehicle", {}))
                self.record(db, sha, None, "dataset", 0, at, {k: v for k, v in manifest.items() if k != "artifacts"})
                for position, month in enumerate(snapshot.catalog.get("months", [])):
                    self.record(db, sha, None, "month", position, at,
                                {month["month"]: {k: v for k, v in month.items() if k != "artifact"}})
                for position, (key, index) in enumerate(indexes.items()):
                    self.record(db, sha, None, "index", position, at, {key: index})
                db.execute("INSERT INTO snapshots VALUES (?)", (sha,))
            for key, value in (("identity", identity), ("generation_id", manifest["generationId"]),
                               ("manifest", manifest), ("catalog", snapshot.catalog), ("statistics_pending", True)):
                self.put(db, key, value)
            # Remove superseded detailed archives only after the complete replacement exists.
            for table in ("trips", "records", "fields", "artifacts"):
                db.execute(f"DELETE FROM {table} WHERE sha NOT IN (SELECT sha FROM active) AND sha NOT IN (SELECT sha FROM snapshots)")

    def overview(self):
        with self.connect() as db:
            row = db.execute(f"SELECT MIN(at),MAX(at),COUNT(*) FROM records r WHERE {VISIBLE}").fetchone()
            count = db.execute("SELECT COUNT(*) FROM trips WHERE sha IN (SELECT sha FROM active)").fetchone()[0]
            fields = [series_info(row[0]) for row in db.execute("SELECT DISTINCT field FROM fields WHERE sha IN (SELECT sha FROM active) OR sha IN (SELECT sha FROM snapshots) ORDER BY field")]
            return {"generation_id": self.meta(db, "generation_id"), "start": row[0], "end": row[1],
                    "trip_count": count, "record_count": row[2], "fields": fields,
                    "statistics_pending": self.meta(db, "statistics_pending", False)}

    def points(self, field, start=None, end=None, limit=2000, cursor=None, trip_id=None):
        if not isinstance(field, str) or "." not in field or not integer(limit, 1) or limit > 10000:
            raise InvalidExport("Choose a historical field and a page size from 1 to 10000")
        if any(value is not None and not integer(value) for value in (start, end)) or start is not None and end is not None and end < start:
            raise InvalidExport("History bounds must be Unix milliseconds with end >= start")
        kind, key = field.split(".", 1)
        if trip_id == "":
            trip_id = None
        if trip_id is not None and (not isinstance(trip_id, str) or not trip_id):
            raise InvalidExport("Choose a valid recorded trip")
        query = {"field": field, "start": start, "end": end, "trip_id": trip_id}
        with self.connect() as db:
            generation = self.meta(db, "generation_id")
            if cursor is not None and (not isinstance(cursor, dict) or cursor.get("generation_id") != generation
                                      or cursor.get("query") != query
                                      or not integer(cursor.get("at")) or not integer(cursor.get("id"))):
                raise InvalidExport("History changed or cursor is invalid; restart the query")
            if trip_id is not None and not db.execute("SELECT 1 FROM trips WHERE sha IN (SELECT sha FROM active) AND trip_id=?", (trip_id,)).fetchone():
                raise InvalidExport("Trip was not found in the imported history")
            rows = db.execute(f"""SELECT r.id,r.at,r.trip_id,r.position,r.data FROM records r,json_each(r.data) j
                WHERE ({VISIBLE}) AND r.kind=? AND j.key=?
                AND (? IS NULL OR r.trip_id=?)
                AND r.at>=? AND r.at<=? AND (r.at>? OR (r.at=? AND r.id>?))
                ORDER BY r.at,r.id LIMIT ?""", (kind, key, trip_id, trip_id, start or 0, end if end is not None else 2**63-1,
                cursor["at"] if cursor else -1, cursor["at"] if cursor else -1, cursor["id"] if cursor else 0, limit+1)).fetchall()
            page = rows[:limit]
            next_cursor = {"generation_id": generation, "query": query, "at": page[-1][1], "id": page[-1][0]} if len(rows) > limit else None
            return {**series_info(field), "generation_id": generation, "trip_id": trip_id,
                    "points": [{"time": r[1], "trip_id": r[2], "sample_index": r[3], "value": json.loads(r[4])[key]} for r in page],
                    "next_cursor": next_cursor}

    def trip_index(self, start=None, end=None, limit=200, cursor=None):
        """Page compact trip choices without returning their full sample arrays."""
        if not integer(limit, 1) or limit > 1000:
            raise InvalidExport("Trip page size must be from 1 to 1000")
        if any(v is not None and not integer(v) for v in (start, end)) or start is not None and end is not None and end < start:
            raise InvalidExport("Trip bounds must be Unix milliseconds with end >= start")
        query = {"start": start, "end": end}
        with self.connect() as db:
            generation = self.meta(db, "generation_id")
            if cursor is not None and (not isinstance(cursor, dict) or cursor.get("generation_id") != generation
                                      or cursor.get("query") != query or not integer(cursor.get("started"))
                                      or not isinstance(cursor.get("trip_id"), str)):
                raise InvalidExport("History changed or trip cursor is invalid; restart the query")
            where = "sha IN (SELECT sha FROM active) AND ended>=? AND started<=?"
            bounds = (start or 0, end if end is not None else 2**63-1)
            total = db.execute(f"SELECT COUNT(*) FROM trips WHERE {where}", bounds).fetchone()[0]
            rows = db.execute(f"SELECT started,trip_id,data FROM trips WHERE {where} AND (started<? OR (started=? AND trip_id<?)) ORDER BY started DESC,trip_id DESC LIMIT ?",
                              (*bounds, cursor["started"] if cursor else 2**63-1, cursor["started"] if cursor else 2**63-1,
                               cursor["trip_id"] if cursor else "", limit+1)).fetchall()
            page = rows[:limit]
            choices = []
            for started, trip_id, data in page:
                trip = json.loads(data)
                span = db.execute("SELECT MIN(at),MAX(at) FROM records WHERE sha IN (SELECT sha FROM active) AND trip_id=?", (trip_id,)).fetchone()
                summary = trip_summary(trip)
                choices.append({"trip_id": trip_id, "started_at": started, "ended_at": trip.get("endedAt") or started,
                                "sample_start": min(started, span[0] or started), "sample_end": max(trip.get("endedAt") or started, span[1] or started),
                                "distance_km": trip.get("distanceKm"), "energy_kwh": trip.get("energyKwh"),
                                "duration_seconds": summary["durationSeconds"], "telemetry_count": summary["telemetryCount"],
                                "route_count": summary["routePointCount"], "weather_count": summary["weatherSampleCount"]})
            next_cursor = {"generation_id": generation, "query": query, "started": page[-1][0], "trip_id": page[-1][1]} if len(rows) > limit else None
            return {"generation_id": generation, "trip_count": total, "trips": choices, "next_cursor": next_cursor}

    def trip(self, trip_id=""):
        with self.connect() as db:
            row = db.execute("SELECT data FROM trips WHERE sha IN (SELECT sha FROM active) AND (?='' OR trip_id=?) ORDER BY ended DESC,started DESC,trip_id DESC LIMIT 1", (trip_id, trip_id)).fetchone()
            if not row:
                raise InvalidExport("Trip was not found in the imported history")
            return json.loads(row[0])

    def summaries(self, period=""):
        if period and not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", period):
            raise InvalidExport("Period must be YYYY-MM or YYYY-MM-DD")
        from zoneinfo import ZoneInfo
        from .model import timestamp
        with self.connect() as db:
            zone = ZoneInfo(self.meta(db, "manifest")["timeZone"])
            result = []
            for (data,) in db.execute("SELECT data FROM trips WHERE sha IN (SELECT sha FROM active) ORDER BY started,trip_id"):
                trip = json.loads(data)
                if not period or timestamp(trip["startedAt"]).astimezone(zone).date().isoformat().startswith(period):
                    result.append(trip_summary(trip))
            return result

    def fields_with_data(self):
        """Measurements with a usable value anywhere in the committed history.

        False and zero are readings. Unit-bearing sensors require numbers and
        binary sensors require booleans, matching the entity value conversion.
        """
        with self.connect() as db:
            rows = db.execute("""SELECT DISTINCT r.kind,j.key,j.type
                FROM records r,json_each(r.data) j WHERE r.sha IN (SELECT sha FROM active)
                AND r.kind IN ('telemetry','weather','route') AND j.type != 'null'
                AND NOT (j.type='text' AND j.value IN ('unknown','unavailable'))""")
            result = set()
            for kind, key, value_type in rows:
                field = f"{kind}.{key}"
                if not car_sensor(field):
                    continue
                if kind == "telemetry" and key in BINARY_FIELDS:
                    valid = value_type in {"true", "false"}
                elif series_info(field)["statistic_unit"]:
                    valid = value_type in {"integer", "real"}
                else:
                    valid = True
                if valid:
                    result.add(field)
            return result

    def hourly(self):
        """Arithmetic sample statistics, never interpolate unrecorded periods."""
        with self.connect() as db:
            result = {}
            rows = db.execute("""SELECT r.kind,j.key,(r.at/3600000)*3600000,AVG(j.value),MIN(j.value),MAX(j.value)
                FROM records r,json_each(r.data) j WHERE r.sha IN (SELECT sha FROM active)
                AND j.type IN ('integer','real') GROUP BY r.kind,j.key,(r.at/3600000) ORDER BY 3""")
            for kind, key, at, mean, minimum, maximum in rows:
                field = f"{kind}.{key}"
                info = series_info(field)
                if info["timestamp_value"] or info["statistic_unit"] is None:
                    continue
                factor = info["statistic_factor"]
                result.setdefault(field, []).append({"time": at, "mean": mean*factor, "min": minimum*factor, "max": maximum*factor})
            return result

    def statistics_state(self):
        with self.connect() as db:
            return {field: json.loads(data) for field, data in db.execute("SELECT field,data FROM statistics")}

    def statistics_done(self, data):
        with self.connect() as db:
            db.execute("DELETE FROM statistics")
            db.executemany("INSERT INTO statistics VALUES (?,?)", ((key, encoded(value)) for key, value in data.items()))
            self.put(db, "statistics_pending", False)

    def remove(self):
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)


async def sync_history(store, repository, snapshot, executor):
    state = await executor(store.state)
    if state["generation_id"] == snapshot.manifest.raw["generationId"]:
        return
    for artifact in snapshot.manifest.artifacts:
        if artifact.kind not in {"day_archive", "month_archive"} or await executor(store.has_artifact, artifact.sha256):
            continue
        trips = await repository.archive(snapshot, artifact)
        await executor(store.stage, artifact, trips)
    indexes = {}
    for artifact in snapshot.manifest.artifacts:
        if artifact.kind in {"week_index", "month_index"}:
            indexes[artifact.key] = await repository.index(snapshot, artifact.key)
    await executor(store.complete, snapshot, indexes)


def statistic_id(entry_id, field):
    # Home Assistant's ULID entry IDs contain capitals. Recorder requires
    # lowercase slugs without consecutive/leading/trailing underscores.
    entry_slug = re.sub(r"[^a-z0-9]+", "_", entry_id.lower()).strip("_")
    slug = re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")
    digest = hashlib.sha256(field.encode()).hexdigest()[:8]
    return f"aaos_drive:{entry_slug}_{slug}_{digest}"
