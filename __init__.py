"""The KNMI Direct integration."""

from dataclasses import dataclass

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession, async_create_clientsession
import logging

from .app import App
from .const import CONF_MQTT_TOKEN, CONF_EDR_API_TOKEN, CONF_WMS_TOKEN
from .notification_service import NotificationService
from .edr import EDR
from .wms import WMS

_PLATFORMS: list[Platform] = [Platform.WEATHER, Platform.CAMERA]
_LOGGER = logging.getLogger(__name__)

@dataclass
class RuntimeData:
    """Class to hold your data."""
    notification_service: NotificationService
    wms: WMS
    edr: EDR
    app: App

type KNMIDirectConfigEntry = ConfigEntry[RuntimeData]  # noqa: F821

async def async_setup_entry(hass: HomeAssistant, entry: KNMIDirectConfigEntry) -> bool:
    """Set up KNMI Direct from a config entry."""
    _LOGGER.debug("async_setup_entry")

    ns = NotificationService(entry.data[CONF_MQTT_TOKEN])
    entry.async_create_background_task(hass, ns.run(), "NotificationService")

    session = async_get_clientsession(hass)

    entry.runtime_data = RuntimeData(
        notification_service= ns,
        edr=EDR(session, entry.data[CONF_EDR_API_TOKEN]),
        wms=WMS(session, entry.data[CONF_WMS_TOKEN]),
        app=App(session)
    )

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True



async def async_unload_entry(hass: HomeAssistant, entry: KNMIDirectConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)

    return unload_ok