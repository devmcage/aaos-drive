"""Authenticated history API and bundled, local Home Assistant history panel."""

from pathlib import Path
import sqlite3

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .history import statistic_id
from .model import InvalidExport
from .measurements import car_sensor


def coordinator(hass, entry_id):
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state != ConfigEntryState.LOADED:
        raise HomeAssistantError("Select a loaded AAOS Logging Drive vehicle")
    return entry.runtime_data


@websocket_api.websocket_command({vol.Required("type"): "aaos_drive/history/vehicles"})
@websocket_api.require_admin
@websocket_api.async_response
async def vehicles(hass, connection, msg):
    result = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state == ConfigEntryState.LOADED:
            result.append({"id": entry.entry_id, "name": entry.title,
                           "drive_available": entry.runtime_data.last_update_success})
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): "aaos_drive/history/fields", vol.Required("config_entry_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def fields(hass, connection, msg):
    target = coordinator(hass, msg["config_entry_id"])
    async with target.lock:
        result = await hass.async_add_executor_job(target.history.overview)
        result["fields"] = [field for field in result["fields"] if car_sensor(field["field"])]
        from .statistics import native_statistic_ids
        native = native_statistic_ids(hass, target.entry)
        for field in result["fields"]:
            external = statistic_id(target.entry.entry_id, field["field"]) if field["statistic_unit"] and not field["timestamp_value"] and not field["categorical"] else None
            field["statistic_id"] = native.get(field["field"]) or external
            field["external_statistic_id"] = external
        result["drive_available"] = target.last_update_success
        result["statistics_error"] = target.statistics_error
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "aaos_drive/history/trips", vol.Required("config_entry_id"): str,
    vol.Optional("start"): vol.All(int, vol.Range(min=0)), vol.Optional("end"): vol.All(int, vol.Range(min=0)),
    vol.Optional("limit", default=200): vol.All(int, vol.Range(min=1, max=1000)), vol.Optional("cursor"): dict,
})
@websocket_api.require_admin
@websocket_api.async_response
async def trips(hass, connection, msg):
    target = coordinator(hass, msg["config_entry_id"])
    try:
        async with target.lock:
            result = await hass.async_add_executor_job(target.history.trip_index, msg.get("start"), msg.get("end"), msg["limit"], msg.get("cursor"))
        connection.send_result(msg["id"], result)
    except (InvalidExport, OSError, sqlite3.Error):
        connection.send_error(msg["id"], "history_query_failed", "History changed or trip query failed. Reload and try again.")


@websocket_api.websocket_command({
    vol.Required("type"): "aaos_drive/history/points", vol.Required("config_entry_id"): str,
    vol.Required("field"): str, vol.Optional("start"): vol.All(int, vol.Range(min=0)),
    vol.Optional("end"): vol.All(int, vol.Range(min=0)),
    vol.Optional("limit", default=2000): vol.All(int, vol.Range(min=1, max=10000)),
    vol.Optional("cursor"): dict,
    vol.Optional("trip_id"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def points(hass, connection, msg):
    target = coordinator(hass, msg["config_entry_id"])
    try:
        async with target.lock:
            result = await hass.async_add_executor_job(target.history.points, msg["field"],
                msg.get("start"), msg.get("end"), msg["limit"], msg.get("cursor"), msg.get("trip_id"))
        connection.send_result(msg["id"], result)
    except (InvalidExport, OSError, sqlite3.Error):
        connection.send_error(msg["id"], "history_query_failed", "History changed or query failed. Reload the vehicle and try again.")


async def async_setup_frontend(hass):
    for command in (vehicles, fields, trips, points):
        websocket_api.async_register_command(hass, command)
    await hass.http.async_register_static_paths([StaticPathConfig(
        "/aaos_drive/history.js", str(Path(__file__).parent / "www/history.js"), False)])
    await async_register_panel(hass, frontend_url_path="aaos-history", webcomponent_name="aaos-history-panel",
        sidebar_title="AAOS history", sidebar_icon="mdi:chart-timeline-variant",
        module_url="/aaos_drive/history.js?v=0.4.1", embed_iframe=False, require_admin=True)
