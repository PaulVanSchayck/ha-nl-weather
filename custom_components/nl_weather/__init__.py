"""The NL Weather integration."""

import asyncio
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
    NLWeatherConfigEntry,
    NLWeatherAutoEDRCoordinator,
    NLWeatherManualEDRCoordinator,
    NLWeatherUpdateCoordinator,
    RuntimeData,
)

_PLATFORMS: list[Platform] = [
    Platform.WEATHER,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: NLWeatherConfigEntry) -> bool:
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
        entry.runtime_data.app_coordinators[subentry_id] = NLWeatherUpdateCoordinator(
            hass, entry, subentry
        )
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

    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def async_update_listener(
    hass: HomeAssistant, entry: NLWeatherConfigEntry
) -> None:
    """Handle update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NLWeatherConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.version > 1:
        # This means the user has downgraded from a future version
        return False

    if config_entry.version == 1:
        if config_entry.minor_version < 2:
            for subentry in config_entry.subentries.values():
                new_data = {**subentry.data}
                new_data[CONF_MODE] = StationMode.AUTO
                hass.config_entries.async_update_subentry(
                    config_entry, subentry, data=new_data
                )

            hass.config_entries.async_update_entry(
                config_entry,
                minor_version=2,
            )

    _LOGGER.debug(
        "Migration to configuration version %s.%s successful",
        config_entry.version,
        config_entry.minor_version,
    )

    return True
