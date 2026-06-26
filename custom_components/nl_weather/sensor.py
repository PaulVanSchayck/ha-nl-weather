from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.weather.significant_change import (
    VALID_CARDINAL_DIRECTIONS,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    UnitOfIrradiance,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .const import (
    Alert,
    ATTR_WEATHER_CLOUD_COVERAGE,
    ATTR_WEATHER_DEW_POINT,
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_PRESSURE,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_VISIBILITY,
    ATTR_WEATHER_WIND_BEARING,
    ATTR_WEATHER_WIND_GUST_SPEED,
    ATTR_WEATHER_WIND_SPEED,
    ATTR_WEATHER_SOLAR_RADIATION,
    ATTR_WEATHER_SUNSHINE,
    ATTR_WEATHER_TEMPERATURE_GRASS,
    ATTR_WEATHER_CLOUD_CEILING,
    ATTR_WEATHER_TEMPERATURE_SOIL,
    PARAMETER_ATTRIBUTE_MAP,
)
from .coordinator import (
    NLWeatherConfigEntry,
    NLWeatherEDRCoordinator,
    NLWeatherUpdateCoordinator,
)


@dataclass(frozen=True)
class AlertSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ObservationSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ForecastSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any] | None = field(default=None, repr=False)


def _get_alert_descriptions(data: dict[str, Any]) -> list[str]:
    alerts = data.get("alerts", [])
    return [
        description.strip()
        for alert in alerts
        if isinstance((description := alert.get("description")), str)
        and description.strip()
    ]


def _get_alert_description(data: dict[str, Any]) -> str | None:
    alerts = _get_alert_descriptions(data)
    if not alerts:
        return "none"
    if len(alerts) == 1:
        return "1 alert"
    return f"{len(alerts)} alerts"


def _get_alert_attributes(data: dict[str, Any]) -> dict[str, Any]:
    alerts = _get_alert_descriptions(data)
    return {
        "alert_count": len(alerts),
        "alerts": alerts,
        "description": ". ".join(alerts),
    }


def _get_alert_level(data: dict[str, Any]) -> Alert:
    # TODO: Is the first alert always the highest?
    try:
        return Alert(data["hourly"]["forecast"][0]["alertLevel"])
    except (KeyError, IndexError, TypeError, ValueError):
        return Alert.NONE


def _get_observation_param(
    data: dict[str, Any],
    weather_attribute: str,
) -> Any:
    return data.get("params", {}).get(PARAMETER_ATTRIBUTE_MAP[weather_attribute])


def _get_cloud_coverage(data: dict[str, Any]) -> float | int | None:
    okta = _get_observation_param(data, ATTR_WEATHER_CLOUD_COVERAGE)
    if okta is None:
        return None
    if okta == 9:
        return 100
    return round(okta / 8 * 100, 1)


def _get_wind_direction_cardinal(data: dict[str, Any]) -> str | None:
    degrees = _get_observation_param(data, ATTR_WEATHER_WIND_BEARING)
    if degrees is None:
        return None
    index = int((float(degrees) + 11.25) / 22.5) % 16
    return VALID_CARDINAL_DIRECTIONS[index]


def _get_forecast_temperature(
    day_index: int, temp_key: str
) -> Callable[[dict[str, Any]], Any]:
    """Return a value_fn that extracts a forecast temperature.

    The returned callable accepts the full coordinator data dict.
    """

    def _fn(data: dict[str, Any]) -> Any:
        try:
            return data["daily"]["forecast"][day_index]["temperature"][temp_key]
        except (KeyError, IndexError, TypeError):
            return None

    return _fn


ALERT_SENSOR_DESCRIPTIONS: list[AlertSensorDescription] = [
    AlertSensorDescription(
        key="alert",
        translation_key="weather_alert",
        icon="mdi:weather-cloudy-alert",
        value_fn=_get_alert_description,
    ),
    AlertSensorDescription(
        key="alert_level",
        translation_key="weather_alert_level",
        icon="mdi:alert-box",
        device_class=SensorDeviceClass.ENUM,
        options=[a.value for a in Alert],
        value_fn=_get_alert_level,
    ),
]


