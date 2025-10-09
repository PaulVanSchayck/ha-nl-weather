import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .notification_service import NotificationService
from .edr import EDR, NotFoundError, closest_coverage
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_NAME, CONF_LATITUDE, CONF_LONGITUDE, CONF_REGION
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import utcnow
from .app import ServerError
from .const import APP_API_SCAN_INTERVAL, PARAMETER_ATTRIBUTE_MAP, EDR_STATION_MINIMAL_DISTANCE

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


class NLWeatherEDRCoordinator(DataUpdateCoordinator):
    """Coordinator that only calls EDR API when NotificationService tells to"""
    _latest_filename_datetime = datetime(year=1970, month=1, day=1, hour=0, minute=0, second=0, tzinfo=timezone.utc)
    _station_names = {}

    def __init__(self, hass, entry: ConfigEntry, ns: NotificationService, edr: EDR) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"NL Weather EDR API data coordinator",
            update_interval=None,  # no polling
        )
        self._ns = ns
        self._edr = edr

        self._locations = {}
        for subentry_id, subentry in entry.subentries.items():
            self._locations[subentry_id] = {
               'lat': subentry.data[CONF_LATITUDE],
               'lon': subentry.data[CONF_LONGITUDE]
            }

    def _prepare_data(self, coverages):
        data = {}
        for subentry_id, location in self._locations.items():
            coverage, distance = closest_coverage(coverages, location)
            data[subentry_id] = {
                'ranges': coverage['ranges'],
                'distance': distance,
                'datetime': datetime.fromisoformat(coverage['domain']['axes']['t']['values'][0]),
                'station_id': coverage['eumetnet:locationId'],
                'station_name': self._station_names[coverage['eumetnet:locationId']],
            }
        return data

    async def get_coverage_datetime(self, event) -> None:
        filename_datetime = datetime.strptime(event["data"]["filename"], "KMDS__OPER_P___10M_OBS_L2_%Y%m%d%H%M.nc").replace(
            tzinfo=timezone.utc)

        if filename_datetime < self._latest_filename_datetime:
            _LOGGER.debug(f"Already got coverage later than datetime: {filename_datetime}")
            return

        if filename_datetime == self._latest_filename_datetime and max(v["distance"] for v in self.data.values()) < EDR_STATION_MINIMAL_DISTANCE:
            _LOGGER.debug(f"Already got close enough coverages for datetime: {filename_datetime}")
            return

        _LOGGER.debug(f"Fetch EDR coverage for datetime: {filename_datetime}")
        for _ in range(3):
            await asyncio.sleep(15)
            try:
                coverages = await self._edr.get_coverage(filename_datetime, PARAMETER_ATTRIBUTE_MAP.values())
                self._latest_filename_datetime = filename_datetime
                self.async_set_updated_data(self._prepare_data(coverages))
                return
            except (NotFoundError, ServerError) as e:
                _LOGGER.debug(f"Retrying fetching EDR coverage due to error: {e}")
                continue
        _LOGGER.warning(f"Could not retrieve latest coverage at {filename_datetime} after 3 attempts")

    async def _async_update_data(self):
        """No polling. Just return the already available data."""
        return self.data

    async def _async_setup(self):
        # TODO: Handle removal of this callback
        self._ns.set_callback('10-minute-in-situ-meteorological-observations', "NLWeatherEDRCoordinator", self.get_coverage_datetime)

        # Cache all station names
        stations = await self._edr.locations()
        for feature in stations['features']:
            self._station_names[feature['id']] = feature['properties']['name']

        # Get some initial observation data
        coverages, latest_dt = await self._edr.get_latest_coverage(PARAMETER_ATTRIBUTE_MAP.values())
        self._latest_filename_datetime = latest_dt
        self.async_set_updated_data(self._prepare_data(coverages))
