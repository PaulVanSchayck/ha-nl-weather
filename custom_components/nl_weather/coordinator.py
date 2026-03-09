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
from .KNMI.helpers import (
    coverage_distance,
    sort_coverages_on_distance,
    unique_items_sorted_by_frequency,
)

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
    _station_names = {}

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

        self._location = {
            "lat": self._config[CONF_LATITUDE],
            "lon": self._config[CONF_LONGITUDE],
        }

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

        # Cache all station names
        stations = await self._edr.locations()
        for feature in stations["features"]:
            self._station_names[feature["id"]] = feature["properties"]["name"]


class NLWeatherAutoEDRCoordinator(NLWeatherEDRCoordinator):
    """Coordinator that gets the closest values for a specific location from a mix of weather stations"""

    def _prepare_data(self, coverages):
        sorted_coverages = sort_coverages_on_distance(coverages, self._location)

        data = {"params": {}, "datetime": None, "station_name": ""}
        stations, distances, datetimes = [], [], []

        for param in PARAMETER_ATTRIBUTE_MAP.values():
            for coverage, distance in sorted_coverages:
                if param not in coverage["ranges"]:
                    continue
                data["params"][param] = coverage["ranges"][param]["values"][-1]
                stations.append(coverage["eumetnet:locationId"])
                distances.append(distance)
                datetimes.append(coverage["domain"]["axes"]["t"]["values"][-1])
                break

        if len(data["params"]) == 0:
            _LOGGER.warning("Found not a single parameter in the coverages")
            return data

        # Prepare for display
        data["datetime"] = datetime.fromisoformat(
            unique_items_sorted_by_frequency(datetimes)[0]
        )
        data["station_name"] = ", ".join(
            list(
                map(
                    lambda s: self._station_names[s],
                    unique_items_sorted_by_frequency(stations),
                )
            )
        )
        data["distance"] = unique_items_sorted_by_frequency(distances)[0]

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
        await super()._async_setup()
        self._latest_filename_datetime = await self._edr.get_latest_datetime()

        # Get some initial observation data
        coverages = await self._edr.get_cube_coverages(
            self._latest_filename_datetime, PARAMETER_ATTRIBUTE_MAP.values()
        )

        self.async_set_updated_data(self._prepare_data(coverages))


class NLWeatherManualEDRCoordinator(NLWeatherEDRCoordinator):
    """Coordinator that gets data for specific weather station"""

    _latest_filename_datetime = datetime(
        year=1970, month=1, day=1, hour=0, minute=0, second=0, tzinfo=timezone.utc
    )

    def __init__(self, hass, subentry: ConfigSubentry, ns, edr) -> None:
        super().__init__(hass, subentry, ns, edr)
        self._station = self._config[CONF_STATION]

    def _prepare_data(self, coverage):
        return {
            "datetime": datetime.fromisoformat(
                coverage["domain"]["axes"]["t"]["values"][-1]
            ),
            "station_name": self._station_names[coverage["eumetnet:locationId"]],
            "distance": coverage_distance(coverage, self._location),
            "params": {p: i["values"][-1] for p, i in coverage["ranges"].items()},
        }

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
                    self._station, filename_datetime, PARAMETER_ATTRIBUTE_MAP.values()
                )
                self._latest_filename_datetime = filename_datetime
                self.async_set_updated_data(self._prepare_data(coverage))
                return
            except (NotFoundError, ServerError) as e:
                _LOGGER.debug(f"Retrying fetching EDR coverage due to error: {e}")
                continue
        _LOGGER.warning(
            f"Could not retrieve coverage for {self._station} at {filename_datetime} after 3 attempts"
        )

    async def _async_setup(self):
        await super()._async_setup()
        self._latest_filename_datetime = await self._edr.get_latest_datetime()

        # Get some initial observation data
        try:
            coverage = await self._edr.get_location_coverage(
                self._station,
                self._latest_filename_datetime,
                PARAMETER_ATTRIBUTE_MAP.values(),
            )
            self.async_set_updated_data(self._prepare_data(coverage))
        except NotFoundError:
            _LOGGER.debug(
                f"Could not fill initial data from {self._station} at {self._latest_filename_datetime}"
            )
            # TODO: This doesn't help yet
            self.async_set_updated_data(None)
