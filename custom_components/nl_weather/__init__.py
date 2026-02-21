"""The NL Weather integration."""

import asyncio
from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MODE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .KNMI.app import App
from .KNMI.edr import EDR
from .KNMI.notification_service import NotificationService
from .KNMI.wms import WMS
from .const import (
    CONF_MQTT_TOKEN,
    CONF_EDR_API_TOKEN,
    CONF_WMS_TOKEN,
    DOMAIN as DOMAIN,
    StationMode,
)
from .coordinator import (
    NLWeatherAutoEDRCoordinator,
    NLWeatherManualEDRCoordinator,
    NLWeatherUpdateCoordinator,
    NLWeatherEDRCoordinator,
)

_PLATFORMS: list[Platform] = [
    Platform.WEATHER,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]
_LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeData:
    notification_service: NotificationService
    wms: WMS
    app: App
    edr: EDR
    app_coordinators: dict[str, NLWeatherUpdateCoordinator]
    edr_coordinators: dict[str, NLWeatherEDRCoordinator]


type KNMIDirectConfigEntry = ConfigEntry[RuntimeData]  # noqa: F821


async def async_setup_entry(hass: HomeAssistant, entry: KNMIDirectConfigEntry) -> bool:
    """Set up from a config entry."""
    _LOGGER.debug("async_setup_entry")

    session = async_get_clientsession(hass)
    ns = NotificationService(entry.data[CONF_MQTT_TOKEN])
    edr = EDR(session, entry.data[CONF_EDR_API_TOKEN])
    entry.async_create_background_task(hass, ns.run(), "NotificationService")

    entry.runtime_data = RuntimeData(
        notification_service=ns,
        wms=WMS(session, entry.data[CONF_WMS_TOKEN]),
        app=App(session),
        edr=edr,
        app_coordinators={},
        edr_coordinators={},
    )

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == "location":
            entry.runtime_data.app_coordinators[subentry_id] = (
                NLWeatherUpdateCoordinator(hass, entry, subentry)
            )
        elif subentry.subentry_type == "station":
            if subentry.data[CONF_MODE] == StationMode.AUTO:
                entry.runtime_data.edr_coordinators[subentry_id] = (
                    NLWeatherAutoEDRCoordinator(hass, subentry, ns, edr)
                )
            elif subentry.data[CONF_MODE] == StationMode.MANUAL:
                entry.runtime_data.edr_coordinators[subentry_id] = (
                    NLWeatherManualEDRCoordinator(hass, subentry, ns, edr)
                )

    await asyncio.gather(
        *[
            c.async_config_entry_first_refresh()
            for c in entry.runtime_data.app_coordinators.values()
        ],
        *[
            c.async_config_entry_first_refresh()
            for c in entry.runtime_data.edr_coordinators.values()
        ],
    )

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: KNMIDirectConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: KNMIDirectConfigEntry) -> None:
    """Handle an options update."""
    await hass.config_entries.async_reload(entry.entry_id)
