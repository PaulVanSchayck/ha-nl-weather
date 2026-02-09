"""The NL Weather integration."""

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .KNMI.app import App
from .KNMI.edr import EDR
from .KNMI.notification_service import NotificationService
from .KNMI.wms import WMS
from .const import CONF_MQTT_TOKEN, CONF_EDR_API_TOKEN, CONF_WMS_TOKEN, DOMAIN  # noqa: F401
from .coordinator import NLWeatherUpdateCoordinator, NLWeatherEDRCoordinator

_PLATFORMS: list[Platform] = [
    Platform.WEATHER,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]
_LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeData:
    """Class to hold your data."""

    notification_service: NotificationService
    wms: WMS
    app: App
    coordinators: dict[str, NLWeatherUpdateCoordinator]
    obs_coordinator: NLWeatherEDRCoordinator


type KNMIDirectConfigEntry = ConfigEntry[RuntimeData]  # noqa: F821


async def async_setup_entry(hass: HomeAssistant, entry: KNMIDirectConfigEntry) -> bool:
    """Set up from a config entry."""
    _LOGGER.debug("async_setup_entry")

    session = async_get_clientsession(hass)
    ns = NotificationService(entry.data[CONF_MQTT_TOKEN])
    entry.async_create_background_task(hass, ns.run(), "NotificationService")

    entry.runtime_data = RuntimeData(
        notification_service=ns,
        wms=WMS(session, entry.data[CONF_WMS_TOKEN]),
        app=App(session),
        coordinators={},
        obs_coordinator=NLWeatherEDRCoordinator(
            hass, entry, ns, EDR(session, entry.data[CONF_EDR_API_TOKEN])
        ),
    )

    await entry.runtime_data.obs_coordinator.async_config_entry_first_refresh()

    for subentry_id, subentry in entry.subentries.items():
        entry.runtime_data.coordinators[subentry_id] = NLWeatherUpdateCoordinator(
            hass, entry, subentry
        )
        await entry.runtime_data.coordinators[
            subentry_id
        ].async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: KNMIDirectConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
