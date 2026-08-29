from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from random import randint

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME, CONF_REGION
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    APP_FORECAST_API_SCAN_INTERVAL,
    APP_NOWCAST_API_SCAN_INTERVAL,
    CONF_STATION,
    PARAMETER_ATTRIBUTE_MAP,
)
from .KNMI.app import (
    App,
    AppException,
    PrecipitationGraph,
    Weather,
    WeatherDailyForecast,
)
from .KNMI.edr import EDR, NotFoundError, ServerError
from .KNMI.grid_definitions import GridDefinitions, GridManager
from .KNMI.helpers import (
    Coordinate,
    coverage_distance,
    format_dt,
    sort_coverages_on_distance,
    unique_items_sorted_by_frequency,
)
from .KNMI.notification_service import NotificationService
from .KNMI.wms import WMS

_LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeData:
    notification_service: NotificationService
    wms: WMS
    app: App
    edr: EDR
    app_coordinators: dict[str, NLWeatherUpdateCoordinator]
    nowcast_coordinators: dict[str, NLWeatherNowcastCoordinator]
    edr_coordinators: dict[str, NLWeatherEDRCoordinator]


type NLWeatherConfigEntry = ConfigEntry[RuntimeData]


class NLWeatherUpdateCoordinator(
    DataUpdateCoordinator[Weather],
):
    """Coordinator for NL Weather forecast data."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: NLWeatherConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"NL Weather KNMI App API data coordinator for {entry.title} ({subentry.data[CONF_NAME]})",
            always_update=False,
            update_interval=APP_FORECAST_API_SCAN_INTERVAL,
        )
        self._api = entry.runtime_data.app
        self._location = Coordinate(
            subentry.data[CONF_LATITUDE],
            subentry.data[CONF_LONGITUDE],
        )
        self._region = subentry.data[CONF_REGION]

    async def _async_setup(self) -> None:
        # Calculate grid cells for this location
        grid_manager = GridManager.default()
        self._forecast_cell = grid_manager.cell(
            GridDefinitions.FORECAST, self._location
        )

    async def _async_update_data(self) -> Weather:
        """Obtain the latest data from KNMI App API."""
        forecast_cell = self._forecast_cell

        if forecast_cell is None:
            raise UpdateFailed("KNMI forecast cell is not configured.")

        try:
            summary = await self._api.weather(
                forecast_cell,
                self._region,
            )

            enriched_forecast: list[WeatherDailyForecast] = []

            for daily_forecast in summary["daily"]["forecast"]:
                day_detail = await self._api.weather_detail(
                    forecast_cell,
                    self._region,
                    daily_forecast["date"],
                )

                enriched_forecast.append(
                    {
                        **daily_forecast,
                        "precipitation": {
                            **daily_forecast["precipitation"],
                            "chance": day_detail["precipitationChance"]["chance"],
                        },
                        "uv_index": (
                            day_detail["uvIndex"]["value"]
                            if "uvIndex" in day_detail
                            else None
                        ),
                        "wind": day_detail["wind"],
                        "heatIndex": day_detail.get("heatIndex"),
                    }
                )

        except AppException as err:
            raise UpdateFailed(
                f"Error while retrieving data: {err}"
            ) from err

        current_hour = datetime.now(timezone.utc).replace(
            minute=0,
            second=0,
            microsecond=0,
        )

        filtered_hourly_forecast = [
            hourly_forecast
            for hourly_forecast in summary["hourly"]["forecast"]
            if datetime.fromisoformat(hourly_forecast["dateTime"]) >= current_hour
        ]

        return {
            **summary,
            "hourly": {
                **summary["hourly"],
                "forecast": filtered_hourly_forecast,
            },
            "daily": {
                "forecast": enriched_forecast,
            },
        }


class NLWeatherNowcastCoordinator(
    DataUpdateCoordinator[list[dict[str, object]]]
):
    """Coordinator for NL Weather precipitation nowcast data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the precipitation nowcast coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=(
                "NL Weather KNMI App API precipitation nowcast coordinator "
                f"for {entry.title} ({subentry.data[CONF_NAME]})"
            ),
            always_update=False,
            update_interval=APP_NOWCAST_API_SCAN_INTERVAL,
        )

        self._api = entry.runtime_data.app
        self._location = Coordinate(
            subentry.data[CONF_LATITUDE],
            subentry.data[CONF_LONGITUDE],
        )
        self._region = subentry.data[CONF_REGION]
        radar_cell = GridManager.default().cell(
            GridDefinitions.RADAR,
            self._location,
        )

        if radar_cell is None:
            raise ConfigEntryError(
                "Unable to determine the KNMI radar cell for the configured location."
            )

        self._radar_cell: str = radar_cell

    def _get_precipitation_nowcast(
        self,
        precipitation_graph: PrecipitationGraph,
    ) -> list[dict[str, object]]:
        """Convert precipitation graph data to five-minute forecast data."""
        precipitation = precipitation_graph.get("precipitation")

        if not isinstance(precipitation, dict):
            raise TypeError(
                "Invalid precipitation graph: 'precipitation' must be a dictionary"
            )

        times = precipitation.get("times")
        amounts = precipitation.get("amounts")

        if not isinstance(times, list):
            raise TypeError(
                "Invalid precipitation graph: 'times' must be a list"
            )

        if not isinstance(amounts, list):
            raise TypeError(
                "Invalid precipitation graph: 'amounts' must be a list"
            )

        if len(times) != len(amounts):
            raise ValueError(
                "Invalid precipitation graph: 'times' and 'amounts' "
                "must have the same length"
            )

        if not all(isinstance(time, str) for time in times):
            raise TypeError(
                "Invalid precipitation graph: all 'times' values must be strings"
            )

        return [
            {
                "datetime": datetime.fromisoformat(time),
                "precipitation": amount,
            }
            for time, amount in zip(times, amounts, strict=True)
        ]

    async def _async_update_data(self) -> list[dict[str, object]]:
        """Retrieve precipitation nowcast data."""
        now = datetime.now(timezone.utc)
        latest_5_minutes = now.replace(
            minute=(now.minute // 5) * 5,
            second=0,
            microsecond=0,
        )

        try:
            precipitation_graph = await self._api.precipitation_graph(
                self._radar_cell,
                format_dt(latest_5_minutes),
            )
        except AppException as err:
            raise UpdateFailed(
                f"Error while retrieving precipitation nowcast: {err}"
            ) from err

        return self._get_precipitation_nowcast(precipitation_graph)


class NLWeatherEDRCoordinator(
    DataUpdateCoordinator[dict[str, object] | None]
):
    """Base EDR Coordinator"""

    _latest_filename_datetime = datetime(
        year=1970, month=1, day=1, hour=0, minute=0, second=0, tzinfo=timezone.utc
    )
    _station_names: dict[str, str]

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
        ns: NotificationService,
        edr: EDR,
    ) -> None:
        """Initialize the EDR coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"NL Weather EDR API data coordinator for "
            f"{subentry.data[CONF_NAME]}",
            update_interval=None,
        )
        self._ns = ns
        self._edr = edr
        self._config = subentry.data
        self._subentry = subentry
        self._station_names = {}

        self._location = Coordinate(
            self._config[CONF_LATITUDE],
            self._config[CONF_LONGITUDE],
        )

    async def get_coverage_datetime(self, event) -> None:
        pass

    async def _async_update_data(self) -> dict[str, object] | None:
        """No polling. Just return the already available data."""
        return self.data

    async def _async_setup(self):
        self._latest_filename_datetime = await self._edr.get_latest_datetime()

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
                # Not all stations have all sensors
                if param not in coverage["ranges"]:
                    continue
                data["params"][param] = coverage["ranges"][param]["values"][-1]
                # The value may be null for this station
                if data["params"][param] is None:
                    continue
                stations.append(coverage["eumetnet:locationId"])
                distances.append(distance)
                datetimes.append(coverage["domain"]["axes"]["t"]["values"][-1])
                break
            if param not in data["params"]:
                _LOGGER.warning(f"Did not find {param} in any coverage")

        if len(data["params"]) == 0:
            _LOGGER.warning("Found not a single parameter in the coverages")
            return data

        # Prepare for display
        data["datetime"] = datetime.fromisoformat(
            unique_items_sorted_by_frequency(datetimes)[0]
        )
        data["station_name"] = ", ".join(
            self._station_names[s] for s in unique_items_sorted_by_frequency(stations)
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
            # Allowing for some time for the data to be available in EDR, plus some jitter time
            await asyncio.sleep(15 + randint(0, 10))
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

        # Get some initial observation data
        coverages = await self._edr.get_cube_coverages(
            self._latest_filename_datetime, PARAMETER_ATTRIBUTE_MAP.values()
        )

        self.async_set_updated_data(self._prepare_data(coverages))


class NLWeatherManualEDRCoordinator(NLWeatherEDRCoordinator):
    """Coordinator that gets data for a specific weather station."""

    _latest_filename_datetime = datetime(
        year=1970, month=1, day=1, hour=0, minute=0, second=0, tzinfo=timezone.utc
    )

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
        ns: NotificationService,
        edr: EDR,
    ) -> None:
        """Initialize the manual EDR coordinator."""
        super().__init__(hass, entry, subentry, ns, edr)
        self._station = self._config[CONF_STATION]

    def _get_dict_value(
        self,
        data: dict[str, object],
        key: str,
        context: str,
    ) -> dict[str, object]:
        """Get a dictionary value from API data."""
        value = data.get(key)

        if not isinstance(value, dict):
            raise TypeError(
                f"KNMI {context} contains invalid {key} data."
            )

        return value

    def _get_list_value(
        self,
        data: dict[str, object],
        key: str,
        context: str,
    ) -> list[object]:
        """Get a list value from API data."""
        value = data.get(key)

        if not isinstance(value, list):
            raise TypeError(
                f"KNMI {context} contains invalid {key} data."
            )

        return value

    def _get_parameter_value(
        self,
        parameter_data: object,
        parameter: str,
    ) -> float:
        """Get the latest numeric value for a weather parameter."""
        if not isinstance(parameter_data, dict):
            raise TypeError(
                f"KNMI coverage contains invalid data for parameter {parameter}."
            )

        values = parameter_data.get("values")

        if not isinstance(values, list):
            raise TypeError(
                f"KNMI coverage contains invalid values for parameter {parameter}."
            )

        if not values:
            raise ValueError(
                f"KNMI coverage contains no values for parameter {parameter}."
            )

        value = values[-1]

        if not isinstance(value, (int, float)):
            raise TypeError(
                f"KNMI coverage contains a non-numeric value for parameter "
                f"{parameter}."
            )

        return float(value)

    def _prepare_parameters(
        self,
        ranges: dict[str, object],
    ) -> dict[str, float]:
        """Prepare the latest values for all weather parameters."""
        params: dict[str, float] = {}

        for parameter, parameter_data in ranges.items():
            params[parameter] = self._get_parameter_value(
                parameter_data,
                parameter,
            )

        return params

    def _get_datetime_value(
        self,
        values: list[object],
        context: str,
    ) -> datetime:
        """Get a timezone-aware datetime from API values."""
        if not values:
            raise ValueError(
                f"KNMI {context} contains no datetime values."
            )

        value = values[-1]

        if not isinstance(value, str):
            raise TypeError(
                f"KNMI {context} contains a non-string datetime value."
            )

        return datetime.fromisoformat(value)

    def _prepare_data(self, coverage: dict[str, object]) -> dict[str, object]:
        """Prepare KNMI observation data for the coordinator."""
        domain = self._get_dict_value(coverage, "domain", "coverage response")
        axes = self._get_dict_value(domain, "axes", "domain")
        time_axis = self._get_dict_value(axes, "t", "axes")
        time_values = self._get_list_value(time_axis, "values", "time axis")

        location_id = coverage.get("eumetnet:locationId")
        if not isinstance(location_id, str):
            raise TypeError(
                "KNMI coverage response contains an invalid "
                "EUMETNET location ID."
            )

        ranges = self._get_dict_value(
            coverage,
            "ranges",
            "coverage response",
        )

        prepare_data = {
            "datetime": self._get_datetime_value(
                time_values,
                "coverage response",
            ),
            "station_name": self._station_names[location_id],
            "distance": coverage_distance(coverage, self._location),
            "params": self._prepare_parameters(ranges),
        }
        _LOGGER.debug("Prepare location data: %s", prepare_data)
        return prepare_data

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
            # Allowing for some time for the data to be available in EDR, plus some jitter time
            await asyncio.sleep(15 + randint(0, 10))
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

    async def _async_setup(self) -> None:
        """Set up the coordinator and fetch initial observation data."""
        await super()._async_setup()

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
