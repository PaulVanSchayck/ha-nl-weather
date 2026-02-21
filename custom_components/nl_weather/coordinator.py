import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_NAME, CONF_LATITUDE, CONF_LONGITUDE, CONF_REGION
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import utcnow

from .const import APP_API_SCAN_INTERVAL, CONF_STATION, PARAMETER_ATTRIBUTE_MAP
from .KNMI.edr import NotFoundError, ServerError
from .KNMI.helpers import sort_coverage_on_distance

_LOGGER = logging.getLogger(__name__)


class NLWeatherUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for NL Weather forecast data."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, subentry: ConfigSubentry
    ) -> None:
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
            "lat": subentry.data[CONF_LATITUDE],
            "lon": subentry.data[CONF_LONGITUDE],
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
        data["hourly"]["forecast"] = [
            h
            for h in data["hourly"]["forecast"]
            if datetime.fromisoformat(h["dateTime"]) >= current_hour
        ]

        return data


class NLWeatherEDRCoordinator(DataUpdateCoordinator):
    """Base EDR Coordinator"""

    _latest_filename_datetime = datetime(
        year=1970, month=1, day=1, hour=0, minute=0, second=0, tzinfo=timezone.utc
    )

    def __init__(self, hass, subentry: ConfigSubentry, ns, edr) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"NL Weather EDR API data coordinator for {subentry.data[CONF_NAME]}",
            update_interval=None,  # no polling
        )
        self._ns = ns
        self._edr = edr
        self._config = subentry.data
        self._subentry = subentry

    async def get_coverage_datetime(self, event) -> None:
        pass

    async def _async_update_data(self):
        """No polling. Just return the already available data."""
        return self.data

    async def _async_setup(self):
        # TODO: Handle removal of this callback
        self._ns.set_callback(
            "10-minute-in-situ-meteorological-observations",
            self._subentry.subentry_id,
            self.get_coverage_datetime,
        )


class NLWeatherAutoEDRCoordinator(NLWeatherEDRCoordinator):
    """Coordinator that gets the closest values for a specific location from a mix of weather stations"""

    def __init__(self, hass, subentry: ConfigSubentry, ns, edr) -> None:
        super().__init__(hass, subentry, ns, edr)
        self._location = {
            "lat": self._config[CONF_LATITUDE],
            "lon": self._config[CONF_LONGITUDE],
        }

    def _prepare_data(self, coverages):
        sorted_coverages = sort_coverage_on_distance(coverages, self._location)

        data = {"ranges": {}, "datetime": None}
        for param in PARAMETER_ATTRIBUTE_MAP.values():
            for coverage in sorted_coverages:
                if param in coverage["ranges"]:
                    data["ranges"][param] = coverage["ranges"][param]

        # TODO: Do this prettier
        data["datetime"] = datetime.fromisoformat(
            sorted_coverages[0]["domain"]["axes"]["t"]["values"][0]
        )

        return data

    async def get_coverage_datetime(self, event) -> None:
        filename_datetime = datetime.strptime(
            event["data"]["filename"], "KMDS__OPER_P___10M_OBS_L2_%Y%m%d%H%M.nc"
        ).replace(tzinfo=timezone.utc)

        if filename_datetime < self._latest_filename_datetime:
            _LOGGER.debug(
                f"Already got coverage later than datetime: {filename_datetime}"
            )
            return

        _LOGGER.debug(f"Fetch EDR coverage for datetime: {filename_datetime}")
        for _ in range(3):
            await asyncio.sleep(15)
            try:
                coverages = await self._edr.get_cube_coverages(
                    filename_datetime, PARAMETER_ATTRIBUTE_MAP.values()
                )
                self._latest_filename_datetime = filename_datetime
                self.async_set_updated_data(self._prepare_data(coverages))
                return
            except (NotFoundError, ServerError) as e:
                _LOGGER.debug(f"Retrying fetching EDR coverage due to error: {e}")
                continue
        _LOGGER.warning(
            f"Could not retrieve latest cube coverage at {filename_datetime} after 3 attempts"
        )

    async def _async_setup(self):
        self._latest_filename_datetime = await self._edr.get_latest_datetime()

        # Get some initial observation data
        coverages = await self._edr.get_cube_coverages(
            self._latest_filename_datetime, PARAMETER_ATTRIBUTE_MAP.values()
        )

        self.async_set_updated_data(self._prepare_data(coverages))
        return await super()._async_setup()


class NLWeatherManualEDRCoordinator(NLWeatherEDRCoordinator):
    """Coordinator that gets data for specific weather station"""

    _latest_filename_datetime = datetime(
        year=1970, month=1, day=1, hour=0, minute=0, second=0, tzinfo=timezone.utc
    )

    def __init__(self, hass, subentry: ConfigSubentry, ns, edr) -> None:
        super().__init__(hass, subentry, ns, edr)
        self._location = self._config[CONF_STATION]

    def _prepare_data(self, coverage):
        coverage["datetime"] = datetime.fromisoformat(
            coverage["domain"]["axes"]["t"]["values"][0]
        )
        return coverage

    async def get_coverage_datetime(self, event) -> None:
        filename_datetime = datetime.strptime(
            event["data"]["filename"], "KMDS__OPER_P___10M_OBS_L2_%Y%m%d%H%M.nc"
        ).replace(tzinfo=timezone.utc)

        if filename_datetime <= self._latest_filename_datetime:
            _LOGGER.debug(
                f"Already got coverage later than or at datetime: {filename_datetime}"
            )
            return

        _LOGGER.debug(f"Fetch EDR coverage for datetime: {filename_datetime}")
        for _ in range(3):
            await asyncio.sleep(15)
            try:
                coverage = await self._edr.get_location_coverage(
                    self._location, filename_datetime, PARAMETER_ATTRIBUTE_MAP.values()
                )
                self._latest_filename_datetime = filename_datetime
                self.async_set_updated_data(self._prepare_data(coverage))
                return
            except (NotFoundError, ServerError) as e:
                _LOGGER.debug(f"Retrying fetching EDR coverage due to error: {e}")
                continue
        _LOGGER.warning(
            f"Could not retrieve coverage for {self._location} at {filename_datetime} after 3 attempts"
        )

    async def _async_setup(self):
        self._latest_filename_datetime = await self._edr.get_latest_datetime()

        # Get some initial observation data
        try:
            coverage = await self._edr.get_location_coverage(
                self._location,
                self._latest_filename_datetime,
                PARAMETER_ATTRIBUTE_MAP.values(),
            )
            self.async_set_updated_data(self._prepare_data(coverage))
        except NotFoundError:
            _LOGGER.debug(
                f"Could not fill initial data from {self._location} at {self._latest_filename_datetime}"
            )
            # TODO: This doesn't help yet
            self.async_set_updated_data(None)

        return await super()._async_setup()
