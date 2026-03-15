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
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, KNMIDirectConfigEntry
from .const import Alert
from .coordinator import NLWeatherEDRCoordinator, NLWeatherUpdateCoordinator


@dataclass(frozen=True)
class AlertSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ObservationSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ForecastTemperatureDescription(SensorEntityDescription):
    day_index: int | None = None
    temp_key: str | None = None


def _get_alert_description(data: dict[str, Any]) -> str | None:
    alerts = data.get("alerts", [])
    if not alerts:
        return "none"
    # TODO: Not dealing with multiple alerts yet
    return alerts[0].get("description")


def _get_alert_level(data: dict[str, Any]) -> Alert:
    # TODO: Not dealing with multiple alerts yet
    try:
        return Alert(data["hourly"]["forecast"][0]["alertLevel"])
    except (KeyError, IndexError, TypeError, ValueError):
        return Alert.NONE


def _get_observation_param(data: dict[str, Any], param: str) -> Any:
    return data.get("params", {}).get(param)


def _get_cloud_coverage(data: dict[str, Any]) -> float | int | None:
    okta = _get_observation_param(data, "nhc")
    if okta is None:
        return None
    if okta == 9:
        return 100
    return round(okta / 8 * 100, 1)


def _get_wind_direction_cardinal(data: dict[str, Any]) -> str | None:
    degrees = _get_observation_param(data, "dd")
    if degrees is None:
        return None
    index = int((float(degrees) + 11.25) / 22.5) % 16
    return VALID_CARDINAL_DIRECTIONS[index]


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
        value_fn=lambda data: _get_observation_param(data, "ta"),
    ),
    ObservationSensorDescription(
        key="humidity",
        translation_key="observations_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, "rh"),
    ),
    ObservationSensorDescription(
        key="visibility",
        translation_key="observations_visibility",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, "zm"),
    ),
    ObservationSensorDescription(
        key="pressure",
        translation_key="observations_pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.HPA,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, "pp"),
    ),
    ObservationSensorDescription(
        key="wind_speed",
        translation_key="observations_wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        value_fn=lambda data: _get_observation_param(data, "ff"),
    ),
    ObservationSensorDescription(
        key="wind_gust",
        translation_key="observations_wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        suggested_display_precision=1,
        value_fn=lambda data: _get_observation_param(data, "gff"),
    ),
    ObservationSensorDescription(
        key="dewpoint",
        translation_key="observations_dewpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: _get_observation_param(data, "td"),
    ),
    ObservationSensorDescription(
        key="wind_direction",
        translation_key="observations_wind_direction",
        icon="mdi:compass-outline",
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        native_unit_of_measurement=DEGREE,
        suggested_display_precision=0,
        value_fn=lambda data: _get_observation_param(data, "dd"),
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


FORECAST_TEMPERATURE_DESCRIPTIONS: list[ForecastTemperatureDescription] = [
    ForecastTemperatureDescription(
        key="forecast_today_high",
        translation_key="forecast_today_high",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        day_index=0,
        temp_key="max",
    ),
    ForecastTemperatureDescription(
        key="forecast_today_low",
        translation_key="forecast_today_low",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        day_index=0,
        temp_key="min",
    ),
    ForecastTemperatureDescription(
        key="forecast_tomorrow_high",
        translation_key="forecast_tomorrow_high",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        day_index=1,
        temp_key="max",
    ),
    ForecastTemperatureDescription(
        key="forecast_tomorrow_low",
        translation_key="forecast_tomorrow_low",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        day_index=1,
        temp_key="min",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: KNMIDirectConfigEntry,
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
                NLForecastTemperatureSensor(
                    app_coordinator, config_entry, subentry, desc
                )
                for desc in FORECAST_TEMPERATURE_DESCRIPTIONS
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
        config_entry: KNMIDirectConfigEntry,
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


class NLObservationSensor(CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: KNMIDirectConfigEntry,
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


class NLForecastTemperatureSensor(
    CoordinatorEntity[NLWeatherUpdateCoordinator], SensorEntity
):
    def __init__(
        self,
        coordinator: NLWeatherUpdateCoordinator,
        config_entry: KNMIDirectConfigEntry,
        subentry: ConfigSubentry,
        desc: ForecastTemperatureDescription,
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
        self._day_index = desc.day_index
        self._temp_key = desc.temp_key

    @property
    def native_value(self):
        return self.coordinator.data["daily"]["forecast"][self._day_index][
            "temperature"
        ][self._temp_key]
