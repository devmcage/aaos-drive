"""Expose every exported measurement; preserve unknown enum values and future fields."""

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback

from .const import BINARY_FIELDS
from .entity import AAOSEntity
from .model import finite, timestamp
from .measurements import TIMESTAMPS, car_sensor, label, measurement, series_info


def remove_legacy_entities(hass, entry):
    """Retire this integration's summary/metadata sensors on upgrade."""
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}:"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform == "aaos_drive" and entity.domain == "sensor" and entity.unique_id.startswith(prefix):
            key = entity.unique_id[len(prefix):]
            if key.startswith(("month.", "trip.", "vehicle.", "dataset.")) or not car_sensor(key) and key.startswith(("telemetry.", "weather.", "route.")):
                registry.async_remove(entity.entity_id)



async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    remove_legacy_entities(hass, entry)
    known = set()

    @callback
    def discover():
        keys = {key for key in coordinator.data.values() if car_sensor(key)}
        keys -= {f"telemetry.{key}" for key in BINARY_FIELDS}
        new = sorted(keys - known)
        known.update(new)
        async_add_entities([AAOSSensor(coordinator, key) for key in new])

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class AAOSSensor(AAOSEntity, SensorEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key, label(key))
        self.field = key.rsplit(".", 1)[-1]
        self._attr_native_unit_of_measurement, self._attr_device_class, self.factor = measurement(self.field)
        if key == "dataset.telemetryAgeSeconds":
            self._attr_native_unit_of_measurement, self._attr_device_class = "s", "duration"
        if key.startswith("vehicle.specifications.exteriorDimensionsMm."):
            self._attr_native_unit_of_measurement, self._attr_device_class = "mm", "distance"
        # Numeric sensor statistics are attached to this same entity ID. Recorder
        # may also record the latest received state after installation, as usual.
        info = series_info(key)
        self._attr_state_class = "measurement" if car_sensor(key) and info["statistic_unit"] and not info["categorical"] else None

    @property
    def native_value(self):
        snapshot = self.coordinator.data
        if self.key == "dataset.telemetryAgeSeconds":
            recorded = timestamp(snapshot.telemetry.get("recordedAt"))
            return max(0, (datetime.now(timezone.utc) - recorded).total_seconds()) if recorded else None
        value = snapshot.values().get(self.key)
        if self.field in TIMESTAMPS:
            return value if isinstance(value, datetime) else timestamp(value)
        if value is None:
            return None
        if self._attr_native_unit_of_measurement:
            return value * self.factor if finite(value) else None
        if isinstance(value, (list, dict)):
            return len(value)
        if type(value) in (int, float):
            return value if finite(value) else None
        return str(value)[:255]

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        value = self.coordinator.data.values().get(self.key)
        if isinstance(value, (list, dict)) or isinstance(value, str) and len(value) > 255 or self.factor != 1:
            attrs["raw_value"] = value
        if self.field.endswith("State") or self.field in {"currentGear", "gearSelection", "turnSignalState", "engineOilLevel", "regenerativeBrakingLevel", "evStoppingMode"} or self.field.startswith("seatOccupancy"):
            attrs["value_encoding"] = "raw AAOS vehicle property enum; no inferred translation"
        return attrs
