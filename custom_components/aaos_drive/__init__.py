"""AAOS Logging's read-only Google Drive importer."""

import aiohttp
import sqlite3
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session, async_get_config_entry_implementation
from homeassistant.helpers.storage import Store
from homeassistant.helpers.start import async_at_started

from .api import DriveAuthError, DriveError, ReadOnlyDrive
from .const import DOMAIN, readonly_grant
from .coordinator import AAOSCoordinator
from .model import InvalidExport
from .repository import DriveRepository
from .history import HistoryStore

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.DEVICE_TRACKER]


async def async_setup(hass, config):
    from .frontend import async_setup_frontend
    await async_setup_frontend(hass)
    async def handle_read(call):
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if entry is None or entry.domain != DOMAIN or entry.state != ConfigEntryState.LOADED or not getattr(entry, "runtime_data", None):
            raise ServiceValidationError("Select a loaded AAOS Logging Drive integration")
        coordinator = entry.runtime_data
        if call.service in {"get_history", "get_history_fields", "get_trip", "list_trips"}:
            async with coordinator.lock:
                try:
                    if call.service == "get_history_fields":
                        return await hass.async_add_executor_job(coordinator.history.overview)
                    if call.service == "get_trip":
                        trip = await hass.async_add_executor_job(coordinator.history.trip, call.data.get("trip_id", ""))
                        state = await hass.async_add_executor_job(coordinator.history.state)
                        return {"generation_id": state["generation_id"], "trip": trip}
                    if call.service == "list_trips":
                        trips = await hass.async_add_executor_job(coordinator.history.summaries, call.data.get("period", ""))
                        state = await hass.async_add_executor_job(coordinator.history.state)
                        return {"generation_id": state["generation_id"], "trips": trips}
                    return await hass.async_add_executor_job(coordinator.history.points,
                        call.data["field"], call.data.get("start"), call.data.get("end"),
                        call.data["limit"], call.data.get("cursor"), call.data.get("trip_id"))
                except (InvalidExport, OSError, sqlite3.Error) as err:
                    raise ServiceValidationError(str(err)) from err
        if not coordinator.last_update_success or coordinator.data is None:
            raise HomeAssistantError("Refresh the AAOS Logging Drive integration successfully first")
        try:
            async with coordinator.lock:
                if not coordinator.last_update_success:
                    raise HomeAssistantError("Refresh the AAOS Logging Drive integration successfully first")
                snapshot = coordinator.data
                if call.service == "get_catalog":
                    return {"manifest": snapshot.manifest.raw, "catalog": snapshot.catalog}
                if call.service == "get_index":
                    index = await coordinator.repository.index(snapshot, call.data["logical_key"])
                    return {"generation_id": snapshot.manifest.raw["generationId"], "index": index}
        except DriveAuthError as err:
            entry.async_start_reauth(hass)
            raise HomeAssistantError(str(err)) from err
        except (InvalidExport, DriveError, aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err

    base = {vol.Required("config_entry_id"): str}
    history_fields = {vol.Required("field"): str, vol.Optional("start"): vol.All(int, vol.Range(min=0)),
                      vol.Optional("end"): vol.All(int, vol.Range(min=0)),
                      vol.Optional("limit", default=2000): vol.All(int, vol.Range(min=1, max=10000)),
                      vol.Optional("cursor"): dict, vol.Optional("trip_id"): str}
    for action, extra in (("get_catalog", {}), ("get_trip", {vol.Optional("trip_id", default=""): str}), ("list_trips", {vol.Optional("period", default=""): str}), ("get_index", {vol.Required("logical_key"): str}), ("get_history", history_fields), ("get_history_fields", {})):
        hass.services.async_register(DOMAIN, action, handle_read, schema=vol.Schema({**base, **extra}), supports_response=SupportsResponse.ONLY)
    return True


async def async_setup_entry(hass, entry):
    if not readonly_grant(entry.data["token"]):
        raise ConfigEntryAuthFailed("A dedicated read-only Google Drive grant is required")
    implementation = await async_get_config_entry_implementation(hass, entry)
    oauth = OAuth2Session(hass, entry, implementation)

    async def token():
        await oauth.async_ensure_token_valid()
        if not readonly_grant(oauth.token):
            raise DriveAuthError("The refreshed token does not have a read-only grant")
        return oauth.token["access_token"]

    repository = DriveRepository(
        ReadOnlyDrive(async_get_clientsession(hass), token), entry.data["folder_id"], hass.async_add_executor_job,
        {"datasetId": entry.data["dataset_id"], "vehicleId": entry.data["vehicle_id"]},
    )
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.head")
    repository.accepted_head = await store.async_load()
    history = HistoryStore(hass.config.path(".storage", f"{DOMAIN}_{entry.entry_id}_history.sqlite"))
    await hass.async_add_executor_job(history.initialize)
    coordinator = AAOSCoordinator(hass, entry, repository, store, history)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Resolve native statistic IDs only after platforms have registered their entities.
    entry.async_on_unload(async_at_started(hass, coordinator.async_statistics_after_start))
    options = dict(entry.options)

    async def options_updated(hass, changed_entry):
        if dict(changed_entry.options) != options:
            await hass.config_entries.async_reload(changed_entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(options_updated))
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass, entry):
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.head").async_remove()
    history = HistoryStore(hass.config.path(".storage", f"{DOMAIN}_{entry.entry_id}_history.sqlite"))
    if await hass.async_add_executor_job(history.path.exists):
        from homeassistant.components.recorder import get_instance
        from .history import statistic_id
        previous = await hass.async_add_executor_job(history.statistics_state)
        from .statistics import native_statistic_ids
        native = native_statistic_ids(hass, entry)
        identifiers = [statistic_id(entry.entry_id, field) for field in previous]
        identifiers.extend(native[field] for field in previous if field in native and previous[field].get("native_hours"))
        get_instance(hass).async_clear_statistics(identifiers)
    await hass.async_add_executor_job(history.remove)
