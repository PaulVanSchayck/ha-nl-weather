"""Weather entity"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import cast, Any

from homeassistant.components.weather import WeatherEntity, ATTR_CONDITION_SUNNY, ATTR_CONDITION_CLEAR_NIGHT, \
    ATTR_WEATHER_HUMIDITY, ATTR_WEATHER_WIND_SPEED, ATTR_WEATHER_CLOUD_COVERAGE, ATTR_WEATHER_TEMPERATURE, \
    ATTR_WEATHER_VISIBILITY, ATTR_WEATHER_WIND_GUST_SPEED, ATTR_WEATHER_WIND_BEARING, ATTR_WEATHER_DEW_POINT, \
    ATTR_WEATHER_PRESSURE, ATTR_CONDITION_CLOUDY, ATTR_CONDITION_PARTLYCLOUDY, Forecast, WeatherEntityFeature
from homeassistant.const import UnitOfSpeed, UnitOfTemperature, UnitOfLength
from homeassistant.helpers import sun
from homeassistant.helpers.device_registry import DeviceInfo, DeviceEntryType
from homeassistant.util import utcnow
from . import KNMIDirectConfigEntry
from .app import App
from .notification_service import NotificationService
from .edr import EDR, NotFoundError, ServerError
from .const import DOMAIN, CONDITION_MAP, PARAMETER_ATTRIBUTE_MAP, ATTR_WEATHER_CONDITION, CONDITION_FORECAST_MAP

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)



async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: KNMIDirectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    ns = config_entry.runtime_data.notification_service
    edr = config_entry.runtime_data.edr
    app = config_entry.runtime_data.app
    location = {
        "lat": hass.config.latitude,
        "lon": hass.config.longitude,
    }
    async_add_entities([KNMIDirectWeather(config_entry, ns, edr, app, location)])

class KNMIDirectWeather(WeatherEntity):
    should_poll = False
    _attr_attribution = (
        "CC-BY 4.0 KNMI"
    )
    _attr_has_entity_name = True
    _latest_coverage = None
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )
    _hourly_forecast: list[Forecast] = []
    _daily_forecast: list[Forecast] = []
    _forecast_location_id = None

    def __init__(self, config_entry: KNMIDirectConfigEntry, ns: NotificationService, edr: EDR, app: App, location) -> None:
        self._ns = ns
        self._edr = edr
        self._app = app
        self._location = location
        self._attr_unique_id = "foobar"
        self._attr_device_info = DeviceInfo(
            name="KNMI",
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, config_entry.entry_id)},
            manufacturer="KNMI.nl",
            model="Meteorologische Waarnemingen",
            configuration_url="https://www.knmi.nl",
        )
        self._attr_name = "Thuis"

        # Units
        self._attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_visibility_unit = UnitOfLength.KILOMETERS


    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._latest_coverage is None:
            return None
        return {
            # TODO: Would be much nicer to get the station name
            "station_id": self._latest_coverage["eumetnet:locationId"],
            "datetime": self.get_latest_coverage_datetime()
        }

    @property
    def condition(self) -> str | None:
        """Return the current condition."""
        try:
            condition = CONDITION_MAP[self.get_latest_range_value(ATTR_WEATHER_CONDITION)]
        except KeyError:
            _LOGGER.exception("Unknown condition")
            condition =  ATTR_CONDITION_SUNNY

        if condition == ATTR_CONDITION_CLOUDY:
            if self.cloud_coverage <= 75:
                condition = ATTR_CONDITION_PARTLYCLOUDY
            if self.cloud_coverage <= 25:
                condition = ATTR_CONDITION_SUNNY

        if condition == ATTR_CONDITION_SUNNY and not sun.is_up(self.hass):
            condition = ATTR_CONDITION_CLEAR_NIGHT

        return condition

    @property
    def native_temperature(self) -> float:
        return self.get_latest_range_value(ATTR_WEATHER_TEMPERATURE)

    @property
    def cloud_coverage(self) -> float | None:
        # TODO: Check and explain calculation
        return self.get_latest_range_value(ATTR_WEATHER_CLOUD_COVERAGE)/8*100

    @property
    def native_wind_speed(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_WIND_SPEED)

    @property
    def native_visibility(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_VISIBILITY)/1000

    @property
    def native_pressure(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_PRESSURE)

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_WIND_GUST_SPEED)

    @property
    def wind_bearing(self) -> float | str | None:
        return self.get_latest_range_value(ATTR_WEATHER_WIND_BEARING)

    @property
    def native_dew_point(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_DEW_POINT)

    @property
    def humidity(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_HUMIDITY)

    def get_latest_range_value(self, attribute) -> float | None:
        if self._latest_coverage is None:
            return None
        p = PARAMETER_ATTRIBUTE_MAP[attribute]
        return self._latest_coverage['ranges'][p]['values'][0]

    def get_latest_coverage_datetime(self) -> datetime:
        if self._latest_coverage is None:
            return datetime(year=1970, month=1, day=1, hour=0, minute=0, second=0, tzinfo=timezone.utc)
        return datetime.fromisoformat(self._latest_coverage['domain']['axes']['t']['values'][0])

    async def get_coverage_datetime(self, event) -> None:
        event_datetime = datetime.strptime(event["data"]["filename"], "KMDS__OPER_P___10M_OBS_L2_%Y%m%d%H%M.nc").replace(
            tzinfo=timezone.utc)

        # TODO: Also consider distance to station when to refetch
        if event_datetime <= self.get_latest_coverage_datetime():
            return

        _LOGGER.debug(f"Fetch EDR coverage for datetime: {event_datetime}")
        for _ in range(3):
            await asyncio.sleep(15)
            try:
                self._latest_coverage = await self._edr.get_closest_coverage(self._location, event_datetime, PARAMETER_ATTRIBUTE_MAP.values())
                self.async_write_ha_state()
                return
            except (NotFoundError, ServerError) as e:
                _LOGGER.debug(f"Retrying fetching EDR coverage due to error: {e}")
                continue
        _LOGGER.warning(f"Could not retrieve latest coverage at {event_datetime} after 3 attempts")

    async def get_forecast(self, event = None) -> None:
        # TODO: Fix getting/setting region
        weather = await self._app.weather(self._forecast_location_id, "0")

        self._hourly_forecast = self.calc_hourly_forecast(weather['hourly']['forecast'])
        self._daily_forecast = self.calc_daily_forecast(weather['daily']['forecast'])
        self.async_write_ha_state()

    @staticmethod
    def calc_hourly_forecast(forecast) -> list[Forecast]:
        return [
            cast(Forecast, {
                'datetime': h['dateTime'],
                'condition': CONDITION_FORECAST_MAP[h['weatherType']], # TODO: Handle exceptions
                'native_temperature': h['temperature'],
                'native_precipitation': h['precipitation']['amount'],
                'precipitation_probability': h['precipitation']['chance'],
                'native_wind_speed': h['wind']['speed'],
                'native_wind_gust_speed': h['wind']['gusts'],
                'wind_bearing': h['wind']['degree']
            }) for h in forecast if datetime.fromisoformat(h['dateTime']).hour >= utcnow().hour
        ]

    @staticmethod
    def calc_daily_forecast(forecast) -> list[Forecast]:
        return [
            cast(Forecast, {
                'datetime': h['date'],
                'condition': CONDITION_FORECAST_MAP[h['weatherType']],  # TODO: Handle exceptions
                'native_temperature': h['temperature']['max'],
                'native_templow': h['temperature']['min'],
                'native_precipitation': h['precipitation']['amount'],
                'precipitation_probability': h['precipitation']['chance']
             }) for h in forecast
        ]

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast in native units."""
        return self._hourly_forecast

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return the hourly forecast in native units."""
        return self._daily_forecast

    async def async_added_to_hass(self):
        self._ns.set_callback('10-minute-in-situ-meteorological-observations', self.get_coverage_datetime)
        self._ns.set_callback('harmonie_arome_cy43_p1', self.get_forecast)

        # Get some initial observation data
        try:
            self._latest_coverage = await self._edr.get_latest_closest_coverage(self._location, PARAMETER_ATTRIBUTE_MAP.values())
            self.async_write_ha_state()
        except (NotFoundError, ServerError):
            _LOGGER.warning(f"Could not retrieve initial coverage")
            return

        # Calculate forecast location ID
        await self.hass.async_add_executor_job(self._app.load_area_definition)
        self._forecast_location_id = self._app.get_closest_location(self._location)

        # Get some initial forecast data
        # TODO: Error handling
        await self.get_forecast()

        return