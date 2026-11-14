# AAOS Logging Drive Python library

`aaos-logging-drive` is a standalone Python library for read-only access to AAOS
Logging exports in Google Drive. The import name is `aaos_logging_drive`.
Python 3.11 or newer is required. Home Assistant is **not** a dependency.

This source tree is prepared for its first PyPI release, version **0.1.0**.
Until it is published, install from the local project or its built wheel:

```sh
python -m pip install ./packages/aaos-logging-drive
```

After publication, the same version will be installable with:

```sh
python -m pip install aaos-logging-drive==0.1.0
```

## Read recorded trips

The caller supplies an `aiohttp.ClientSession` and an asynchronous token provider.
Use a Google OAuth grant restricted to `https://www.googleapis.com/auth/drive.readonly`.
The application owns consent, token storage and refresh; this library neither
bundles credentials nor starts a hosted authentication service.

```python
import asyncio
import os

import aiohttp
from aaos_logging_drive import AAOSDriveClient


async def token_provider():
    # For a long-running application, return a fresh OAuth access token here.
    return os.environ["AAOS_DRIVE_ACCESS_TOKEN"]


async def main():
    async with aiohttp.ClientSession() as session:
        client = AAOSDriveClient.from_google_drive(
            session,
            token_provider,
            os.environ["AAOS_DRIVE_FOLDER"],  # Car folder ID or Drive folder URL.
            history_path="car-history.sqlite",
        )
        snapshot = await client.refresh()
        print(snapshot.manifest.raw["generationId"])
        trips = await client.list_trips()
        if trips:
            trip = trips[-1]
            page = await client.get_history(
                "telemetry.speedKph", trip_id=trip["tripId"]
            )
            while True:
                for point in page["points"]:
                    print(point["time"], point["value"])
                if page["next_cursor"] is None:
                    break
                page = await client.get_history(
                    "telemetry.speedKph", trip_id=trip["tripId"],
                    cursor=page["next_cursor"],
                )


asyncio.run(main())
```

`refresh()` selects a complete immutable Drive V3 generation, checks all artifact
sizes/hashes and imports its detailed trip archives. Temporary publication races
are retried. A failed import retains the preceding complete snapshot/history.
Separate trips never share a power-estimation window. Missing data stays unknown.

## API and persistence

- `client.refresh()` returns a `Snapshot` with the latest recorded values and export metadata.
- `client.history_fields()` returns field descriptions, units, counts and time bounds.
- `client.list_trips(period="")` returns reviewed trip summaries; filter by `YYYY-MM` or `YYYY-MM-DD`.
- `client.get_trip(trip_id="")` returns the exact original trip, including its arrays; blank selects latest.
- `client.get_history(field, start=None, end=None, limit=2000, cursor=None, trip_id=None)` returns original-time readings with provenance and a continuation cursor. Bounds use Unix milliseconds.
- `client.accepted_head` is a copy of the accepted generation checkpoint. Persist it in your application and pass it back as `accepted_head=` on restart to maintain rollback protection.

For an established source, also persist `snapshot.manifest.raw["datasetId"]` and
`["vehicleId"]`, and restore them as `expected_identity={"datasetId": ..., "vehicleId": ...}`.
The library follows a changed identity only with a verified published merge;
when local history exists, all previously imported trips must be preserved.
Save checkpoints only after a successful `refresh()`. They contain source identity
and hashes, not OAuth tokens. History can be queried offline after a previous
complete import. Without `history_path`, only the validated current snapshot is available.

The session is caller-owned and is never closed by the library. All SQLite and
archive decoding work uses `asyncio.to_thread` by default. Applications can pass
another asynchronous executor. Low-level `ReadOnlyDrive`, `DriveRepository`,
`HistoryStore`, `Manifest`, `archive_trips`, `review_energy`, `capacity_telemetry`
and `sync_history` are also available. `AAOSDriveClient(repository, history)`
supports custom transports and an already initialized history store.

## Supported data

Drive sync V3, day-file format 1, trip schema 17 and the optional powertrain-v1
extension are supported. Fuel/hybrid readings, nullable boolean states, route and
weather samples, metadata, original trip JSON, and future export fields are retained.
Fuel estimates exclude unobserved intervals and stationary use; hybrid battery
energy remains separate. Battery-energy recovery is labeled as estimated, and
capacity retention is not verified state of health. Historical recordings cannot
acquire measurements that were never logged.

The local history format and processing version are unchanged by the extraction
from the Home Assistant integration. Applications must not use one history file
concurrently from different processes. The generic hourly aggregation and opaque
statistics checkpoint are available for adapters; this package does not register
entities or write to Home Assistant Recorder.

## Build and test

```sh
python -m pip install build twine
python -m build packages/aaos-logging-drive --outdir dist
python -m twine check dist/*
python -m unittest discover -s packages/aaos-logging-drive/tests -v
```

The wheel and source distribution contain only this library, its license, and its
standalone tests/documentation. They do not contain the Home Assistant wrapper,
car data, authentication configuration or repository verification files.
