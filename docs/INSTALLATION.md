# AAOS Logging Drive — installation for Home Assistant

AAOS Logging Drive imports your car's completed, synced trips from Google Drive into Home Assistant. It creates a car device with measured sensors, retains every exported sample, and supplies a trip dashboard and historical numeric statistics.

This guide covers integration **0.4.1**, Home Assistant **2026.9 or later**, AAOS Logging Drive sync **V3**, day-file format **1** and trip schema **17**. Its section order follows the [Home Assistant Google Drive guide](https://www.home-assistant.io/integrations/google_drive/). The setup steps below apply to **AAOS Logging Drive**, the custom integration supplied in this package.

Each household uses its own Google account and OAuth credentials. The package includes no registered client ID or secret. You do not need to operate a separate website or authorization service.

## On this page

- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Sensors](#sensors)
- [Examples](#examples)
- [Removing the integration](#removing-the-integration)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Related topics and links](#related-topics-and-links)

## Prerequisites

Have the following ready:

- A working Home Assistant installation, an administrator account and access to its configuration folder.
- HACS, or the integration's [installation ZIP](https://github.com/devmcage/aaos-drive/releases/latest) including the `custom_components/aaos_drive` folder.
- AAOS Logging on the vehicle, with at least one completed Google Drive sync using V3.
- A Google account able to view and download the vehicle's synced files.
- A Google Cloud project with Google Drive API enabled and a dedicated **Web application** OAuth client for this integration.
- Internet access from Home Assistant to Google and from the browser used for account linking.

### Prepare the vehicle data

1. Complete a trip and a Google Drive sync in AAOS Logging. Home Assistant reads files already uploaded by the app.
2. Open [Google Drive](https://drive.google.com/) using the account that will authorize Home Assistant.
3. Open `AAOSLogging`, then the folder for the required car. Its name normally follows `<car-name>_<vehicle-id>`.
4. Confirm that the vehicle folder contains `Sync/V3/Artifacts` and `Sync/V3/Commits`. A committed export contains a commit JSON file and the artifacts referenced by that file.
5. Copy the vehicle folder's browser URL. Select the **vehicle folder itself**, rather than its `Sync`, `V3`, `Artifacts` or `Backup` subfolder.

The relevant folder layout is:

```text
AAOSLogging/
  <car-name>_<vehicle-id>/       ← select this folder
    Sync/
      V3/
        Artifacts/
        Commits/
    Backup/                     ← optional; not the integration's import source
```

A ZIP downloaded from Drive is useful as a reference or backup, but the integration connects to the Drive folder. If another account owns the folder, share it with the account Home Assistant will use and give that account permission to view/download its contents.

### Scenario 1: You already have credentials

You may use an existing Google Cloud project. Check the following before continuing:

1. Open the project's [Google Drive API page](https://console.cloud.google.com/apis/library/drive.googleapis.com) and enable the API if necessary.
2. Use a dedicated OAuth client of type **Web application**. If an existing client has previously been used for Drive write access, create a separate client for AAOS Logging Drive in the same project.
3. Check the client has the authorized redirect URI that Home Assistant shows. With My Home Assistant enabled, use `https://my.home-assistant.io/redirect/oauth`.
4. Configure the app's data access for `https://www.googleapis.com/auth/drive.readonly`.
5. Keep the client ID and secret available for the Application Credentials dialog in Home Assistant.

The integration rejects a token containing other Drive scopes alongside `drive.readonly`. A client used by a different Drive integration may have a wider previous grant even when the new request asks for read-only access. A dedicated client avoids that overlap.

Continue with [Configuration](#configuration). If you need a new client or project, use Scenario 2.

### Scenario 2: You do not have credentials set up yet

#### Create a project and enable Google Drive API

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Use the project selector to create a project, for example **My AAOS Home Assistant**.
3. Make sure the new project is selected.
4. Open [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com) and select **Enable**.

Google documents API activation and OAuth client creation in its [web-server OAuth setup guide](https://developers.google.com/identity/protocols/oauth2/web-server#prerequisites).

#### Configure the consent screen

1. Open **Google Auth Platform → Branding**. Select **Get started** if the platform is not configured.
2. Enter an app name you will recognize at sign-in, such as **My AAOS Home Assistant**, and your support email.
3. For a personal Google account, select an **External** audience. An organization's Internal audience only applies to eligible accounts within that organization.
4. Enter your contact email, review Google's terms and finish the setup.
5. Under **Data Access**, add only `https://www.googleapis.com/auth/drive.readonly` for Drive access, then save.

These settings follow Google's [consent-screen instructions](https://developers.google.com/workspace/guides/configure-oauth-consent). Optional logo and website branding are separate from account linking. Use accurate details for your own app; entering the My Home Assistant redirect does not give you ownership of the `home-assistant.io` domain.

The read-only scope allows viewing and downloading files accessible to the authorized account. The importer reads the selected vehicle folder, but the Google grant itself covers the account's accessible Drive files. If you want a narrower account boundary, authorize a separate account with viewer access to the car folder. See Google's [Drive scope descriptions](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

#### Set the audience and publishing status

For an initial test, leave the app in **Testing** and add the Google account you will authorize under **Audience → Test users**. For unattended ongoing use, set the publishing status to **In production** when your setup is ready. Drive authorizations granted while an External app is in Testing expire after seven days; reconnect after changing status. Publishing does not mean Google has verified the app. See Google's [audience and publishing guidance](https://support.google.com/cloud/answer/15549945?hl=en).

Google provides a [personal-use verification exception](https://support.google.com/cloud/answer/13464323?hl=en) for limited personal use with fewer than 100 users. An unverified-app notice can still appear. This is different from distributing one shared OAuth application to a public user base. Each user of this integration sets up their own client; an organization can impose additional authorization requirements.

#### Create the OAuth client ID and secret

1. Open **Google Auth Platform → Clients → Create client**.
2. Select **Web application**, then name the client **AAOS Home Assistant client**.
3. Under **Authorized redirect URIs**, add:

   ```text
   https://my.home-assistant.io/redirect/oauth
   ```

4. Create the client and save its **Client ID** and **Client secret** securely while Google displays them. You will enter these into Home Assistant, not into the integration files.

The standard URI is a real callback supplied through My Home Assistant, not an example to replace with a new website. If your Home Assistant setup displays a different callback because My Home Assistant is disabled, register the exact callback it shows and follow Google's URI requirements. OAuth redirects must match their registered values exactly. See [Home Assistant Application Credentials](https://www.home-assistant.io/integrations/application_credentials/) and [Google's OAuth client instructions](https://developers.google.com/identity/protocols/oauth2/web-server#creatingcred).

## Configuration

### Install with HACS

1. Open **HACS** in Home Assistant.
2. Open the three-dot menu and select **Custom repositories**.
3. Add `https://github.com/devmcage/aaos-drive`, choose type **Integration**, then select **Add**.
4. Find **AAOS Logging Drive** in HACS and download the latest release.
5. Restart Home Assistant and refresh the browser.
6. Continue with [Add AAOS Logging Drive](#add-aaos-logging-drive) below. Google credentials are still required.

Alternatively, use [Open the repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=devmcage&repository=aaos-drive&category=integration), then download it.

HACS manages the files in `custom_components/aaos_drive`, including the built-in trip dashboard. Install one copy, using either HACS or the manual method below. For upgrades, use HACS's update option, restart Home Assistant and refresh the browser. Keep the existing integration entry and `.storage` history files.

### Install the custom integration files

1. Make a Home Assistant backup before replacing an existing installation.
2. Extract `aaos-drive-0.4.1.zip` on your computer.
3. Open Home Assistant's configuration directory using your normal file-access method. Home Assistant OS normally exposes it as `/config`. For a Container installation, use the host folder mounted at `/config`.
4. Create `custom_components` inside that configuration directory if it does not exist.
5. Copy the **whole** `aaos_drive` folder from the ZIP's `custom_components` directory into it. The result must include:

   ```text
   /config/custom_components/aaos_drive/manifest.json
   /config/custom_components/aaos_drive/__init__.py
   /config/custom_components/aaos_drive/www/history.js
   ```

6. When upgrading, replace the previous integration folder as a whole. Keep the vehicle configuration and `.storage` history files.
7. Restart Home Assistant. Refresh the browser if the integration is not immediately listed.

The `docs` directory is documentation and does not need copying into Home Assistant's configuration directory. Home Assistant's [configuration-directory guidance](https://www.home-assistant.io/docs/configuration/) explains where to find your configuration files for manual installation.

### Add AAOS Logging Drive

1. Sign in to Home Assistant as an administrator.
2. Open **Settings → Devices & services → Add integration**.
3. Search for and select **AAOS Logging Drive**.
4. When prompted for Application Credentials, enter the client ID and secret from your dedicated Google OAuth client. Select the correct credentials if a chooser appears.
5. Continue to Google account authorization.

Credentials are stored by Home Assistant and used by its native OAuth flow. Do not add them to YAML, the Python files or a copy of the ZIP you distribute.

### Authorize the Google account

1. Select the account with access to the vehicle folder.
2. Confirm the app name matches the OAuth application you configured. If Google shows an unverified-app notice, continue only when it refers to your own expected application and Google offers that option.
3. Approve the requested permission to view and download Drive files.
4. On **Link account to Home Assistant**, check the Home Assistant instance URL and link the account.
5. Return to the Home Assistant setup dialog.

You are authorizing Home Assistant to read your exported logs. The integration does not upload, delete or edit Drive files and does not control the vehicle.

### Select the vehicle folder and complete the import

1. In **Vehicle folder URL or ID**, paste the vehicle-folder URL saved earlier. A plain folder ID is also accepted.
2. Submit the form. The integration validates the latest committed V3 export and its vehicle/dataset identity.
3. Allow the first complete history import to finish. It imports every detailed trip archive referenced by the accepted generation, including earlier months. Large datasets need more time and local storage.
4. Open the new car device under **AAOS Logging Drive**.
5. Open **AAOS history** in the sidebar and select the vehicle. The initial date range covers imported history. Choose a trip or all trips in a period, then a sensor.

The import verifies artifact sizes, checksums and trip counts. If a generation is incomplete, it is rejected; an existing installation keeps its previous complete history. Configure additional vehicle datasets as separate integration entries. The same vehicle/dataset pair cannot be added twice.

### Configure refresh and stale detection

Open **Settings → Devices & services → AAOS Logging Drive**, then the entry's **Configure** option.

| Setting | Default | Allowed range | Meaning |
| --- | --- | --- | --- |
| Read Drive every (minutes) | 15 | 1–1440 minutes | How often Home Assistant checks already uploaded data. |
| Mark telemetry stale after (hours) | 24 | 1–8760 hours | Age after which the last recorded telemetry sample is marked stale. |

Changing options reloads the integration. Press the device's **Refresh Drive data** button for an immediate check. That button does not ask the car to upload a trip.

## Sensors

The car device has stable telemetry, weather and route entities. Numeric sensors show the latest recorded value; binary sensors show recorded true/false states. A position tracker shows the last logged position, and a diagnostic sensor reports stale telemetry. See the [attribute and data reference](ATTRIBUTES.md) for every field, unit and interpretation.

Sensors with no usable readings anywhere in the initial imported history are hidden but remain enabled. They can automatically appear when a subsequent import contains a valid reading. Sensors with past readings stay visible even if their most recent value is unknown. Zero and false are valid readings. After the default is applied, manual show/hide choices are preserved; user-hidden entities are not automatically shown.

To inspect or change an entity's visibility, open its entity settings from the device or **Settings → Devices & services → Entities**. Include hidden entities in the list/filter if necessary, then change the visibility option. Disabling an entity is a separate setting.

Month-specific summaries, trip-summary entities and static specification entities are not created on the device. Their complete data remains accessible through the history/actions described in the reference document.

## Examples

### View sensor data for one trip

1. Open **AAOS history** in the sidebar as an administrator.
2. Select the car, then choose a recorded trip.
3. Select a field such as **Telemetry speed kph**. The chart uses original timestamps within that trip's exact bounds.
4. Use **Load more samples** if another page is available. The chart initially retrieves up to 2,000 samples per field.
5. Use **Export full selected history (CSV)** to download all pages for the selected primary field and trip/date range. CSV preserves the original typed value in `value_json`.

The table displays up to the last 500 loaded primary-field records. That display limit does not remove samples from storage or the full export.

### Add a trip dashboard card

The sidebar works immediately after installation. For a dashboard card:

1. Add `/aaos_drive/history.js?v=0.4.1` as a dashboard resource of type **JavaScript module**. In the dashboard resources screen, use **Add resource**; enable Advanced mode in your profile if the resource settings are not visible.
2. Edit your dashboard, add a **Manual** card, and paste:

   ```yaml
   type: custom:aaos-history-card
   fields:
     - telemetry.speedKph
     - telemetry.powerKw
     - telemetry.batteryPercent
   ```

3. Save the card, choose the vehicle and select a trip or date period. The configured charts share those filters. The field selector adds the primary chart; its table and CSV export apply to that selected field.

Vehicle selection works without a fixed entry ID. To preselect one entry, add `config_entry_id: YOUR_AAOS_CONFIG_ENTRY_ID` to the card. The full-sample card and its history API require an administrator account.

### Use Home Assistant's native History or Statistics graph

Select a measured numeric entity in **History** and choose the dates on which the car recorded data. Recognized numeric fields have original-hour statistics linked to their actual entity IDs. Find the real entity ID in its settings; renamed entities are supported.

For example, replace the entity ID below with your speed entity:

```yaml
type: statistics-graph
entities:
  - sensor.your_car_telemetry_speed_kph
period: hour
stat_types:
  - mean
  - min
  - max
days_to_show: 7
```

Native graphs show hourly numeric aggregates for imported dates, not every original sample. Use the trip card for raw values, boolean states and enum codes. Native backfill waits until at least one hour after a recorded hour ends so Recorder's hourly compiler can finish. The [Statistics graph documentation](https://www.home-assistant.io/dashboards/statistics-graph/) explains the native card's options.

### Retrieve complete original trip data

Under **Developer tools → Actions**, select **AAOS Logging Drive: Get complete trip**, select the integration entry and supply a `trip_id` if you want a particular trip. Leaving it blank returns the latest imported trip. Available actions include listing trips, reading timestamped fields and retrieving the catalog/indexes; their inputs and results are explained in [ATTRIBUTES.md](ATTRIBUTES.md#actions-and-history-results).

## Removing the integration

### To remove an integration instance from Home Assistant

1. Open **Settings → Devices & services → AAOS Logging Drive**.
2. Find the vehicle's integration entry and select its three-dot menu.
3. Select **Delete** and confirm Home Assistant's removal prompt.

Removal deletes the entry's local AAOS history database and accepted-generation record. It requests cleanup of the entry's imported statistics, including owned native IDs still resolvable in the entity registry. Ordinary Recorder state-history retention remains governed by Home Assistant. Export or back up history first if you want to keep a local copy.

Drive files remain in the account because all integration access is read-only. Removing the integration is separate from removing its Application Credentials or revoking its Google grant. Remove unused credentials in Home Assistant's Application Credentials screen; revoke access for your dedicated OAuth app in your Google account if you also want to end its authorization. Do not revoke a client used by other applications unintentionally.

## Known limitations

- This integration reads completed, synced car data. It does not provide live streaming, remote controls or a car-side sync trigger.
- The built-in Google Drive backup integration cannot read arbitrary AAOS log files. Install **AAOS Logging Drive** to read the vehicle export; both integrations can exist separately. See the built-in integration's [known limitations](https://www.home-assistant.io/integrations/google_drive/#known-limitations).
- Only fields actually exported by the logger are available. Vehicle hardware, AAOS permissions and manufacturer support determine which contain readings.
- Native historical import supplies hourly numeric statistics. Supported helpers do not backdate all raw entity states; the bundled trip dashboard retains the individual samples.
- Historical enums retain original numeric codes. The integration does not infer manufacturer-specific meanings or manufacture missing values.
- Raw history uses local disk space independently of Recorder's ordinary retention. Include `/config/.storage/aaos_drive_<config-entry-id>_history.sqlite` in backups along with your normal Home Assistant configuration. Keep `.storage` intact during upgrades.
- Changed source archives are reimported. Source trip deletions are applied only after a complete replacement generation is validated. Metadata revisions before your first imported export cannot be reconstructed from that export alone.
- Import limits are 128 MiB per artifact/decoded member and 512 MiB total uncompressed content per trip archive. Oversized or unsupported exports are rejected rather than partially displayed.

## Troubleshooting

| Symptom | What to check or do |
| --- | --- |
| AAOS Logging Drive does not appear in Add integration | Check the exact `/config/custom_components/aaos_drive/manifest.json` path, copy the whole folder, restart Home Assistant and refresh the browser. Inspect **Settings → System → Logs** for import errors. |
| `redirect_uri_mismatch` | Confirm the OAuth client is Web application and its authorized redirect exactly matches the URI Home Assistant uses. Check the selected client/project and allow time for Google configuration changes to take effect. |
| Google denies access in Testing | Add the signing-in account under Test users. A managed Workspace account may need administrator approval. |
| Authorization stops after about seven days | Check the External app's publishing status. Testing authorizations expire after seven days; set the intended status and reconnect. |
| A read-only grant is required | Use a dedicated client and only `drive.readonly` for Drive access. Revoke that dedicated app's old wider grant before authorizing it again. |
| Google did not return a refresh token | Revoke consent for the dedicated application and sign in again through Home Assistant. The integration needs offline access to refresh its token. |
| The folder does not contain a supported snapshot | Select the car folder containing `Sync/V3`, not Backup or an exported ZIP. Complete a car-side V3 sync and check that the commit's referenced artifacts are present. |
| Unable to read Google Drive / cannot connect | Check Drive API is enabled in the selected project, network connectivity, the signing-in account and download permissions on the chosen folder. |
| Vehicle dataset already configured | Use the existing entry. A second entry for the same vehicle/dataset is prevented. |
| Wrong dataset when reconnecting | Reauthorize the account that can access the original vehicle folder. Reauthentication must restore the same vehicle/dataset. |
| Sensor is unknown or hidden | In the trip dashboard or full-trip action, inspect whether the field has real values. `null` stays unknown; no-data fields default to hidden. Check AAOS app permissions/support if the car never supplies the field. |
| Speed History is empty despite recorded trips | Select the actual speed entity and recorded dates; restart after upgrading, press Refresh Drive data and refresh the History page. Check Logs for `AAOS statistics import failed`. Compare with the raw trip dashboard. Do not delete configuration or history to force a reimport. |
| Native graph is empty for a boolean, enum or unitless counter | Use AAOS history for those original samples. Native imported statistics apply to recognized numeric measurement units. |
| Data looks old, even after pressing Refresh | Compare `recorded_at_unix_ms` with the current time. A successful Drive check does not create new car readings. Complete a new trip and car-side sync. |
| Sidebar or card reports unauthorized | Use a Home Assistant administrator account; the full-history API is restricted to administrators. |
| Custom card is not found or an old interface remains | Check the resource URL and JavaScript module type, then refresh the browser. After an upgrade, update its version query to match the installed package. |
| A history query says history changed | A new generation arrived while you were paging. Reload/reselect the vehicle and restart the query or CSV export. |
| Google credentials are incorrect | Check or remove unused credentials through Home Assistant's [Application Credentials](https://www.home-assistant.io/integrations/application_credentials/) screen, then reconnect with the correct dedicated client. |

When reporting a problem, include the integration/Home Assistant versions, the affected field and dates, and the relevant log message. Exclude OAuth secrets/tokens and consider removing identifying trip locations from shared logs or exports.

## Related topics and links

- [Attribute and data reference](ATTRIBUTES.md): measurements, enum interpretation, metadata, history and actions.
- [Home Assistant Google Drive guide](https://www.home-assistant.io/integrations/google_drive/): the reference page used for this guide's organization.
- [Home Assistant Application Credentials](https://www.home-assistant.io/integrations/application_credentials/): managing client credentials and account linking.
- [My Home Assistant](https://www.home-assistant.io/integrations/my/): account-link redirects and instance URL selection.
- [Google OAuth consent configuration](https://developers.google.com/workspace/guides/configure-oauth-consent): consent-screen setup.
- [Google Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth): what read-only access permits.
- [Google personal-use verification exception](https://support.google.com/cloud/answer/13464323?hl=en): personal OAuth app rules.

Google and Home Assistant can change console labels and screens. Use the linked official instructions if a label differs. Integration-specific steps and defaults in this guide match version 0.4.1.
