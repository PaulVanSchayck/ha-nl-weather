import binascii
import json
import logging
from base64 import b64decode
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorType, TextSelectorConfig
from . import EDR, WMS

from .const import DOMAIN, CONF_EDR_API_TOKEN, CONF_MQTT_TOKEN, CONF_WMS_TOKEN
from .edr import TokenInvalid
from .wms import TokenInvalid as WMSTokenInvalid # TODO: Fix this
from .notification_service import NotificationService, TokenInvalid as NSTokenInvalid

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_EDR_API_TOKEN, msg="EDR API Token"): TextSelector(
        TextSelectorConfig(type=TextSelectorType.TEXT)
    ),
    vol.Required(CONF_WMS_TOKEN, msg="Web Map Service (WMS) Token"): TextSelector(
        TextSelectorConfig(type=TextSelectorType.TEXT)
    ),
    vol.Required(CONF_MQTT_TOKEN, msg="Notification Service (MQTT) Token"): TextSelector(
        TextSelectorConfig(type=TextSelectorType.TEXT)
    ),
})

def validate_token(token):
    try:
        json.loads(b64decode(token, validate=True))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
        raise IncorrectToken


async def validate_edr_input(hass: HomeAssistant, data: dict):
    validate_token(data[CONF_EDR_API_TOKEN])
    edr = EDR(async_get_clientsession(hass), data[CONF_EDR_API_TOKEN])

    try:
        await edr.metadata()
    except TokenInvalid:
        raise CannotConnect


async def validate_wms_input(hass: HomeAssistant, data: dict):
    validate_token(data[CONF_WMS_TOKEN])
    wms = WMS(async_get_clientsession(hass), data[CONF_WMS_TOKEN])

    try:
        await wms.get({})
    except WMSTokenInvalid:
        raise CannotConnect


async def validate_mqtt_input(hass: HomeAssistant, data: dict):
    validate_token(data[CONF_MQTT_TOKEN])
    ns = NotificationService(data[CONF_MQTT_TOKEN])

    try:
        await ns.test_connection()
    except NSTokenInvalid:
        raise CannotConnect

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_PUSH

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""

        errors = {}
        if user_input is not None:
            try:
                await validate_edr_input(self.hass, user_input)
            except CannotConnect:
                errors[CONF_EDR_API_TOKEN] = "cannot_connect"
            except IncorrectToken:
                errors[CONF_EDR_API_TOKEN] = "invalid"

            try:
                await validate_wms_input(self.hass, user_input)
            except CannotConnect:
                errors[CONF_WMS_TOKEN] = "cannot_connect"
            except IncorrectToken:
                errors[CONF_WMS_TOKEN] = "invalid"

            try:
                await validate_mqtt_input(self.hass, user_input)
            except CannotConnect:
                errors[CONF_MQTT_TOKEN] = "cannot_connect"
            except IncorrectToken:
                errors[CONF_MQTT_TOKEN] = "invalid"

        if not errors and user_input is not None:
            return self.async_create_entry(title="NL Weather at Home", data=user_input)
        else:
            return self.async_show_form(
                step_id="user", data_schema=DATA_SCHEMA, errors=errors
            )


class IncorrectToken(HomeAssistantError):
    """Error to indicate the token is not a valid base64 encoded string."""

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

