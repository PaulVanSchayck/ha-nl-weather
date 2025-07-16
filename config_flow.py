import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorType, TextSelectorConfig
from . import EDR

from .const import DOMAIN, CONF_EDR_API_TOKEN, CONF_MQTT_TOKEN
from .edr import TokenInvalid
from .notification_service import NotificationService

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_EDR_API_TOKEN, msg="EDR API Token"): TextSelector(
        TextSelectorConfig(type=TextSelectorType.TEXT)
    ),
    vol.Required(CONF_MQTT_TOKEN, msg="Notification Service (MQTT) Token"): TextSelector(
        TextSelectorConfig(type=TextSelectorType.TEXT)
    ),
})


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.
    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    # Validate the data can be used to set up a connection.

    if len(data[CONF_MQTT_TOKEN]) < 15:
        # TODO: Try base64 decode
        raise InvalidTokenMQTT

    ns = NotificationService(data[CONF_MQTT_TOKEN])

    result = await ns.test_connection()
    if not result:
        raise CannotConnectMQTT

    if len(data[CONF_EDR_API_TOKEN]) < 15:
        # TODO: Try base64 decode
        raise InvalidTokenEDR

    edr = EDR(async_get_clientsession(hass), data[CONF_EDR_API_TOKEN])

    try:
        await edr.metadata()
    except TokenInvalid:
        raise CannotConnectEDR

    return {"title": "knmi_direct"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_PUSH

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""

        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnectEDR:
                errors[CONF_EDR_API_TOKEN] = "cannot_connect"
            except InvalidTokenEDR:
                errors[CONF_EDR_API_TOKEN] = "invalid"
            except CannotConnectMQTT:
                errors[CONF_MQTT_TOKEN] = "cannot_connect"
            except InvalidTokenMQTT:
                errors[CONF_MQTT_TOKEN] = "invalid"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


class CannotConnectEDR(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidTokenEDR(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid token."""

class CannotConnectMQTT(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidTokenMQTT(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid token."""