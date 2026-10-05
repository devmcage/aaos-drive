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

    async def async_press(self):
        await self.coordinator.async_refresh()
        if not self.coordinator.last_update_success:
            raise HomeAssistantError("AAOS Drive refresh failed; the last validated snapshot was retained")
