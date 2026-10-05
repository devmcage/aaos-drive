# AAOS Logging for Home Assistant

<img src="custom_components/aaos_drive/brand/icon@2x.png" width="96" height="96" alt="Official AAOS Logging icon">

A read-only Home Assistant integration for **all recorded AAOS Logging vehicle data over time**, imported from the user's Google Drive.

User documentation: [Detailed installation guide](docs/INSTALLATION.md) and [Complete attribute and data reference](docs/ATTRIBUTES.md).

Version **0.4.2** supports Drive sync **V3**, TripLog day format **1**, trip schema **17**, and Home Assistant **2026.9 or later**. The Android app does not need changes. The integration and trip dashboard use the [official AAOS Logging artwork](icon/README.md).

## Recorded history

The first successful refresh imports every completed trip in the committed Drive dataset, including previous months. Later refreshes import changed archives and reuse unchanged content.

Open **AAOS history** in the Home Assistant sidebar using an administrator account. The trip dashboard lets you choose a vehicle, a recorded trip and a sensor, or all trips within a date range. The initial range covers all imported history. The same card can show several sensor charts with shared trip/date filters on a Home Assistant dashboard.

- Every exported telemetry field has its original timestamped samples, including battery, speed, power, G forces, tyre pressures, brakes, lights, seats, engine readings and driver-assistance states.
- Boolean states, raw enum codes, text, null values and new export fields remain available.
- Weather samples, GPS route samples and every trip's measurements are included.
- Vehicle metadata, catalog month measures and week/month indexes are recorded when their committed export is imported.
- Load additional sample pages as needed. **Export full selected history (CSV)** retrieves every page for the selected sensor and trip/date range. Its value_json column preserves null, boolean, numeric, text and structured values.
- Complete original trip records are available through Home Assistant actions.

Numeric measurements with recognized units are imported at their original recording hours into Home Assistant's **long-term statistics**. Measured sensors such as speed, power and battery percentage also receive statistics under their **actual sensor entity IDs**, which Home Assistant's native History page requests. External statistics with `aaos_drive:` IDs remain available for compatibility and trip summaries. These are arithmetic sample means, minima and maxima; trip measurements are assigned to the trip's ending hour. They are not cumulative energy totals.

The device contains stable entities for measured telemetry, route and weather fields. Each shows the most recent recorded value and includes its recording time and trip ID. Month-specific summaries, last-trip summaries, dataset counters and static specifications are not sensor entities; those records remain available through actions and local history. Timestamps and telemetry power-source metadata are attributes/data, rather than separate sensors.

Sensors with no usable readings anywhere in the first complete imported history are **hidden** through Home Assistant's entity registry. Zero, false and untranslated enum codes count as readings. A sensor with older readings stays visible even when its latest value is unknown. Hidden entities remain enabled, and all original fields and samples stay available in the trip dashboard/actions. Automatically hidden sensors become visible when a later import supplies a valid reading; temporary missing values do not hide them again. Show or hide individual entities through their Home Assistant settings to override this default. User-hidden sensors stay hidden.

Select a measured numeric sensor in native **History** to view its imported hourly records. A native **Statistics graph** card can use the same sensor entity ID. Numeric entities have a measurement state class, so Home Assistant also records their latest received states after installation. Those later state updates are distinct from the past hours imported from the car.

Raw entity states cannot be backdated through the supported import helper. Use the bundled **AAOS trip dashboard** for every original sample, including boolean states and enum codes. Native hourly backfill waits until at least one hour after the recorded hour ends, avoiding a race with Recorder's hourly compiler; older imported days appear after setup. Read the [installation guide](docs/INSTALLATION.md#examples) for dashboard examples and the [data reference](docs/ATTRIBUTES.md) for interpretation.

## Install or upgrade

### Install with HACS

