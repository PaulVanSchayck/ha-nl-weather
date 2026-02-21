import binascii
import json
import logging
from base64 import b64decode
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MODE,
    CONF_NAME,
    CONF_REGION,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    selector,
)

from . import EDR, WMS
from .const import (
    ALERT_REGIONS,
    CONF_EDR_API_TOKEN,
    CONF_MARK_LOCATIONS,
    CONF_MQTT_TOKEN,
    CONF_RADAR_STYLE,
    CONF_STATION,
    CONF_WMS_TOKEN,
    DEFAULT_RADAR_STYLE,
    DOMAIN,
    RADAR_STYLES,
    StationMode,
)
from .KNMI.edr import TokenInvalid
from .KNMI.notification_service import (
    NotificationService,
)

# TODO: Unify KNMI API exceptions to common shared exceptions
from .KNMI.notification_service import (
    TokenInvalid as NSTokenInvalid,
)
from .KNMI.wms import TokenInvalid as WMSTokenInvalid

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EDR_API_TOKEN, msg="EDR API Token"): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_WMS_TOKEN, msg="Web Map Service (WMS) Token"): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(
            CONF_MQTT_TOKEN, msg="Notification Service (MQTT) Token"
        ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RADAR_STYLE, default=DEFAULT_RADAR_STYLE): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=key, label=key)
                    for key in RADAR_STYLES.keys()
                ],
                translation_key="radar_style",
            ),
        ),
        vol.Required(CONF_MARK_LOCATIONS, default=True): BooleanSelector(),
    }
)


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


class OptionsFlowHandler(OptionsFlowWithReload):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_PUSH
    _config = None

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
            self._config = user_input
            return await self.async_step_finish()
        else:
            return self.async_show_form(
                step_id="user",
                data_schema=DATA_SCHEMA,
                errors=errors,
                description_placeholders={
                    "kdp_url": "https://developer.dataplatform.knmi.nl/"
                },
            )

    async def async_step_finish(self, user_input=None):
        """Final step just to show instructions."""
        if user_input is not None:
            return self.async_create_entry(
                title="NL Weather",
                data=self._config,
            )

        return self.async_show_form(step_id="finish", data_schema=vol.Schema({}))

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {
            "location": LocationSubentryFlowHandler,
            "station": StationSubentryFlowHandler,
        }

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlowHandler:
        """Create the options flow."""
        return OptionsFlowHandler()


class StationSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for adding and modifying a station."""

    async def async_step_user(self, user_input=None):
        """User flow to add a new station."""
        if user_input is not None:
            if user_input[CONF_MODE] == StationMode.AUTO:
                return await self.async_step_auto()
            else:
                return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_MODE): vol.In([m.value for m in StationMode])}
            ),
        )

    async def async_step_manual(self, user_input=None):
        session = async_get_clientsession(self.hass)
        edr = EDR(session, self._get_entry().data[CONF_EDR_API_TOKEN])
        locations = await edr.locations()

        stations = {
            f["id"]: f"{f['properties']['name']}" for f in locations["features"]
        }
        options = sorted(
            [
                {
                    "value": f["id"],
                    "label": f"{f['properties']['name']} - {f['properties']['type']}",
                }
                for f in locations["features"]
            ],
            key=lambda o: o["label"],
        )

        if user_input is not None:
            user_input[CONF_MODE] = StationMode.MANUAL
            title = stations[user_input[CONF_STATION]]
            user_input[CONF_NAME] = title
            return self.async_create_entry(data=user_input, title=title)

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STATION): selector(
                        {
                            "select": {
                                "options": options,
                                "mode": "dropdown",
                            }
                        }
                    ),
                }
            ),
        )

    async def async_step_auto(self, user_input=None):
        if user_input is not None:
            user_input[CONF_MODE] = StationMode.AUTO
            return self.async_create_entry(data=user_input, title=user_input[CONF_NAME])

        return self.async_show_form(
            step_id="auto",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self.hass.config.location_name
                    ): str,
                    vol.Required(
                        CONF_LATITUDE, default=self.hass.config.latitude
                    ): cv.latitude,
                    vol.Required(
                        CONF_LONGITUDE, default=self.hass.config.longitude
                    ): cv.longitude,
                }
            ),
        )


class LocationSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for adding and modifying a location."""

    async def async_step_user(self, user_input=None):
        return await self.async_step_location(user_input)

    async def async_step_location(self, user_input=None):
        """User flow to add a new location."""
        if user_input is not None:
            return self.async_create_entry(data=user_input, title=user_input[CONF_NAME])

        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self.hass.config.location_name
                    ): str,
                    # TODO: Should not fall outside WMS bbox
                    vol.Required(
                        CONF_LATITUDE, default=self.hass.config.latitude
                    ): cv.latitude,
                    vol.Required(
                        CONF_LONGITUDE, default=self.hass.config.longitude
                    ): cv.longitude,
                    # TODO: Find region based on location
                    vol.Required(CONF_REGION): selector(
                        {
                            "select": {
                                "options": [
                                    {"value": k, "label": v}
                                    for k, v in ALERT_REGIONS.items()
                                ],
                                "mode": "dropdown",
                            }
                        }
                    ),
                }
            ),
        )


class IncorrectToken(HomeAssistantError):
    """Error to indicate the token is not a valid base64 encoded string."""


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
