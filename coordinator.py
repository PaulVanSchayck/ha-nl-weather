import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_NAME, CONF_LATITUDE, CONF_LONGITUDE, CONF_REGION
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import utcnow
from .app import ServerError
from .const import APP_API_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

class NLWeatherUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for NL Weather forecast data."""
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"NL Weather KNMI App API data coordinator for {entry.title} ({subentry.data[CONF_NAME]})",
            always_update=False,
            update_interval=APP_API_SCAN_INTERVAL,
        )
        self._api = entry.runtime_data.app
        self._location = {
            'lat': subentry.data[CONF_LATITUDE],
            'lon': subentry.data[CONF_LONGITUDE]
        }
        self._region = subentry.data[CONF_REGION]

    async def _async_setup(self) -> None:
        # Calculate forecast location ID
        await self.hass.async_add_executor_job(self._api.load_area_definition)
        self._forecast_location_id = self._api.get_closest_location(self._location)

    async def _async_update_data(self) -> dict[str, Any]:
        """Obtain the latest data from KNMI App API."""
        try:
            data = await self._api.weather(self._forecast_location_id, self._region)
        except ServerError as err:
            # TODO: Improve error handling
            raise UpdateFailed(f"Error while retrieving data: {err}") from err

        # Prune hours that already passed from the data, this is way more convenient to do here already
        current_hour = utcnow().replace(minute=0, second=0, microsecond=0)
        data['hourly']['forecast'] = [h for h in data['hourly']['forecast'] if datetime.fromisoformat(h['dateTime']) >= current_hour]

        return data
