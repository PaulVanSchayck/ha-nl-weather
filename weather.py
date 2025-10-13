"""Weather entity"""

from __future__ import annotations

import logging
from typing import cast, Any

from homeassistant.components.weather import WeatherEntity, ATTR_CONDITION_SUNNY, ATTR_CONDITION_CLEAR_NIGHT, \
    ATTR_WEATHER_HUMIDITY, ATTR_WEATHER_WIND_SPEED, ATTR_WEATHER_CLOUD_COVERAGE, ATTR_WEATHER_TEMPERATURE, \
    ATTR_WEATHER_VISIBILITY, ATTR_WEATHER_WIND_GUST_SPEED, ATTR_WEATHER_WIND_BEARING, ATTR_WEATHER_DEW_POINT, \
    ATTR_WEATHER_PRESSURE, ATTR_CONDITION_CLOUDY, ATTR_CONDITION_PARTLYCLOUDY, Forecast, WeatherEntityFeature, \
    ATTR_CONDITION_FOG, ATTR_CONDITION_WINDY, ATTR_CONDITION_WINDY_VARIANT
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import UnitOfSpeed, UnitOfTemperature, UnitOfLength, CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.helpers import sun
from homeassistant.helpers.device_registry import DeviceInfo, DeviceEntryType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import KNMIDirectConfigEntry
from .coordinator import NLWeatherUpdateCoordinator, NLWeatherEDRCoordinator
from .const import DOMAIN, CONDITION_MAP, PARAMETER_ATTRIBUTE_MAP, ATTR_WEATHER_CONDITION, CONDITION_FORECAST_MAP

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: KNMIDirectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:

    for subentry_id, subentry in config_entry.subentries.items():

        coordinator = config_entry.runtime_data.coordinators[subentry_id]

        # TODO: Make these entities configurable
        async_add_entities(
            [
                NLWeatherForecast(coordinator, config_entry, subentry),
                NLWeatherObservations(config_entry.runtime_data.obs_coordinator, config_entry, subentry)

            ], config_subentry_id=subentry_id
        )

