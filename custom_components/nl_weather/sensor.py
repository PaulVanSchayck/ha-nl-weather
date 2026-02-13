"""Sensor platform for NL Weather."""

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
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

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: KNMIDirectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    obs_coordinator = config_entry.runtime_data.obs_coordinator
    for subentry_id, subentry in config_entry.subentries.items():
        coordinator = config_entry.runtime_data.coordinators[subentry_id]

        entities = [
            NLWeatherAlertSensor(coordinator, config_entry, subentry),
            NLWeatherAlertLevelSensor(coordinator, config_entry, subentry),
            NLObservationStationDistanceSensor(obs_coordinator, config_entry, subentry),
            NLObservationStationNameSensor(obs_coordinator, config_entry, subentry),
            NLObservationTimeSensor(obs_coordinator, config_entry, subentry),
            NLObservationCloudCoverageSensor(obs_coordinator, config_entry, subentry),
            NLObservationWindDirectionSensor(obs_coordinator, config_entry, subentry),
        ]

        # Add generic range-based observation sensors
        for desc in OBSERVATION_DESCRIPTIONS:
            entities.append(
                NLObservationRangeSensor(obs_coordinator, config_entry, subentry, desc)
            )

        async_add_entities(entities, config_subentry_id=subentry_id)


class NLWeatherAlertSensor(CoordinatorEntity[NLWeatherUpdateCoordinator], SensorEntity):
    """Sensor for weather alerts."""

    def __init__(
        self,
        coordinator: NLWeatherUpdateCoordinator,
        config_entry: KNMIDirectConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self.entity_description = SensorEntityDescription(
            key="alert",
            icon="mdi:weather-cloudy-alert",
            translation_key="weather_alert",
        )

    @property
    def native_value(self):
        """Return the alert description."""
        try:
            alerts = self.coordinator.data.get("alerts", [])
            if len(alerts) == 0:
                return "none"
            return alerts[0]["description"]
        except (KeyError, IndexError, TypeError) as err:
            _LOGGER.warning("Error accessing alert data: %s", err)
            return None


class NLWeatherAlertLevelSensor(
    CoordinatorEntity[NLWeatherUpdateCoordinator], SensorEntity
):
    """Sensor for weather alert level."""

    def __init__(
        self,
        coordinator: NLWeatherUpdateCoordinator,
        config_entry: KNMIDirectConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_alert_level"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self.entity_description = SensorEntityDescription(
            key="alert_level",
            options=[a.value for a in Alert],
            icon="mdi:alert-box",
            translation_key="weather_alert_level",
            device_class=SensorDeviceClass.ENUM,
        )

    @property
    def native_value(self):
        """Return the alert level enum value."""
        try:
            alert_level = self.coordinator.data["hourly"]["forecast"][0]["alertLevel"]
            return Alert(alert_level)
        except (KeyError, IndexError, ValueError, TypeError) as err:
            _LOGGER.warning("Error accessing alert level data: %s", err)
            return None


class NLObservationStationDistanceSensor(
    CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity
):
    """Sensor for observation station distance."""

    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: KNMIDirectConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_station_distance"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_description = SensorEntityDescription(
            key="station_distance",
            translation_key="observations_station_distance",
        )
        self.device_class = SensorDeviceClass.DISTANCE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._subentry_id = subentry.subentry_id
        self.native_unit_of_measurement = UnitOfLength.KILOMETERS
        self.suggested_display_precision = 1

    @property
    def native_value(self):
        """Return the station distance value."""
        try:
            return self.coordinator.data[self._subentry_id]["distance"]
        except (KeyError, TypeError) as err:
            _LOGGER.debug("Error accessing station distance data: %s", err)
            return None


class NLObservationStationNameSensor(
    CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity
):
    """Sensor for observation station name."""

    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: KNMIDirectConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_station_name"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_description = SensorEntityDescription(
            key="station_name",
            translation_key="observations_station_name",
        )
        self._subentry_id = subentry.subentry_id

    @property
    def native_value(self):
        """Return the station name."""
        try:
            return self.coordinator.data[self._subentry_id]["station_name"]
        except (KeyError, TypeError) as err:
            _LOGGER.debug("Error accessing station name data: %s", err)
            return None


class NLObservationTimeSensor(CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity):
    """Sensor for observation time."""

    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: KNMIDirectConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_observation_time"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_description = SensorEntityDescription(
            key="time",
            translation_key="observations_time",
        )
        self.device_class = SensorDeviceClass.TIMESTAMP
        self._subentry_id = subentry.subentry_id

    @property
    def native_value(self):
        """Return the observation datetime."""
        try:
            return self.coordinator.data[self._subentry_id]["datetime"]
        except (KeyError, TypeError) as err:
            _LOGGER.debug("Error accessing observation time data: %s", err)
            return None


