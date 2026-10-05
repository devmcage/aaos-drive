"""Native OAuth account linking followed by selection of one logger car folder."""

import logging

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DriveAuthError, DriveError, ReadOnlyDrive, folder_id
from .const import DEFAULT_SCAN_MINUTES, DEFAULT_STALE_HOURS, DOMAIN, READ_SCOPE, readonly_grant
from .model import InvalidExport
from .repository import DriveRepository


class OAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    DOMAIN = DOMAIN
    VERSION = 1
    _oauth_data = None

    @property
    def logger(self):
        return logging.getLogger(__name__)

    @property
    def extra_authorize_data(self):
        return {"scope": READ_SCOPE, "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false"}

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data):
        if not readonly_grant(data["token"]):
            return self.async_abort(reason="readonly_required")
        if not data["token"].get("refresh_token"):
            return self.async_abort(reason="refresh_token_required")
        self._oauth_data = data
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            try:
                snapshot = await self._repository(entry.data["folder_id"]).refresh()
                if snapshot.manifest.raw["datasetId"] != entry.data["dataset_id"] or snapshot.manifest.raw["vehicleId"] != entry.data["vehicle_id"]:
                    return self.async_abort(reason="wrong_dataset")
            except (DriveError, InvalidExport, aiohttp.ClientError, TimeoutError):
                return self.async_abort(reason="cannot_read_folder")
            return self.async_update_reload_and_abort(entry, data_updates=data)
        return await self.async_step_folder()

    def _repository(self, selected_folder):
        async def token():
            return self._oauth_data["token"]["access_token"]
        return DriveRepository(ReadOnlyDrive(async_get_clientsession(self.hass), token), selected_folder, self.hass.async_add_executor_job)

    async def async_step_folder(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                selected = folder_id(user_input["folder_id"])
                snapshot = await self._repository(selected).refresh()
                await self.async_set_unique_id(f"{snapshot.manifest.raw['vehicleId']}:{snapshot.manifest.raw['datasetId']}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=snapshot.catalog.get("carName") or "AAOS Logging vehicle",
                    data={**self._oauth_data, "folder_id": selected, "dataset_id": snapshot.manifest.raw["datasetId"], "vehicle_id": snapshot.manifest.raw["vehicleId"]},
                )
            except DriveAuthError:
                errors["base"] = "invalid_auth"
            except InvalidExport as err:
                self.logger.warning("AAOS export validation failed: %s", err)
                errors["base"] = "invalid_export"
            except (DriveError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="folder", data_schema=vol.Schema({vol.Required("folder_id"): str}), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AAOSOptionsFlow()


class AAOSOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required("scan_minutes", default=self.config_entry.options.get("scan_minutes", DEFAULT_SCAN_MINUTES)): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
            vol.Required("stale_hours", default=self.config_entry.options.get("stale_hours", DEFAULT_STALE_HOURS)): vol.All(vol.Coerce(int), vol.Range(min=1, max=8760)),
        }))
