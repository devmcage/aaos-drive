"""Publish recorded hours under owned sensor IDs and stable external IDs."""

from datetime import datetime, timezone
import asyncio
import hashlib
import json

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_add_external_statistics, async_import_statistics
from homeassistant.helpers import entity_registry as er

from .history import statistic_id
from .const import DOMAIN
from .measurements import car_sensor, series_info


def native_statistic_ids(hass, entry):
    """Resolve the actual (possibly renamed) sensor IDs owned by this vehicle."""
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}:"
    result = {}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform != DOMAIN or entity.domain != "sensor" or not entity.unique_id.startswith(prefix):
            continue
        field = entity.unique_id[len(prefix):]
        info = series_info(field)
        if car_sensor(field) and info["statistic_unit"] and not info["categorical"] and not info["timestamp_value"]:
            result[field] = entity.entity_id
    return result


def native_hour_cutoff():
    """Allow Recorder's hourly compiler to finish before replacing a recorded hour."""
    return int(datetime.now(timezone.utc).timestamp() // 3600) * 3600000 - 2 * 3600000


async def sync_statistics(hass, entry, history):
    state = await hass.async_add_executor_job(history.state)
    old = await hass.async_add_executor_job(history.statistics_state)
    native_ids = native_statistic_ids(hass, entry)
    cutoff = native_hour_cutoff()
    # Entity setup/renames can happen after the Drive generation was imported.
    # Reconcile IDs even for an unchanged generation and a completed old import.
    mapping_changed = any(old.get(field, {}).get("native_statistic_id") != native_ids.get(field)
                          for field in old.keys() | native_ids.keys())
    newly_completed = any(native_ids.get(field) and
                          {hour for hour in previous.get("hours", []) if hour <= cutoff} - set(previous.get("native_hours", []))
                          for field, previous in old.items())
    if not state["statistics_pending"] and not mapping_changed and not newly_completed:
        return
    series = await hass.async_add_executor_job(history.hourly)
    applied = {}
    recorder = get_instance(hass)
    for field in sorted(series.keys() | old.keys() | native_ids.keys()):
        rows = series.get(field, [])
        hours = [row["time"] for row in rows]
        digest = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
        native_id = native_ids.get(field)
        native_rows = [row for row in rows if row["time"] <= cutoff] if native_id else []
        native_digest = hashlib.sha256(json.dumps(native_rows, separators=(",", ":")).encode()).hexdigest() if native_id else None
        native_hours = [row["time"] for row in native_rows]
        applied[field] = {"digest": digest, "hours": hours, "native_statistic_id": native_id,
                          "native_digest": native_digest, "native_hours": native_hours}
        previous = old.get(field, {})
        if previous == applied[field]:
            continue
        identifier = statistic_id(entry.entry_id, field)
        changed_values = previous.get("digest") != digest or previous.get("hours") != hours
        removed_hours = set(previous.get("hours", [])) - set(hours)
        # Correct deletions as well as additions; every native ID comes from
        # this config entry's owned registry records, never from saved untrusted IDs.
        if removed_hours:
            recorder.async_clear_statistics([identifier])
        if native_id and set(previous.get("native_hours", [])) - set(native_hours):
            recorder.async_clear_statistics([native_id])
        if not rows:
            continue
        info = series_info(field)
        metadata = {"statistic_id": identifier, "source": "aaos_drive",
                    "name": f"{entry.title}: {info['name']}", "has_sum": False,
                    "mean_type": StatisticMeanType.ARITHMETIC, "unit_class": None,
                    "unit_of_measurement": info["statistic_unit"]}
        for offset in range(0, len(rows), 1000):
            statistics = [{"start": datetime.fromtimestamp(row["time"]/1000, timezone.utc),
                           "mean": row["mean"], "min": row["min"], "max": row["max"]}
                          for row in rows[offset:offset+1000]]
            if changed_values:
                async_add_external_statistics(hass, metadata, statistics)
        if native_id and (native_digest != previous.get("native_digest") or previous.get("native_statistic_id") != native_id):
            native_metadata = {**metadata, "statistic_id": native_id, "source": "recorder", "name": None}
            for offset in range(0, len(native_rows), 1000):
                statistics = [{"start": datetime.fromtimestamp(row["time"]/1000, timezone.utc),
                               "mean": row["mean"], "min": row["min"], "max": row["max"]}
                              for row in native_rows[offset:offset+1000]]
                # Public Recorder helper validates the owned entity ID and UTC hour.
                async_import_statistics(hass, native_metadata, statistics)
    # This is called only after HA starts; the recorder waits for startup to process jobs.
    async with asyncio.timeout(60):
        await recorder.async_block_till_done()
    await hass.async_add_executor_job(history.statistics_done, applied)