class NLObservationCloudCoverageSensor(
    CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity
):
    """Sensor for cloud coverage in okta, converted to percentage."""

    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: KNMIDirectConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_cloud_coverage"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self.entity_description = SensorEntityDescription(
            key="cloud_coverage",
            translation_key="observations_cloud_coverage",
        )
        self.device_class = None
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._subentry_id = subentry.subentry_id
        self.native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self):
        """Return cloud coverage as percentage (0-100) from okta value (0-8, or 9 for obscured).

        Okta scale:
        - 0: 0/8 (0% coverage)
        - 1-7: 1/8 to 7/8 (12.5% to 87.5%)
        - 8: 8/8 (100% fully covered)
        - 9: Sky obscured by fog/phenomena (treated as 100%)
        """
        try:
            if self.coordinator.data is None:
                return None
            okta = self.coordinator.data[self._subentry_id]["ranges"]["nhc"]["values"][
                0
            ]
            if okta is None:
                return None
            if okta == 9:
                # Sky obscured by fog or other phenomena - treat as 100% coverage
                return 100
            else:
                # Standard okta scale (0-8): convert eighths to percentage
                return round(okta / 8 * 100, 1)
        except (KeyError, IndexError, TypeError) as err:
            _LOGGER.debug("Error accessing cloud coverage data: %s", err)
            return None


class NLObservationWindDirectionSensor(
    CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity
):
    """Sensor converting wind azimuth degrees to cardinal direction (ENUM)."""

    CARDINALS = [
        "n",
        "nne",
        "ne",
        "ene",
        "e",
        "ese",
        "se",
        "sse",
        "s",
        "ssw",
        "sw",
        "wsw",
        "w",
        "wnw",
        "nw",
        "nnw",
    ]

    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: KNMIDirectConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_wind_direction"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self.entity_description = SensorEntityDescription(
            key="wind_direction",
            translation_key="observations_wind_direction",
            device_class=SensorDeviceClass.ENUM,
            options=self.CARDINALS,
        )
        self._attr_state_class = None
        self._subentry_id = subentry.subentry_id

    @staticmethod
    def _degrees_to_cardinal(deg: float) -> str:
        index = int((deg + 11.25) / 22.5) % 16
        return NLObservationWindDirectionSensor.CARDINALS[index]

    @property
    def native_value(self) -> str | None:
        try:
            if self.coordinator.data is None:
                return None
            deg = self.coordinator.data[self._subentry_id]["ranges"]["dd"]["values"][0]
            if deg is None:
                return None
            return self._degrees_to_cardinal(float(deg))
        except (KeyError, IndexError, TypeError, ValueError) as err:
            _LOGGER.debug("Error accessing wind azimuth data: %s", err)
            return None


@dataclass
class ObservationDescription:
    """Description of an observation sensor."""

    key: str
    param: str
    device_class: SensorDeviceClass | None = None
    native_unit: Any = None
    translation_key: str | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    suggested_display_precision: int | None = None


# Descriptions for range-based observation sensors (read from EDR ranges)
OBSERVATION_DESCRIPTIONS: list[ObservationDescription] = [
    ObservationDescription(
        key="temperature",
        param="ta",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.CELSIUS,
        translation_key="observations_temperature",
        suggested_display_precision=1,
    ),
    ObservationDescription(
        key="humidity",
        param="rh",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit=PERCENTAGE,
        translation_key="observations_humidity",
        suggested_display_precision=0,
    ),
    ObservationDescription(
        key="visibility",
        param="vv",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit=UnitOfLength.METERS,
        translation_key="observations_visibility",
        suggested_display_precision=0,
    ),
    ObservationDescription(
        key="pressure",
        param="pp",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit=UnitOfPressure.HPA,
        translation_key="observations_pressure",
        suggested_display_precision=0,
    ),
    ObservationDescription(
        key="wind_speed",
        param="ff",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit=UnitOfSpeed.METERS_PER_SECOND,
        translation_key="observations_wind_speed",
        suggested_display_precision=1,
    ),
    ObservationDescription(
        key="wind_gust",
        param="gff",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit=UnitOfSpeed.METERS_PER_SECOND,
        translation_key="observations_wind_gust",
        suggested_display_precision=1,
    ),
    ObservationDescription(
        key="dewpoint",
        param="td",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit=UnitOfTemperature.CELSIUS,
        translation_key="observations_dewpoint",
        suggested_display_precision=1,
    ),
    ObservationDescription(
        key="wind_azimuth",
        param="dd",
        device_class=SensorDeviceClass.WIND_DIRECTION,
        native_unit=DEGREE,
        translation_key="observations_wind_azimuth",
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        suggested_display_precision=0,
    ),
]


class NLObservationRangeSensor(
    CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity
):
    """Generic sensor for EDR range-based observations."""

    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: KNMIDirectConfigEntry,
        subentry: ConfigSubentry,
        desc: ObservationDescription,
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
        if desc.state_class is not None:
            self._attr_state_class = desc.state_class
        self._param = desc.param
        self._subentry_id = subentry.subentry_id
        if desc.native_unit is not None:
            self.native_unit_of_measurement = desc.native_unit
        if desc.suggested_display_precision is not None:
            self.suggested_display_precision = desc.suggested_display_precision

    @property
    def native_value(self):
        """Return the sensor value from EDR ranges."""
        try:
            if self.coordinator.data is None:
                return None
            return self.coordinator.data[self._subentry_id]["ranges"][self._param][
                "values"
            ][0]
        except (KeyError, IndexError, TypeError) as err:
            _LOGGER.debug(
                "Error accessing EDR range data for %s: %s",
                self.entity_description.key,
                err,
            )
            return None