OBSERVATION_SENSOR_DESCRIPTIONS: list[ObservationSensorDescription] = [
    ObservationSensorDescription(
        key="temperature",
        translation_key="observations_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: _get_observation_param(data, ATTR_WEATHER_TEMPERATURE),
    ),
    ObservationSensorDescription(
        key="humidity",
        translation_key="observations_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, ATTR_WEATHER_HUMIDITY),
    ),
    ObservationSensorDescription(
        key="visibility",
        translation_key="observations_visibility",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, ATTR_WEATHER_VISIBILITY),
    ),
    ObservationSensorDescription(
        key="pressure",
        translation_key="observations_pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.HPA,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, ATTR_WEATHER_PRESSURE),
    ),
    ObservationSensorDescription(
        key="wind_speed",
        translation_key="observations_wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        value_fn=lambda data: _get_observation_param(data, ATTR_WEATHER_WIND_SPEED),
    ),
    ObservationSensorDescription(
        key="wind_gust",
        translation_key="observations_wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        value_fn=lambda data: _get_observation_param(
            data, ATTR_WEATHER_WIND_GUST_SPEED
        ),
    ),
    ObservationSensorDescription(
        key="dewpoint",
        translation_key="observations_dewpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: _get_observation_param(data, ATTR_WEATHER_DEW_POINT),
    ),
    ObservationSensorDescription(
        key="wind_direction",
        translation_key="observations_wind_direction",
        icon="mdi:compass-outline",
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        native_unit_of_measurement=DEGREE,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, ATTR_WEATHER_WIND_BEARING),
    ),
    ObservationSensorDescription(
        key="cloud_coverage",
        translation_key="observations_cloud_coverage",
        icon="mdi:cloud-percent",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=_get_cloud_coverage,
    ),
    ObservationSensorDescription(
        key="solar_radiation",
        translation_key="observations_solar_radiation",
        device_class=SensorDeviceClass.IRRADIANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(
            data, ATTR_WEATHER_SOLAR_RADIATION
        ),
    ),
    ObservationSensorDescription(
        key="sunshine",
        translation_key="observations_sunshine",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, ATTR_WEATHER_SUNSHINE),
    ),
    ObservationSensorDescription(
        key="temperature_grass",
        translation_key="observations_temperature_grass",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: _get_observation_param(
            data, ATTR_WEATHER_TEMPERATURE_GRASS
        ),
    ),
    ObservationSensorDescription(
        key="cloud_ceiling",
        translation_key="observations_cloud_ceiling",
        icon="mdi:cloud-arrow-up",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.FEET,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, ATTR_WEATHER_CLOUD_CEILING),
    ),
    ObservationSensorDescription(
        key="temperature_soil",
        translation_key="observations_temperature_soil",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: _get_observation_param(
            data, ATTR_WEATHER_TEMPERATURE_SOIL
        ),
    ),
    ObservationSensorDescription(
        key="wind_direction_cardinal",
        translation_key="observations_wind_direction_cardinal",
        device_class=SensorDeviceClass.ENUM,
        options=VALID_CARDINAL_DIRECTIONS,
        value_fn=_get_wind_direction_cardinal,
    ),
    ObservationSensorDescription(
        key="station_distance",
        translation_key="observations_station_distance",
        device_class=SensorDeviceClass.DISTANCE,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("distance"),
    ),
    ObservationSensorDescription(
        key="station_name",
        translation_key="observations_station_name",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("station_name"),
    ),
    ObservationSensorDescription(
        key="observation_time",
        translation_key="observations_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("datetime"),
    ),
]


FORECAST_SENSOR_DESCRIPTIONS: list[ForecastSensorDescription] = [
    ForecastSensorDescription(
        key="forecast_today_high",
        translation_key="forecast_today_high",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_get_forecast_temperature(0, "max"),
    ),
    ForecastSensorDescription(
        key="forecast_today_low",
        translation_key="forecast_today_low",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_get_forecast_temperature(0, "min"),
    ),
    ForecastSensorDescription(
        key="forecast_tomorrow_high",
        translation_key="forecast_tomorrow_high",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_get_forecast_temperature(1, "max"),
    ),
    ForecastSensorDescription(
        key="forecast_tomorrow_low",
        translation_key="forecast_tomorrow_low",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_get_forecast_temperature(1, "min"),
    ),
    ForecastSensorDescription(
        key="heat_force_index",
        translation_key="heat_force_index",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sun-thermometer",
        value_fn=lambda data: data["hourly"]["forecast"][0].get("heatIndex", None),
    ),
    ForecastSensorDescription(
        key="heat_force_index_today",
        translation_key="heat_force_index_today",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sun-thermometer-outline",
        value_fn=lambda data: data["daily"]["forecast"][0].get("heatIndex", None),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NLWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry_id, subentry in config_entry.subentries.items():
        entities = []
        app_coordinator = config_entry.runtime_data.app_coordinators[subentry_id]
        edr_coordinator = config_entry.runtime_data.edr_coordinators[subentry_id]

        entities = [
            *[
                NLAlertSensor(app_coordinator, config_entry, subentry, desc)
                for desc in ALERT_SENSOR_DESCRIPTIONS
            ],
            *[
                NLForecastSensor(app_coordinator, config_entry, subentry, desc)
                for desc in FORECAST_SENSOR_DESCRIPTIONS
            ],
            *[
                NLObservationSensor(edr_coordinator, config_entry, subentry, desc)
                for desc in OBSERVATION_SENSOR_DESCRIPTIONS
            ],
        ]

        async_add_entities(entities, config_subentry_id=subentry_id)


class NLAlertSensor(CoordinatorEntity[NLWeatherUpdateCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: NLWeatherUpdateCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
        desc: AlertSensorDescription,
    ) -> None:
        super().__init__(coordinator)

        self.entity_description = desc
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_{desc.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self._value_fn = desc.value_fn

    @property
    def native_value(self):
        return self._value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "alert" or self.coordinator.data is None:
            return None
        return _get_alert_attributes(self.coordinator.data)


class NLObservationSensor(CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
        desc: ObservationSensorDescription,
    ) -> None:
        super().__init__(coordinator)

        self.entity_description = desc
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_{desc.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self._subentry_id = subentry.subentry_id
        self._value_fn = desc.value_fn

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self._value_fn(self.coordinator.data)


class NLForecastSensor(CoordinatorEntity[NLWeatherUpdateCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: NLWeatherUpdateCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
        desc: ForecastSensorDescription,
    ) -> None:
        super().__init__(coordinator)

        self.entity_description = desc
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_{desc.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self._value_fn = desc.value_fn

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self._value_fn(self.coordinator.data)
