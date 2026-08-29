import json
import logging
from typing import NotRequired, TypedDict, cast

from aiohttp import ClientResponseError, ClientSession

BASE_URL = "https://api.app.knmi.cloud"
_LOGGER = logging.getLogger(__name__)


class PrecipitationGraphData(TypedDict):
    """Precipitation graph data."""

    times: list[str]
    amounts: list[float]


class PrecipitationGraph(TypedDict):
    """Precipitation graph response."""

    precipitation: PrecipitationGraphData


class WeatherPrecipitation(TypedDict):
    """Weather precipitation data."""

    amount: float
    chance: float


class WeatherWind(TypedDict):
    """Weather wind data."""

    source: str
    degree: float
    speed: float
    gusts: float
    beaufort: int


class WeatherHourlyForecast(TypedDict):
    """Hourly weather forecast."""

    dateTime: str
    temperature: float
    precipitation: WeatherPrecipitation
    weatherType: int
    alertLevel: str
    wind: WeatherWind
    heatIndex: float


class WeatherHourly(TypedDict):
    """Hourly weather forecast container."""

    forecast: list[WeatherHourlyForecast]


class WeatherDailyTemperature(TypedDict):
    """Daily temperature data."""

    min: float
    max: float


class WeatherDailyForecast(TypedDict):
    """Daily weather forecast."""

    temperature: WeatherDailyTemperature
    precipitation: WeatherPrecipitation
    weatherType: int
    alertLevels: list[str]
    date: str
    uv_index: NotRequired[float | None]
    wind: NotRequired[WeatherWind]
    heatIndex: NotRequired[float | None]


class WeatherDaily(TypedDict):
    """Daily weather forecast container."""

    forecast: list[WeatherDailyForecast]


class WeatherBackground(TypedDict):
    """Weather background information."""

    sky: str
    clouds: str
    celestial: str
    dateTime: str


class WeatherAlert(TypedDict):
    """Weather alert."""

    level: str
    title: str
    description: str


class WeatherSummary(TypedDict):
    """Weather summary."""

    dateTime: str
    temperature: float


class WeatherSun(TypedDict):
    """Sunrise and sunset information."""

    sunrise: str
    sunset: str


class WeatherUvIndex(TypedDict):
    """UV index information."""

    value: float
    summary: str


class Weather(TypedDict):
    """KNMI weather response."""

    backgrounds: list[WeatherBackground]
    alerts: list[WeatherAlert]
    summaries: list[WeatherSummary]
    hourly: WeatherHourly
    daily: WeatherDaily
    wind: WeatherWind
    sun: WeatherSun
    uvIndex: WeatherUvIndex
    heatIndex: float


class EnrichedWeather(TypedDict):
    """KNMI weather data enriched with detailed daily forecasts."""

    backgrounds: list[WeatherBackground]
    alerts: list[WeatherAlert]
    summaries: list[WeatherSummary]
    hourly: WeatherHourly
    daily: WeatherDaily
    wind: WeatherWind
    sun: WeatherSun
    uvIndex: WeatherUvIndex
    heatIndex: float


class PrecipitationChance(TypedDict):
    """Precipitation probability data."""

    chance: float
    summary: str


class Sunshine(TypedDict):
    """Sunshine information."""

    description: str
    hours: float


class ClimateTemperatureRange(TypedDict):
    """Climate temperature range."""

    min: float
    max: float


class Climate(TypedDict):
    """Climate information."""

    month: int
    currentTemperatureRange: ClimateTemperatureRange
    averageTemperatureRange: ClimateTemperatureRange
    summary: str
    label: str


class DailyTemperatureData(TypedDict):
    """Daily temperature time series."""

    dates: list[str]
    minTemperatures: list[float]
    lowerMinTemperatures: list[float]
    upperMinTemperatures: list[float]
    maxTemperatures: list[float]
    lowerMaxTemperatures: list[float]
    upperMaxTemperatures: list[float]


class DailyPrecipitationData(TypedDict):
    """Daily precipitation time series."""

    dates: list[str]
    amounts: list[float]
    lowerAmounts: list[float]
    upperAmounts: list[float]


class WeatherDetailDaily(TypedDict):
    """Detailed daily weather data."""

    temperature: DailyTemperatureData
    precipitation: DailyPrecipitationData


class WeatherDetail(TypedDict):
    """KNMI detailed weather response."""

    alerts: list[WeatherAlert]
    precipitationChance: PrecipitationChance
    sunshine: Sunshine
    wind: WeatherWind
    sun: WeatherSun
    uvIndex: WeatherUvIndex
    heatIndex: float
    climate: Climate
    daily: WeatherDetailDaily


class App:
    """Client for the KNMI App API."""

    _session: ClientSession
    _area_definition: dict

    def __init__(self, aiohttp_session: ClientSession) -> None:
        self._session = aiohttp_session

    async def get(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
    ) -> object:
        """Get JSON data from a KNMI App API endpoint."""

        _LOGGER.debug(
            "Calling KNMI App API endpoint %s with %s",
            endpoint,
            params,
        )

        async with self._session.get(
            f"{BASE_URL}/{endpoint}",
            params=params
        ) as response:
            body = await response.text()

            try:
                response.raise_for_status()
            except ClientResponseError as e:
                if e.status == 400:
                    raise InvalidRequest(json.loads(body)) from None
                if e.status == 404:
                    raise NotFoundError("No data found for query") from None
                elif e.status >= 500:
                    raise ServerError(f"Status code: {e.status}: {body}") from None
                raise
            return json.loads(body)

    async def weather(
        self,
        cell_id: str,
        region: str,
    ) -> Weather:
        """Get weather data."""
        params = {
            "location": cell_id,
            "region": region,
        }

        response = await self.get("weather", params)
        # _LOGGER.debug("Weather response: %s", response)
        return cast(Weather, response)

    async def weather_detail(
        self,
        cell_id: str,
        region: str,
        date: str,
    ) -> WeatherDetail:
        """Get detailed weather data."""
        params = {
            "location": cell_id,
            "region": region,
            "date": date,
        }
        response = await self.get("weather/detail", params)
        # _LOGGER.debug("Weather/detail response: %s", response)

        return cast(WeatherDetail, response)

    async def precipitation_graph(
        self,
        radar_cell_id: str,
        date: str,
    ) -> PrecipitationGraph:
        """Get precipitation graph data."""
        params = {
            "location": radar_cell_id,
            "time": date,
        }
        response = await self.get("precipitation/graph", params)
        # _LOGGER.debug("precipitation/graph response: %s", response)

        return cast(PrecipitationGraph, response)


class AppException(Exception):
    """Base App Exception"""


class NotFoundError(AppException):
    """Exception class for no result found"""


class TokenInvalid(AppException):
    """Exception class when token is not accepted"""


class ServerError(AppException):
    """Exception class for server error"""


class InvalidRequest(AppException):
    """Exception class for invalid request"""
