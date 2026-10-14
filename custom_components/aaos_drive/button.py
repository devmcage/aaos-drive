"""Manual refresh reads Drive; it never requests a car-side upload."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .entity import AAOSEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RefreshButton(entry.runtime_data)])


class RefreshButton(AAOSEntity, ButtonEntity):
    _attr_icon = "mdi:cloud-refresh"
    _attr_entity_category = "config"

    def __init__(self, coordinator):
        super().__init__(coordinator, "refresh", "Refresh Drive data")

    @property
    def available(self):
        # Keep retries possible when a previous import failed.
        return True

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        checked = self.coordinator.last_checked_at
        attrs.update(last_checked_at=checked.isoformat() if checked else None,
                     last_successful_sync=self.coordinator.data.checked_at.isoformat(),
                     latest_trip_at_unix_ms=self.coordinator.data.manifest.raw["latestTripEndTimestamp"],
                     source_trip_count=self.coordinator.data.manifest.raw["totalTripCount"],
                     generation_sequence=self.coordinator.data.manifest.raw["generationSequence"],
                     drive_folder_url=f"https://drive.google.com/drive/folders/{self.coordinator.entry.data['folder_id']}"
                         if self.coordinator.entry.data.get("folder_id") else None)
        return attrs

    async def async_press(self):
        await self.coordinator.async_refresh()
        if not self.coordinator.last_update_success:
            raise HomeAssistantError("AAOS Drive refresh failed; the last validated snapshot was retained")
