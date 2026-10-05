"""Last logged trip position, with a recorded timestamp; this is not live GPS."""

from homeassistant.components.device_tracker import SourceType, TrackerEntity

from .entity import AAOSEntity
from .model import finite


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([LoggedPosition(entry.runtime_data)])


class LoggedPosition(AAOSEntity, TrackerEntity):
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator):
        super().__init__(coordinator, "position", "Last logged position")

    @property
    def point(self):
        trip = self.coordinator.data.trip or {}
        route = trip.get("route", [])
        if route:
            return max(route, key=lambda p: p["recordedAt"])
        return {"latitude": trip.get("endLat"), "longitude": trip.get("endLon"), "recordedAt": trip.get("endedAt")}

    @property
    def available(self):
        lat, lon = self.point.get("latitude"), self.point.get("longitude")
        return super().available and finite(lat) and -90 <= lat <= 90 and finite(lon) and -180 <= lon <= 180

    @property
    def latitude(self):
        return self.point.get("latitude")

    @property
    def longitude(self):
        return self.point.get("longitude")

    @property
    def extra_state_attributes(self):
        return {**super().extra_state_attributes, "recorded_at_unix_ms": self.point.get("recordedAt"), "location_source": "last synced trip"}
