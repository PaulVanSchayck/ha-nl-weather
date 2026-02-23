from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import UnitOfLength, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, KNMIDirectConfigEntry
from .const import Alert
from .coordinator import NLWeatherEDRCoordinator, NLWeatherUpdateCoordinator


@dataclass(frozen=True)
class AlertSensorDescription:
    key: str
    translation_key: str
    value_fn: Callable[[dict[str, Any]], Any]
    icon: str | None = None
    device_class: SensorDeviceClass | None = None
    options: list[str] | None = None


@dataclass(frozen=True)
class ObservationSensorDescription:
    key: str
    translation_key: str
    value_fn: Callable[[dict[str, Any], str], Any]
    device_class: SensorDeviceClass | None = None
    native_unit: str | None = None
    suggested_display_precision: int | None = None
    entity_category: EntityCategory | None = None


@dataclass(frozen=True)
class ForecastTemperatureDescription:
    key: str
    translation_key: str
    day_index: int
    temp_key: str


def _get_alert_description(data: dict[str, Any]) -> str | None:
    alerts = data.get("alerts", [])
    if not alerts:
        return "none"
    return alerts[0].get("description")


def _get_alert_level(data: dict[str, Any]) -> Alert | None:
    return Alert(data["hourly"]["forecast"][0]["alertLevel"])


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
        key="station_distance",
        translation_key="observations_station_distance",
        device_class=SensorDeviceClass.DISTANCE,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        value_fn=lambda data, subentry_id: data[subentry_id]["distance"],
    ),
    ObservationSensorDescription(
        key="station_name",
        translation_key="observations_station_name",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data, subentry_id: data[subentry_id]["station_name"],
    ),
    ObservationSensorDescription(
        key="time",
        translation_key="observations_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data, subentry_id: data[subentry_id]["datetime"],
    ),
]


FORECAST_TEMPERATURE_DESCRIPTIONS: list[ForecastTemperatureDescription] = [
    ForecastTemperatureDescription(
        key="forecast_today_high",
        translation_key="forecast_today_high",
        day_index=0,
        temp_key="max",
    ),
    ForecastTemperatureDescription(
        key="forecast_today_low",
        translation_key="forecast_today_low",
        day_index=0,
        temp_key="min",
    ),
    ForecastTemperatureDescription(
        key="forecast_tomorrow_high",
        translation_key="forecast_tomorrow_high",
        day_index=1,
        temp_key="max",
    ),
    ForecastTemperatureDescription(
        key="forecast_tomorrow_low",
        translation_key="forecast_tomorrow_low",
        day_index=1,
        temp_key="min",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: KNMIDirectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    obs_coordinator = config_entry.runtime_data.obs_coordinator
    for subentry_id, subentry in config_entry.subentries.items():
        coordinator = config_entry.runtime_data.coordinators[subentry_id]

        entities = [
            *[
                NLAlertSensor(coordinator, config_entry, subentry, desc)
                for desc in ALERT_SENSOR_DESCRIPTIONS
            ],
            *[
                NLObservationSensor(obs_coordinator, config_entry, subentry, desc)
                for desc in OBSERVATION_SENSOR_DESCRIPTIONS
            ],
            *[
                NLForecastTemperatureSensor(coordinator, config_entry, subentry, desc)
                for desc in FORECAST_TEMPERATURE_DESCRIPTIONS
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

        self.entity_description = SensorEntityDescription(
            key=desc.key,
            translation_key=desc.translation_key,
            icon=desc.icon,
            device_class=desc.device_class,
            options=desc.options,
        )
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

        self.entity_description = SensorEntityDescription(
            key=desc.key,
            translation_key=desc.translation_key,
        )
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_{desc.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        if desc.device_class is not None:
            self.device_class = desc.device_class
        if desc.native_unit is not None:
            self.native_unit_of_measurement = desc.native_unit
        if desc.suggested_display_precision is not None:
            self.suggested_display_precision = desc.suggested_display_precision
        if desc.entity_category is not None:
            self._attr_entity_category = desc.entity_category
        self._subentry_id = subentry.subentry_id
        self._value_fn = desc.value_fn

    @property
    def native_value(self):
        return self._value_fn(self.coordinator.data, self._subentry_id)


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

        self.entity_description = SensorEntityDescription(
            key=desc.key,
            translation_key=desc.translation_key,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        )
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
