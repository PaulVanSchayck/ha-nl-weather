from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import UnitOfTemperature
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
        key="observation_time",
        translation_key="observations_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data["datetime"],
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
        if subentry.subentry_type == "location":
            app_coordinator = config_entry.runtime_data.app_coordinators[subentry_id]

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
            ]

        elif subentry.subentry_type == "station":
            edr_coordinator = config_entry.runtime_data.edr_coordinators[subentry_id]

            entities = [
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