1. Open **HACS → three-dot menu → Custom repositories**.
2. Add `https://github.com/devmcage/aaos-drive` with type **Integration**.
3. Find **AAOS Logging Drive** in HACS and download it.
4. Restart Home Assistant, then follow the [Google credentials and configuration instructions](docs/INSTALLATION.md#configuration).

[Open the repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=devmcage&repository=aaos-drive&category=integration).

HACS installs and updates the integration files. Each user still configures their own read-only Google OAuth client and car folder. This repository can be added as a custom integration; inclusion in the default HACS catalog requires a separate review.

### Manual installation

1. Download `aaos-drive-0.4.2.zip` from the [GitHub release](https://github.com/devmcage/aaos-drive/releases/latest) and unzip it.
2. Copy the **whole `custom_components/aaos_drive` folder** into `/config/custom_components/aaos_drive`, replacing the earlier version when upgrading.
3. Restart Home Assistant.
4. Complete a Google Drive sync in AAOS Logging. In Drive, copy the URL of `AAOSLogging/<car-name>_<vehicle-id>`, the vehicle folder containing `Sync` and `Backup`.
5. Add **AAOS Logging Drive** under **Settings → Devices & services**. Supply the Google application credentials described below, sign in to an account with access to the vehicle folder, and paste its URL or ID.
6. Allow the first full history import to finish. Large datasets need more time and local disk space.
7. Open **AAOS history** in the sidebar. Each vehicle dataset can be configured separately.

Existing installations keep their configuration, imported history and measured-sensor unique IDs. Restarting after upgrading automatically removes the integration's obsolete month/trip/dataset/specification sensor entries from the entity registry. Dashboards referencing those removed summaries need updating. Sensor names use **Telemetry**, **Route** and **Weather**; custom names on retained entities are preserved. Update an existing dashboard resource URL to `/aaos_drive/history.js?v=0.4.2` and refresh the browser.

Upgrading to 0.4.1 applies the empty-sensor visibility default once to existing AAOS measurement entities, using all locally imported history even when Drive has not changed. Existing user-hidden entities are left hidden. Later manual show/hide choices are preserved across refreshes and restarts. Buttons, diagnostic entities and the position tracker are unaffected.

Upgrading from 0.3 automatically adds native sensor statistics even when the Drive generation is unchanged. IDs are resolved through the entity registry, so renamed sensors work. The sensor's `historical_statistic_id` attribute now points to its own entity ID; `external_historical_statistic_id` points to the compatible external series. External IDs normalize Home Assistant's uppercase config-entry ULIDs to lowercase, as Recorder requires.

## Google credentials and read-only access

Home Assistant's built-in Google Drive integration [only reads its own backup files](https://www.home-assistant.io/integrations/google_drive/#known-limitations), so this integration uses Home Assistant's native Application Credentials and OAuth flow.

1. Enable **Google Drive API** in a Google Cloud project you control.
2. Configure consent for only `https://www.googleapis.com/auth/drive.readonly`.
3. Create a dedicated OAuth client of type **Web application**.
4. Register the redirect URI shown by Home Assistant. With My Home Assistant enabled, it is `https://my.home-assistant.io/redirect/oauth`.
5. Enter that client's ID and secret in Home Assistant's application credentials dialog and approve view/download access.

This package contains no registered client ID, secret or user tokens. Home Assistant stores the credentials entered during installation and manages their token refresh. The integration rejects Drive write scopes and sends only GET requests to the Drive API.

Google's read-only scope covers files the authorized account can access, not just one folder. The importer traverses only the selected vehicle folder. A separate account with viewer access to that folder can narrow the account boundary. In Google's Testing mode, Drive refresh tokens can [expire after seven days](https://developers.google.com/identity/protocols/oauth2#expiration).

## Refresh

The integration polls every **15 minutes** by default. Change the interval and stale threshold with its **Configure** button. Press **Refresh Drive data** for an immediate import.

A refresh reads files already uploaded by the car. It does not request an upload or control the car. The stale indicator refers to the recording time, not the most recent Drive check.

## Home Assistant actions

All actions select the vehicle through `config_entry_id` and return response data. Use `response_variable` in scripts.

| Action | Extra input | Response |
| --- | --- | --- |
| `get_history_fields` | None | Every historical field, time bounds, trip count and sample count |
| `get_history` | Required `field`; optional `trip_id`, Unix-ms `start`, `end`, `limit`, `cursor` | Original timestamped values for one trip or across imported trips |
| `get_trip` | Optional `trip_id`; blank selects the most recent trip | Complete original trip with every telemetry, route and weather sample |
| `list_trips` | Optional `period`: YYYY-MM or YYYY-MM-DD | Measurements for all matching trips |
| `get_catalog` | None | Complete current manifest and vehicle catalog |
| `get_index` | Required `logical_key`, such as week:2026-W40 | Complete current weekly/monthly index |

Example:

```yaml
- action: aaos_drive.get_history
  data:
    config_entry_id: YOUR_AAOS_CONFIG_ENTRY_ID
    field: telemetry.powerKw
    limit: 2000
  response_variable: recorded_power
```

Follow `next_cursor` until it is null to retrieve the full series. Keep the same field, trip and bounds while paging. If a new generation arrives during pagination, restart the query. Bounds are inclusive. Historical queries read the local database; full-history actions remain available when Drive is temporarily unavailable. Current catalog/index actions require a successful current refresh.

## Integrity and retention

The importer selects the greatest numeric V3 commit sequence and validates its vehicle/dataset identity, artifact sizes and SHA-256 checksums. It downloads, hashes and decodes **all detailed trip archives** before publishing the new local history. A failed generation leaves the previous complete history visible. Duplicate trips, incomplete archives and altered commits are rejected.

History is stored in `/config/.storage/aaos_drive_<config-entry-id>_history.sqlite`. It contains logged vehicle data and source metadata, without OAuth credentials. Include it in backups. Storage grows with the dataset because the full trip JSON and searchable sample records are retained. It is independent of Recorder's ordinary state-history retention.

The detailed history follows the newest complete Drive dataset. Deleted source trips are removed only after a complete replacement generation is validated. Metadata/index snapshots collected since installation remain available at their export generation times; earlier metadata revisions cannot be reconstructed from the current export alone. Removing the integration deletes its local history and clears its owned external statistics.

ZIPs are decoded in memory and never extracted. Each compressed file or decoded member is limited to 128 MiB, with 512 MiB total uncompressed content per archive and a 32 MiB compressed cache. Parsing, hashing and database work run outside Home Assistant's event loop.

## Reading semantics and limits

- Data represents completed, synced trips rather than live vehicle state.
- Null samples stay unknown; previous values are not carried forward. Repeated timestamps remain distinct through sample indices and pagination.
- Enum codes remain unchanged; manufacturer meanings are not guessed.
- Source units are metric. Power is positive for consumption and negative for regeneration; energy may also be negative.
- Original history retains Unix-millisecond timestamps. The panel displays local times, while CSV includes UTC timestamps and Unix milliseconds.
- GPS entity state represents the latest recorded position; every recorded route point is available in history and full-trip actions.
- Only exported information can be imported. Live-only app fields absent from TelemetryJsonContract cannot be reconstructed.
- The history sidebar and its WebSocket API require a Home Assistant administrator account. Data stays between Home Assistant and Google Drive.

See the [attribute and data reference](docs/ATTRIBUTES.md) for all 68 telemetry keys, entity attributes, trip measurements and metadata, with units and interpretation.

## Verification

Portable tests cover the source-format parser, read-only transport, full history, incremental imports, trip selection, pagination, failures, corrections, native/external statistics, uppercase config-entry IDs, upgrades with unchanged Drive generations, renamed sensors, entity cleanup, historical-data visibility, automatic appearance of supported sensors, manual visibility overrides and field parity with the Android source. Home Assistant adapter tests use API doubles. The dashboard was checked in a browser against a supplied car export, including full-trip speed/power/battery charts. Reference data is not bundled in the distribution.

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -t . -q
python -m compileall -q custom_components
node --check custom_components/aaos_drive/www/history.js
node tests/test_dashboard.js
python tools/build_release.py
```

No live Home Assistant server or Google account was connected during development. End-to-end installation, OAuth consent and Recorder/chart behavior still need verification on a Home Assistant installation.
