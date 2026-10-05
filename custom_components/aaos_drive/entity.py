"""Shared device identity for all exported readings."""

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import callback

from .const import DOMAIN
from .history import statistic_id
from .measurements import car_sensor, series_info


class AAOSEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, name):
        super().__init__(coordinator)
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.unique_id}:{key}"

    def _has_recorded_value(self):
        recorded = getattr(self.coordinator, "fields_with_data", None)
        if recorded is not None:
            return self.key in recorded
        # Also support a coordinator without the local history store.
        value = getattr(self, "native_value", None)
        if value is None:
            value = getattr(self, "is_on", None)
        return value is not None and value not in ("unknown", "unavailable")

    @property
    def entity_registry_visible_default(self):
        return not car_sensor(self.key) or self._has_recorded_value()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._sync_visibility()

    @callback
    def _handle_coordinator_update(self):
        self._sync_visibility()
        super()._handle_coordinator_update()

    @callback
    def _sync_visibility(self):
        """Apply the empty-field default once; preserve later user choices."""
        if not car_sensor(self.key):
            return
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(self.hass)
        record = registry.async_get(self.entity_id)
        if record is None or record.platform != DOMAIN or record.domain not in {"sensor", "binary_sensor"} \
                or record.unique_id != self._attr_unique_id or record.config_entry_id != self.coordinator.entry.entry_id:
            return
        options = dict(record.options.get(DOMAIN, {}))
        initialized = options.get("initial_visibility_applied", False)
        if self._has_recorded_value():
            if record.hidden_by == er.RegistryEntryHider.INTEGRATION:
                registry.async_update_entity(record.entity_id, hidden_by=None)
        elif not initialized and record.hidden_by is None:
            registry.async_update_entity(record.entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION)
        if not initialized:
            registry.async_update_entity_options(record.entity_id, DOMAIN,
                {**options, "initial_visibility_applied": True})

    @property
    def device_info(self):
        catalog = self.coordinator.data.catalog
        identity = catalog.get("vehicle", {}).get("identity", {})
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.unique_id)},
            name=catalog.get("carName") or self.coordinator.entry.title,
            manufacturer=identity.get("make") or "AAOS Logging",
            model=identity.get("model"),
            sw_version=f"Drive V3 / trip schema {self.coordinator.data.manifest.raw['tripSchemaVersion']}",
        )

    @property
    def extra_state_attributes(self):
        snapshot = self.coordinator.data
        group, _, field = self.key.partition(".")
        recorded = snapshot.telemetry.get("recordedAt") if group == "telemetry" else snapshot.weather.get("capturedAt") if group == "weather" else snapshot.route.get("recordedAt") if group == "route" else (snapshot.trip or {}).get("endedAt") if group == "trip" else snapshot.manifest.raw["generatedAt"]
        info = series_info(self.key)
        attrs = {
            "export_field": self.key,
            "history_field": self.key,
            "history_view": "/aaos-history",
            "historical_statistic_id": getattr(self, "entity_id", None) or statistic_id(self.coordinator.entry.entry_id, self.key)
                if getattr(self.coordinator.entry, "entry_id", None) and info["statistic_unit"]
                and not info["timestamp_value"] and not info["categorical"] and car_sensor(self.key) else None,
            "external_historical_statistic_id": statistic_id(self.coordinator.entry.entry_id, self.key)
                if getattr(self.coordinator.entry, "entry_id", None) and info["statistic_unit"]
                and not info["timestamp_value"] and not info["categorical"] and group in {"trip", "telemetry", "weather", "route"} else None,
            "recorded_at_unix_ms": recorded,
            "generation_id": snapshot.manifest.raw["generationId"],
            "trip_id": (snapshot.trip or {}).get("tripId") if group in {"trip", "telemetry", "weather", "route"} else None,
            "data_source": "AAOS Logging Google Drive snapshot",
        }
        if group == "telemetry":
            attrs["power_source"] = snapshot.telemetry.get("powerSource")
        return attrs