class NLWeatherObservations(CoordinatorEntity[NLWeatherEDRCoordinator], WeatherEntity):
    _attr_should_poll = False
    _attr_attribution = (
        "Meteorological observations provided by Koninklijk Nederlands Meteorologisch Instituut (KNMI) licensed under CC-BY 4.0"
    )
    _attr_has_entity_name = True
    _latest_coverage = None

    def __init__(self, coordinator: NLWeatherEDRCoordinator, config_entry: KNMIDirectConfigEntry,
                 subentry: ConfigSubentry ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_observations"
        self._attr_device_info = DeviceInfo(
            name=f"Observations",
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_observations")},
            manufacturer="KNMI.nl",
            model="Observations",
            configuration_url="https://www.knmi.nl",
        )
        self._attr_name = subentry.data[CONF_NAME]
        self._subentry_id = subentry.subentry_id

        # Units
        self._attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_visibility_unit = UnitOfLength.METERS

    @property
    def condition(self) -> str | None:
        """Return the current condition."""
        try:
            condition = CONDITION_MAP[self.get_latest_range_value(ATTR_WEATHER_CONDITION)]
        except KeyError:
            _LOGGER.exception("Unknown condition")
            return ATTR_CONDITION_SUNNY

        # Foggy condition is reported well above 1000 m visibility. Only below 1000 meter it is "fog"
        if condition == ATTR_CONDITION_FOG and self.native_visibility > 1000:
                condition = ATTR_CONDITION_CLOUDY

        # Difference between cloudy, partly cloudy and sunny is not reported
        if condition == ATTR_CONDITION_CLOUDY:
            if self.cloud_coverage <= 75:
                condition = ATTR_CONDITION_PARTLYCLOUDY
            if self.cloud_coverage <= 25:
                condition = ATTR_CONDITION_SUNNY

            # Wind speed above 6 Bft or wind gusts above 72 km/h are windy conditions
            if self.native_wind_speed > 12 or self.native_wind_gust_speed > 20:
                if self.cloud_coverage <= 75:
                    condition = ATTR_CONDITION_WINDY
                else:
                    condition = ATTR_CONDITION_WINDY_VARIANT

        if condition == ATTR_CONDITION_SUNNY and not sun.is_up(self.hass):
            condition = ATTR_CONDITION_CLEAR_NIGHT

        return condition

    @property
    def native_temperature(self) -> float:
        return self.get_latest_range_value(ATTR_WEATHER_TEMPERATURE)

    @property
    def cloud_coverage(self) -> float | None:
        # Unit is okta (https://qudt.org/vocab/unit/OKTA)
        return self.get_latest_range_value(ATTR_WEATHER_CLOUD_COVERAGE)/8*100

    @property
    def native_wind_speed(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_WIND_SPEED)

    @property
    def native_visibility(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_VISIBILITY)

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
        if self.coordinator.data is None:
            return None
        p = PARAMETER_ATTRIBUTE_MAP[attribute]
        return self.coordinator.data[self._subentry_id]['ranges'][p]['values'][0]


class NLWeatherForecast(CoordinatorEntity[NLWeatherUpdateCoordinator], WeatherEntity):
    _attr_should_poll = False
    _attr_attribution = (
        "Forecast data provided by Koninklijk Nederlands Meteorologisch Instituut (KNMI) licensed under CC-BY 4.0"
    )
    _attr_has_entity_name = True
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )
    _hourly_forecast: list[Forecast] = []
    _daily_forecast: list[Forecast] = []

    def __init__(self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)

        self._location = {
            'lat': subentry.data[CONF_LATITUDE],
            'lon': subentry.data[CONF_LONGITUDE]
        }
        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_forecast"
        self._attr_device_info = DeviceInfo(
            name=f"Forecast",
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_forecast")},
            manufacturer="KNMI.nl",
            model="Forecast",
            configuration_url="https://www.knmi.nl",
        )
        self._attr_name = subentry.data[CONF_NAME]

        # Units
        self._attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_visibility_unit = UnitOfLength.KILOMETERS

    @property
    def condition(self) -> str | None:
        # TODO: Handle exceptions
        return CONDITION_FORECAST_MAP[self.coordinator.data['hourly']['forecast'][0]['weatherType']]

    @property
    def native_temperature(self) -> float:
        return self.coordinator.data['hourly']['forecast'][0]['temperature']

    @property
    def native_wind_speed(self) -> float | None:
        return self.coordinator.data['hourly']['forecast'][0]['wind']['speed']

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self.coordinator.data['hourly']['forecast'][0]['wind']['gusts']

    @property
    def wind_bearing(self) -> float | str | None:
        return self.coordinator.data['hourly']['forecast'][0]['wind']['degree']

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast in native units."""
        return [
            cast(Forecast, {
                'datetime': h['dateTime'],
                'condition': CONDITION_FORECAST_MAP[h['weatherType']],  # TODO: Handle exceptions
                'native_temperature': h['temperature'],
                'native_precipitation': h['precipitation']['amount'],
                'precipitation_probability': h['precipitation']['chance'] * 100,
                'native_wind_speed': h['wind']['speed'],
                'native_wind_gust_speed': h['wind']['gusts'],
                'wind_bearing': h['wind']['degree']
            }) for h in self.coordinator.data['hourly']['forecast']
        ]

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return the hourly forecast in native units."""
        return [
            cast(Forecast, {
                'datetime': h['date'],
                'condition': CONDITION_FORECAST_MAP[h['weatherType']],  # TODO: Handle exceptions
                'native_temperature': h['temperature']['max'],
                'native_templow': h['temperature']['min'],
                'native_precipitation': h['precipitation']['amount'],
                'precipitation_probability': h['precipitation']['chance'] * 100
            }) for h in self.coordinator.data['daily']['forecast']
        ]

