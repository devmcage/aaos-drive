"""Small HA API doubles for adapter behavior tests, not a full HA runtime."""

import sys
import types


def module(name, **attrs):
    result = types.ModuleType(name)
    result.__path__ = []
    result.__dict__.update(attrs)
    sys.modules[name] = result
    return result


class Entity:
    pass


class CoordinatorEntity(Entity):
    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success


class Flow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


class HomeAssistantError(Exception):
    pass


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator:
    def __init__(self, hass, logger, **kwargs):
        self.hass = hass
        self.config_entry = kwargs.get("config_entry")


module("homeassistant")
module("homeassistant.components")
module("homeassistant.helpers")
module("homeassistant.helpers.config_validation", config_entry_only_config_schema=lambda domain: {"domain": domain})
module("homeassistant.components.sensor", SensorEntity=type("SensorEntity", (Entity,), {}))
module("homeassistant.components.binary_sensor", BinarySensorEntity=type("BinarySensorEntity", (Entity,), {}))
module("homeassistant.components.button", ButtonEntity=type("ButtonEntity", (Entity,), {}))
module("homeassistant.components.device_tracker", TrackerEntity=type("TrackerEntity", (Entity,), {}), SourceType=types.SimpleNamespace(GPS="gps"))
module("homeassistant.core", callback=lambda fn: fn, SupportsResponse=types.SimpleNamespace(ONLY="only"), CoreState=types.SimpleNamespace(running="running", starting="starting"))
module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError, ConfigEntryAuthFailed=HomeAssistantError, ServiceValidationError=HomeAssistantError)
module("homeassistant.helpers.entity", DeviceInfo=lambda **kwargs: kwargs)
module("homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity, DataUpdateCoordinator=DataUpdateCoordinator, UpdateFailed=UpdateFailed)
module("homeassistant.config_entries", SOURCE_REAUTH="reauth", OptionsFlow=Flow)
module("homeassistant.helpers.config_entry_oauth2_flow", AbstractOAuth2FlowHandler=Flow)
module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: hass.session)
