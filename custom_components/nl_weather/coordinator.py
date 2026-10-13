"""KNMI weather data coordinators."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from random import randint

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME, CONF_REGION
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

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

type Coverage = dict[str, object]
type NotificationEvent = dict[str, object]


type NLWeatherConfigEntry = ConfigEntry["RuntimeData"]


@dataclass
class RuntimeData:
    """Runtime data for the NL Weather integration."""

    notification_service: NotificationService
    wms: WMS
    app: App
    edr: EDR
    app_coordinators: dict[str, "NLWeatherUpdateCoordinator"]
    nowcast_coordinators: dict[str, "NLWeatherNowcastCoordinator"]
    edr_coordinators: dict[str, "NLWeatherEDRCoordinator"]


class NLWeatherUpdateCoordinator(DataUpdateCoordinator[Weather]):
    """Coordinator for NL Weather forecast data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=(
                "NL Weather KNMI App API data coordinator for "
                f"{entry.title} ({subentry.data[CONF_NAME]})"
            ),
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
        """Calculate the forecast grid cell for this location."""
        grid_manager = GridManager.default()
        self._forecast_cell = grid_manager.cell(
            GridDefinitions.FORECAST,
            self._location,
        )

    async def _async_update_data(self) -> Weather:
        """Obtain the latest data from the KNMI App API."""
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
                "Unable to determine the KNMI radar cell for the configured "
                "location."
            )

        self._radar_cell = radar_cell

    def _get_precipitation_nowcast(
        self,
        precipitation_graph: PrecipitationGraph,
    ) -> list[dict[str, object]]:
        """Convert precipitation graph data to five-minute forecast data."""
        precipitation = precipitation_graph.get("precipitation")

        if not isinstance(precipitation, dict):
            raise TypeError(
                "Invalid precipitation graph: 'precipitation' must be a dictionary."
            )

        times = precipitation.get("times")
        amounts = precipitation.get("amounts")

        if not isinstance(times, list):
            raise TypeError(
                "Invalid precipitation graph: 'times' must be a list."
            )

        if not isinstance(amounts, list):
            raise TypeError(
                "Invalid precipitation graph: 'amounts' must be a list."
            )

        if len(times) != len(amounts):
            raise ValueError(
                "Invalid precipitation graph: 'times' and 'amounts' "
                "must have the same length."
            )

        if not all(isinstance(value, str) for value in times):
            raise TypeError(
                "Invalid precipitation graph: all 'times' values must be strings."
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
    """Base coordinator for KNMI EDR observation data."""

    _INITIAL_DATETIME = datetime(
        1970,
        1,
        1,
        tzinfo=timezone.utc,
    )

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
        notification_service: NotificationService,
        edr: EDR,
    ) -> None:
        """Initialize the EDR coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=(
                "NL Weather EDR API data coordinator for "
                f"{subentry.data[CONF_NAME]}"
            ),
            update_interval=None,
        )

        self._notification_service = notification_service
        self._edr = edr
        self._config = subentry.data
        self._subentry = subentry
        self._latest_filename_datetime = self._INITIAL_DATETIME
        self._station_names: dict[str, str] = {}

        self._location = Coordinate(
            self._config[CONF_LATITUDE],
            self._config[CONF_LONGITUDE],
        )

    async def get_coverage_datetime(
        self,
        event: NotificationEvent,
    ) -> None:
        """Handle a new KNMI observation notification."""
        raise NotImplementedError

    async def _async_update_data(self) -> dict[str, object] | None:
        """Return the latest event-driven EDR data without polling."""
        return self.data

    async def _async_setup(self) -> None:
        """Initialize the EDR coordinator and notification callback."""
        self._latest_filename_datetime = await self._edr.get_latest_datetime()

        self._notification_service.set_callback(
            "10-minute-in-situ-meteorological-observations",
            self._subentry.subentry_id,
            self.get_coverage_datetime,
        )

        stations = await self._edr.locations()

        features = stations.get("features")
        if not isinstance(features, list):
            raise TypeError(
                "KNMI EDR locations response contains invalid 'features' data."
            )

        for feature in features:
            if not isinstance(feature, dict):
                continue

            station_id = feature.get("id")
            properties = feature.get("properties")

            if not isinstance(station_id, str):
                continue

            if not isinstance(properties, dict):
                continue

            station_name = properties.get("name")
            if isinstance(station_name, str):
                self._station_names[station_id] = station_name


class NLWeatherAutoEDRCoordinator(NLWeatherEDRCoordinator):
    """Coordinator that selects the closest station for each parameter."""

    def _prepare_data(
        self,
        coverages: list[Coverage],
    ) -> dict[str, object]:
        """Prepare observation data from the available station coverages."""
        sorted_coverages = sort_coverages_on_distance(
            coverages,
            self._location,
        )

        data: dict[str, object] = {
            "params": {},
            "datetime": None,
            "station_name": "",
        }

        params = data["params"]
        if not isinstance(params, dict):
            raise TypeError("Prepared EDR data contains invalid parameters.")

        stations: list[str] = []
        distances: list[float] = []
        datetimes: list[str] = []

        for parameter in PARAMETER_ATTRIBUTE_MAP.values():
            for coverage, distance in sorted_coverages:
                ranges = coverage.get("ranges")

                if not isinstance(ranges, dict) or parameter not in ranges:
                    continue

                parameter_data = ranges[parameter]
                if not isinstance(parameter_data, dict):
                    continue

                values = parameter_data.get("values")
                if not isinstance(values, list) or not values:
                    continue

                value = values[-1]

                if value is None:
                    continue

                params[parameter] = value

                location_id = coverage.get("eumetnet:locationId")
                if isinstance(location_id, str):
                    stations.append(location_id)

                distances.append(distance)

                domain = coverage.get("domain")
                if isinstance(domain, dict):
                    axes = domain.get("axes")
                    if isinstance(axes, dict):
                        time_axis = axes.get("t")
                        if isinstance(time_axis, dict):
                            time_values = time_axis.get("values")
                            if isinstance(time_values, list) and time_values:
                                datetime_value = time_values[-1]
                                if isinstance(datetime_value, str):
                                    datetimes.append(datetime_value)

                break

            if parameter not in params:
                _LOGGER.warning(
                    "Did not find %s in any KNMI EDR coverage",
                    parameter,
                )

        if not params:
            _LOGGER.warning("Did not find a single parameter in the KNMI EDR coverages")
            return data

        if not datetimes:
            raise ValueError(
                "KNMI EDR coverages contain no valid observation timestamps."
            )

        if not stations:
            raise ValueError(
                "KNMI EDR coverages contain no valid station identifiers."
            )

        data["datetime"] = datetime.fromisoformat(
            unique_items_sorted_by_frequency(datetimes)[0]
        )
        data["station_name"] = ", ".join(
            self._station_names.get(station, station)
            for station in unique_items_sorted_by_frequency(stations)
        )
        data["distance"] = unique_items_sorted_by_frequency(distances)[0]

        return data

    async def get_coverage_datetime(
        self,
        event: NotificationEvent,
    ) -> None:
        """Fetch and publish EDR data for a new observation timestamp."""
        filename_datetime = self._get_filename_datetime(event)

        if filename_datetime <= self._latest_filename_datetime:
            _LOGGER.debug(
                "Already have EDR coverage at or after %s",
                filename_datetime,
            )
            return

        _LOGGER.debug(
            "Fetching EDR coverage for %s",
            filename_datetime,
        )

        for attempt in range(3):
            await asyncio.sleep(15 + randint(0, 10))

            try:
                coverages = await self._edr.get_cube_coverages(
                    filename_datetime,
                    PARAMETER_ATTRIBUTE_MAP.values(),
                )
            except (NotFoundError, ServerError) as err:
                _LOGGER.debug(
                    "Retry %d/3 fetching EDR coverage for %s: %s",
                    attempt + 1,
                    filename_datetime,
                    err,
                )
                continue

            self._latest_filename_datetime = filename_datetime
            self.async_set_updated_data(self._prepare_data(coverages))
            return

        _LOGGER.warning(
            "Could not retrieve latest cube coverage at %s after 3 attempts",
            filename_datetime,
        )

    async def _async_setup(self) -> None:
        """Set up the coordinator and fetch the initial observation data."""
        await super()._async_setup()

        coverages = await self._edr.get_cube_coverages(
            self._latest_filename_datetime,
            PARAMETER_ATTRIBUTE_MAP.values(),
        )

        self.async_set_updated_data(self._prepare_data(coverages))

    @staticmethod
    def _get_filename_datetime(
        event: NotificationEvent,
    ) -> datetime:
        """Extract the observation datetime from a notification event."""
        event_data = event.get("data")

        if not isinstance(event_data, dict):
            raise ValueError(
                "KNMI notification event contains invalid 'data'."
            )

        filename = event_data.get("filename")

        if not isinstance(filename, str):
            raise ValueError(
                "KNMI notification event contains no valid 'filename'."
            )

        try:
            return datetime.strptime(
                filename,
                "KMDS__OPER_P___10M_OBS_L2_%Y%m%d%H%M.nc",
            ).replace(tzinfo=timezone.utc)
        except ValueError as err:
            raise ValueError(
                f"Invalid KNMI observation filename: {filename}"
            ) from err


class NLWeatherManualEDRCoordinator(NLWeatherEDRCoordinator):
    """Coordinator that gets data for a specific weather station."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
        notification_service: NotificationService,
        edr: EDR,
    ) -> None:
        """Initialize the manual EDR coordinator."""
        super().__init__(
            hass,
            entry,
            subentry,
            notification_service,
            edr,
        )
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
        return {
            parameter: self._get_parameter_value(
                parameter_data,
                parameter,
            )
            for parameter, parameter_data in ranges.items()
        }

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

        parsed_datetime = datetime.fromisoformat(value)

        if parsed_datetime.tzinfo is None:
            raise ValueError(
                f"KNMI {context} contains a timezone-naive datetime."
            )

        return parsed_datetime

    def _prepare_data(
        self,
        coverage: Coverage,
    ) -> dict[str, object]:
        """Prepare KNMI observation data for the coordinator."""
        domain = self._get_dict_value(
            coverage,
            "domain",
            "coverage response",
        )
        axes = self._get_dict_value(
            domain,
            "axes",
            "domain",
        )
        time_axis = self._get_dict_value(
            axes,
            "t",
            "axes",
        )
        time_values = self._get_list_value(
            time_axis,
            "values",
            "time axis",
        )

        location_id = coverage.get("eumetnet:locationId")
        if not isinstance(location_id, str):
            raise TypeError(
                "KNMI coverage response contains an invalid "
                "EUMETNET location ID."
            )

        station_name = self._station_names.get(location_id)
        if station_name is None:
            raise ValueError(
                f"KNMI EDR did not return a station name for {location_id}."
            )

        ranges = self._get_dict_value(
            coverage,
            "ranges",
            "coverage response",
        )

        prepared_data: dict[str, object] = {
            "datetime": self._get_datetime_value(
                time_values,
                "coverage response",
            ),
            "station_name": station_name,
            "distance": coverage_distance(
                coverage,
                self._location,
            ),
            "params": self._prepare_parameters(ranges),
        }

        _LOGGER.debug(
            "Prepared KNMI EDR location data: %s",
            prepared_data,
        )

        return prepared_data

    async def get_coverage_datetime(
        self,
        event: NotificationEvent,
    ) -> None:
        """Fetch and publish EDR data for a new observation timestamp."""
        filename_datetime = self._get_filename_datetime(event)

        if filename_datetime <= self._latest_filename_datetime:
            _LOGGER.debug(
                "Already have EDR coverage at or after %s",
                filename_datetime,
            )
            return

        _LOGGER.debug(
            "Fetching EDR coverage for station %s at %s",
            self._station,
            filename_datetime,
        )

        for attempt in range(3):
            await asyncio.sleep(15 + randint(0, 10))

            try:
                coverage = await self._edr.get_location_coverage(
                    self._station,
                    filename_datetime,
                    PARAMETER_ATTRIBUTE_MAP.values(),
                )
            except (NotFoundError, ServerError) as err:
                _LOGGER.debug(
                    "Retry %d/3 fetching EDR coverage for station %s at %s: %s",
                    attempt + 1,
                    self._station,
                    filename_datetime,
                    err,
                )
                continue

            self._latest_filename_datetime = filename_datetime
            self.async_set_updated_data(
                self._prepare_data(coverage)
            )
            return

        _LOGGER.warning(
            "Could not retrieve coverage for %s at %s after 3 attempts",
            self._station,
            filename_datetime,
        )

    async def _async_setup(self) -> None:
        """Set up the coordinator and fetch initial observation data."""
        await super()._async_setup()

        try:
            coverage = await self._edr.get_location_coverage(
                self._station,
                self._latest_filename_datetime,
                PARAMETER_ATTRIBUTE_MAP.values(),
            )
        except NotFoundError:
            _LOGGER.debug(
                "Could not fill initial data from %s at %s",
                self._station,
                self._latest_filename_datetime,
            )
            self.async_set_updated_data(None)
            return

        self.async_set_updated_data(
            self._prepare_data(coverage)
        )

    @staticmethod
    def _get_filename_datetime(
        event: NotificationEvent,
    ) -> datetime:
        """Extract the observation datetime from a notification event."""
        event_data = event.get("data")

        if not isinstance(event_data, dict):
            raise ValueError(
                "KNMI notification event contains invalid 'data'."
            )

        filename = event_data.get("filename")

        if not isinstance(filename, str):
            raise ValueError(
                "KNMI notification event contains no valid 'filename'."
            )

        try:
            return datetime.strptime(
                filename,
                "KMDS__OPER_P___10M_OBS_L2_%Y%m%d%H%M.nc",
            ).replace(tzinfo=timezone.utc)
        except ValueError as err:
            raise ValueError(
                f"Invalid KNMI observation filename: {filename}"
            ) from err