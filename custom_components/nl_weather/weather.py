"""Weather entity"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, cast

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_SUNNY,
    ATTR_CONDITION_WINDY,
    ATTR_CONDITION_WINDY_VARIANT,
    ATTR_WEATHER_CLOUD_COVERAGE,
    ATTR_WEATHER_DEW_POINT,
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_PRESSURE,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_VISIBILITY,
    ATTR_WEATHER_WIND_BEARING,
    ATTR_WEATHER_WIND_GUST_SPEED,
    ATTR_WEATHER_WIND_SPEED,
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import (
    CONF_NAME,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.helpers import entity_platform, sun
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import utcnow

from .const import (
    ATTR_WEATHER_CONDITION,
    CONDITION_FORECAST_MAP,
    CONDITION_MAP,
    DOMAIN,
    PARAMETER_ATTRIBUTE_MAP,
    NLWeatherEntityFeature,
)
from .coordinator import (
    NLWeatherConfigEntry,
    NLWeatherEDRCoordinator,
    NLWeatherNowcastCoordinator,
    NLWeatherUpdateCoordinator,
)

SERVICE_GET_MINUTE_FORECAST = "get_minute_forecast"
_LOGGER = logging.getLogger(__name__)


class NLWeatherObservationDataMixin:
    """Shared observation-backed weather logic."""

    observation_coordinator: NLWeatherEDRCoordinator
    hass: HomeAssistant

    def get_latest_range_value(self, attribute: str) -> float | None:
        """Return the latest observation value for an attribute."""
        if self.observation_coordinator.data is None:
            return None

        parameter = PARAMETER_ATTRIBUTE_MAP[attribute]
        if parameter not in self.observation_coordinator.data["params"]:
            return None
        return self.observation_coordinator.data["params"][parameter]

    def _observation_available(self) -> bool:
        return (
            self.get_latest_range_value(ATTR_WEATHER_CONDITION) is not None
            and self.get_latest_range_value(ATTR_WEATHER_VISIBILITY) is not None
            and self.get_latest_range_value(ATTR_WEATHER_CLOUD_COVERAGE) is not None
        )

    def _observation_condition(self) -> str | None:
        """Return the current condition from observations."""
        if (
            condition_code := self.get_latest_range_value(ATTR_WEATHER_CONDITION)
        ) is None:
            return None

        try:
            condition = CONDITION_MAP[condition_code]
        except KeyError:
            _LOGGER.exception("Unknown condition")
            return ATTR_CONDITION_SUNNY

        visibility = self._observation_visibility()
        if (
            condition == ATTR_CONDITION_FOG
            and visibility is not None
            and visibility > 1000
        ):
            condition = ATTR_CONDITION_CLOUDY

        cloud_coverage = self._observation_cloud_coverage()
        wind_speed = self._observation_wind_speed()
        wind_gust_speed = self._observation_wind_gust_speed()

        if condition == ATTR_CONDITION_CLOUDY and cloud_coverage is not None:
            if cloud_coverage <= 75:
                condition = ATTR_CONDITION_PARTLYCLOUDY
            if cloud_coverage <= 25:
                condition = ATTR_CONDITION_SUNNY

            if (
                wind_speed is not None
                and wind_speed > 12
                or wind_gust_speed is not None
                and wind_gust_speed > 20
            ):
                if cloud_coverage <= 75:
                    condition = ATTR_CONDITION_WINDY
                else:
                    condition = ATTR_CONDITION_WINDY_VARIANT

        if condition == ATTR_CONDITION_SUNNY and not sun.is_up(self.hass):
            condition = ATTR_CONDITION_CLEAR_NIGHT

        return condition

    def _observation_temperature(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_TEMPERATURE)

    def _observation_cloud_coverage(self) -> float | None:
        if (
            cloud_coverage := self.get_latest_range_value(ATTR_WEATHER_CLOUD_COVERAGE)
        ) is None:
            return None
        return cloud_coverage / 8 * 100

    def _observation_wind_speed(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_WIND_SPEED)

    def _observation_visibility(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_VISIBILITY)

    def _observation_pressure(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_PRESSURE)

    def _observation_wind_gust_speed(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_WIND_GUST_SPEED)

    def _observation_wind_bearing(self) -> float | str | None:
        return self.get_latest_range_value(ATTR_WEATHER_WIND_BEARING)

    def _observation_dew_point(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_DEW_POINT)

    def _observation_humidity(self) -> float | None:
        return self.get_latest_range_value(ATTR_WEATHER_HUMIDITY)


class NLWeatherForecastDataMixin:
    """Shared forecast-backed weather logic."""

    forecast_coordinator: NLWeatherUpdateCoordinator
    nowcast_coordinator: NLWeatherNowcastCoordinator

    def _forecast_available(self) -> bool:
        return self._current_hourly_forecast() is not None

    def _current_hourly_forecast(self) -> dict[str, Any] | None:
        if self.forecast_coordinator.data is None:
            return None

        hourly_forecast = self.forecast_coordinator.data.get("hourly", {}).get(
            "forecast"
        )
        if not hourly_forecast:
            return None
        return hourly_forecast[0]

    def _map_forecast_condition(self, weather_type: str) -> str:
        try:
            return CONDITION_FORECAST_MAP[weather_type]
        except KeyError:
            _LOGGER.warning("Unknown forecast condition: %s", weather_type)
            return ATTR_CONDITION_SUNNY

    def _forecast_condition(self) -> str | None:
        if (current_forecast := self._current_hourly_forecast()) is None:
            return None
        return self._map_forecast_condition(current_forecast["weatherType"])

    def _forecast_temperature(self) -> float | None:
        if (current_forecast := self._current_hourly_forecast()) is None:
            return None
        return current_forecast["temperature"]

    def _forecast_wind_speed(self) -> float | None:
        if (current_forecast := self._current_hourly_forecast()) is None:
            return None
        return current_forecast["wind"]["speed"]

    def _forecast_wind_gust_speed(self) -> float | None:
        if (current_forecast := self._current_hourly_forecast()) is None:
            return None
        return current_forecast["wind"]["gusts"]

    def _forecast_wind_bearing(self) -> float | str | None:
        if (current_forecast := self._current_hourly_forecast()) is None:
            return None
        return current_forecast["wind"]["degree"]

    def _hourly_forecast_item(self, forecast: dict[str, Any]) -> Forecast:
        return cast(
            Forecast,
            {
                "datetime": forecast["dateTime"],
                "condition": self._map_forecast_condition(forecast["weatherType"]),
                "native_temperature": forecast["temperature"],
                "native_precipitation": forecast["precipitation"]["amount"],
                "precipitation_probability": forecast["precipitation"]["chance"] * 100,
                "native_wind_speed": forecast["wind"]["speed"],
                "native_wind_gust_speed": forecast["wind"]["gusts"],
                "wind_bearing": forecast["wind"]["degree"],
                "heat_force_index": forecast["heatIndex"],
            },
        )

    def _daily_forecast_item(self, forecast: dict[str, Any]) -> Forecast:
        return cast(
            Forecast,
            {
                "datetime": forecast["date"],
                "condition": self._map_forecast_condition(forecast["weatherType"]),
                "native_temperature": forecast["temperature"]["max"],
                "native_templow": forecast["temperature"]["min"],
                "native_precipitation": forecast["precipitation"]["amount"],
                "precipitation_probability": forecast["precipitation"]["chance"] * 100,
                "native_wind_speed": forecast["wind"]["speed"],
                "native_wind_gust_speed": forecast["wind"]["gusts"],
                "wind_bearing": forecast["wind"]["degree"],
                "uv_index": forecast["uv_index"],
                "heat_force_index": forecast["heatIndex"],
            },
        )

    async def _async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast in native units."""
        if self.forecast_coordinator.data is None:
            return None

        return [
            self._hourly_forecast_item(forecast)
            for forecast in self.forecast_coordinator.data["hourly"]["forecast"]
        ]

    async def _async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast in native units."""
        if self.forecast_coordinator.data is None:
            return None

        return [
            self._daily_forecast_item(forecast)
            for forecast in self.forecast_coordinator.data["daily"]["forecast"]
        ]

    async def _async_get_minute_forecast(self) -> dict[str, list[dict[str, Any]]]:
        """Return minute forecast."""
        if self.nowcast_coordinator is None or self.nowcast_coordinator.data is None:
            return {"forecast": []}

        now = utcnow()
        result: list[dict[str, Any]] = []
        for item in self.nowcast_coordinator.data:
            for offset in range(5):
                forecast_time = item["datetime"] + timedelta(minutes=offset)
                if forecast_time >= now:
                    result.append(
                        {
                            "datetime": forecast_time,
                            "precipitation": item.get("precipitation", 0),
                        }
                    )

        return {"forecast": result}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NLWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        name=SERVICE_GET_MINUTE_FORECAST,
        schema=None,
        func="async_get_minute_forecast",
        supports_response=SupportsResponse.ONLY,
    )

    for subentry_id, subentry in config_entry.subentries.items():
        entities = [
            NLWeatherForecast(
                config_entry.runtime_data.app_coordinators[subentry_id],
                config_entry.runtime_data.nowcast_coordinators[subentry_id],
                config_entry,
                subentry,
            ),
            NLWeatherObservations(
                config_entry.runtime_data.edr_coordinators[subentry_id],
                config_entry,
                subentry,
            ),
            NLWeatherCombined(
                config_entry.runtime_data.edr_coordinators[subentry_id],
                config_entry.runtime_data.app_coordinators[subentry_id],
                config_entry.runtime_data.nowcast_coordinators[subentry_id],
                config_entry,
                subentry,
            ),
        ]
        async_add_entities(
            entities,
            config_subentry_id=subentry_id,
        )


class NLWeatherObservations(
    CoordinatorEntity[NLWeatherEDRCoordinator],
    WeatherEntity,
    NLWeatherObservationDataMixin,
):
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = False
    _attr_attribution = "Meteorological observations provided by Koninklijk Nederlands Meteorologisch Instituut (KNMI) licensed under CC-BY 4.0"
    _attr_has_entity_name = True
    _latest_coverage = None

    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)
        self.observation_coordinator = coordinator
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_observations"
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_translation_key = "observations"
        self._attr_has_entity_name = True

        # Units
        self._attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_visibility_unit = UnitOfLength.METERS

    @property
    def available(self) -> bool:
        return self._observation_available()

    @property
    def condition(self) -> str | None:
        return self._observation_condition()

    @property
    def native_temperature(self) -> float | None:
        return self._observation_temperature()

    @property
    def cloud_coverage(self) -> float | None:
        return self._observation_cloud_coverage()

    @property
    def native_wind_speed(self) -> float | None:
        return self._observation_wind_speed()

    @property
    def native_visibility(self) -> float | None:
        return self._observation_visibility()

    @property
    def native_pressure(self) -> float | None:
        return self._observation_pressure()

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self._observation_wind_gust_speed()

    @property
    def wind_bearing(self) -> float | str | None:
        return self._observation_wind_bearing()

    @property
    def native_dew_point(self) -> float | None:
        return self._observation_dew_point()

    @property
    def humidity(self) -> float | None:
        return self._observation_humidity()


class NLWeatherForecast(
    CoordinatorEntity[NLWeatherUpdateCoordinator],
    WeatherEntity,
    NLWeatherForecastDataMixin,
):
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = False
    _attr_attribution = "Forecast data provided by Koninklijk Nederlands Meteorologisch Instituut (KNMI) licensed under CC-BY 4.0"
    _attr_has_entity_name = True
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY
        | WeatherEntityFeature.FORECAST_HOURLY
        | NLWeatherEntityFeature.FORECAST_MINUTE
    )

    def __init__(
        self,
        coordinator: NLWeatherUpdateCoordinator,
        nowcast_coordinator: NLWeatherNowcastCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self.forecast_coordinator = coordinator
        self.nowcast_coordinator = nowcast_coordinator
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_forecast"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
            name=f"Weer {subentry.data[CONF_NAME]}",
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="KNMI.nl",
            model="Waarnemingen, verwachtingen & waarschuwingen",
            configuration_url="https://www.knmi.nl",
        )
        self._attr_translation_key = "forecast"
        self._attr_has_entity_name = True

        # Units
        self._attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_visibility_unit = UnitOfLength.KILOMETERS

    @property
    def condition(self) -> str | None:
        return self._forecast_condition()

    @property
    def native_temperature(self) -> float | None:
        return self._forecast_temperature()

    @property
    def native_wind_speed(self) -> float | None:
        return self._forecast_wind_speed()

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self._forecast_wind_gust_speed()

    @property
    def wind_bearing(self) -> float | str | None:
        return self._forecast_wind_bearing()

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        return await self._async_forecast_hourly()

    async def async_forecast_daily(self) -> list[Forecast] | None:
        return await self._async_forecast_daily()

    async def async_get_minute_forecast(self) -> dict[str, list[dict[str, Any]]]:
        return await self._async_get_minute_forecast()


class NLWeatherCombined(
    WeatherEntity,
    NLWeatherObservationDataMixin,
    NLWeatherForecastDataMixin,
):
    """Weather entity combining observation and forecast sources."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_attribution = "Forecast and observation data provided by Koninklijk Nederlands Meteorologisch Instituut (KNMI) licensed under CC-BY 4.0"
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY
        | WeatherEntityFeature.FORECAST_HOURLY
        | NLWeatherEntityFeature.FORECAST_MINUTE
    )

    def __init__(
        self,
        observation_coordinator: NLWeatherEDRCoordinator,
        forecast_coordinator: NLWeatherUpdateCoordinator,
        nowcast_coordinator: NLWeatherNowcastCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        self.observation_coordinator = observation_coordinator
        self.forecast_coordinator = forecast_coordinator
        self.nowcast_coordinator = nowcast_coordinator

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_weather"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )

        # Units
        self._attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_visibility_unit = UnitOfLength.METERS

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        self.async_on_remove(
            self.observation_coordinator.async_add_listener(self._source_updated)
        )
        self.async_on_remove(
            self.forecast_coordinator.async_add_listener(self._source_updated)
        )

    @callback
    def _source_updated(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._observation_available() or self._forecast_available()

    @property
    def condition(self) -> str | None:
        if (condition := self._observation_condition()) is None:
            return condition
        return self._forecast_condition()

    @property
    def native_temperature(self) -> float | None:
        if (temperature := self._observation_temperature()) is not None:
            return temperature
        return self._forecast_temperature()

    @property
    def native_wind_speed(self) -> float | None:
        if (wind_speed := self._observation_wind_speed()) is not None:
            # Observations are in m/s, forecast in km/h
            return wind_speed * 3.6
        return self._forecast_wind_speed()

    @property
    def native_wind_gust_speed(self) -> float | None:
        if (wind_gust_speed := self._observation_wind_gust_speed()) is not None:
            # Observations are in m/s, forecast in km/h
            return wind_gust_speed * 3.6
        return self._forecast_wind_gust_speed()

    @property
    def wind_bearing(self) -> float | str | None:
        if (wind_bearing := self._observation_wind_bearing()) is not None:
            return wind_bearing
        return self._forecast_wind_bearing()

    @property
    def cloud_coverage(self) -> float | None:
        return self._observation_cloud_coverage()

    @property
    def native_visibility(self) -> float | None:
        return self._observation_visibility()

    @property
    def native_pressure(self) -> float | None:
        return self._observation_pressure()

    @property
    def native_dew_point(self) -> float | None:
        return self._observation_dew_point()

    @property
    def humidity(self) -> float | None:
        return self._observation_humidity()

    async def async_forecast_daily(self) -> list[Forecast] | None:
        return await self._async_forecast_daily()

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        return await self._async_forecast_hourly()

    async def async_get_minute_forecast(self) -> dict[str, list[dict[str, Any]]]:
        return await self._async_get_minute_forecast()
