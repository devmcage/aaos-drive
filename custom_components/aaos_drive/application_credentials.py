"""Use Home Assistant's native application credentials and OAuth callback."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.helpers.config_entry_oauth2_flow import AUTH_CALLBACK_PATH, MY_AUTH_CALLBACK_PATH


async def async_get_authorization_server(hass):
    return AuthorizationServer("https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token")


async def async_get_description_placeholders(hass):
    redirect = MY_AUTH_CALLBACK_PATH if "my" in hass.config.components else f"{hass.config.external_url or 'https://YOUR_DOMAIN:PORT'}{AUTH_CALLBACK_PATH}"
    return {
        "oauth_consent_url": "https://console.cloud.google.com/auth/overview",
        "oauth_creds_url": "https://console.cloud.google.com/auth/clients",
        "more_info_url": "https://developers.google.com/workspace/drive/api/guides/api-specific-auth",
        "redirect_url": redirect,
    }
