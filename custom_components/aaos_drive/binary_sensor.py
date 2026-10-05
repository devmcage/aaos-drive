"""Nullable booleans retain unknown rather than becoming false."""

from datetime import datetime, timezone

from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import BINARY_FIELDS, DEFAULT_STALE_HOURS
from .entity import AAOSEntity
from .model import timestamp
from .sensor import label


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([AAOSBinarySensor(coordinator, f"telemetry.{field}", label(f"telemetry.{field}")) for field in sorted(BINARY_FIELDS)] + [StaleSensor(coordinator)])


class AAOSBinarySensor(AAOSEntity, BinarySensorEntity):
    @property
    def is_on(self):
        value = self.coordinator.data.values().get(self.key)
        return value if type(value) is bool else None


class StaleSensor(AAOSEntity, BinarySensorEntity):
    _attr_device_class = "problem"
    _attr_entity_category = "diagnostic"

    def __init__(self, coordinator):
        super().__init__(coordinator, "dataset.stale", "Logged telemetry stale")

    @property
    def is_on(self):
        recorded = timestamp(self.coordinator.data.telemetry.get("recordedAt"))
        limit = self.coordinator.entry.options.get("stale_hours", DEFAULT_STALE_HOURS)
        return recorded is None or (datetime.now(timezone.utc) - recorded).total_seconds() > limit * 3600
