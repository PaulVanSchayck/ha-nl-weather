from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorEntityDescription
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_NAME, UnitOfLength
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import Alert
from . import KNMIDirectConfigEntry, DOMAIN
from .coordinator import NLWeatherUpdateCoordinator, NLWeatherEDRCoordinator
from homeassistant.core import HomeAssistant


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: KNMIDirectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    obs_coordinator = config_entry.runtime_data.obs_coordinator
    for subentry_id, subentry in config_entry.subentries.items():
        coordinator = config_entry.runtime_data.coordinators[subentry_id]

        async_add_entities(
            [
                NLWeatherAlertSensor(coordinator, config_entry, subentry),
                NLWeatherAlertLevelSensor(coordinator, config_entry, subentry),
                NLObservationStationDistanceSensor(obs_coordinator, config_entry, subentry),
                NLObservationStationNameSensor(obs_coordinator, config_entry, subentry),
                NLObservationTimeSensor(obs_coordinator, config_entry, subentry),
            ], config_subentry_id=subentry_id
        )

# TODO: Clean up sensor creation using a base class

class NLWeatherAlertSensor(CoordinatorEntity[NLWeatherUpdateCoordinator], SensorEntity):
    def __init__(self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_forecast")},
        )
        self.entity_description = SensorEntityDescription(
            key="alert",
            name=f"Weer Waarschuwing {subentry.data[CONF_NAME]}",
            icon="mdi:weather-cloudy-alert",
        )

    @property
    def native_value(self):
        # TODO: Not dealing well with multiple alerts yet
        if len(self.coordinator.data['alerts']) > 0:
            return self.coordinator.data['alerts'][0]['description']
        else:
            # TODO: Needs translation
            return "Geen"

class NLWeatherAlertLevelSensor(CoordinatorEntity[NLWeatherUpdateCoordinator], SensorEntity):
    def __init__(self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_alert_level"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_forecast")},
        )
        self.entity_description = SensorEntityDescription(
            key="alert_level",
            options=[a.value for a in Alert],
            name=f"Weer Code {subentry.data[CONF_NAME]}",
            icon="mdi:alert-box",
            translation_key="weather_alert_level",
            device_class=SensorDeviceClass.ENUM
        )

    @property
    def native_value(self):
        return Alert(self.coordinator.data["hourly"]["forecast"][0]["alertLevel"])

class NLObservationStationDistanceSensor(CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity):
    def __init__(self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_station_distance"
        self._attr_name = f"Weerstation Afstand {subentry.data[CONF_NAME]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_observations")},
        )
        self.device_class = SensorDeviceClass.DISTANCE
        self._subentry_id = subentry.subentry_id
        self.native_unit_of_measurement = UnitOfLength.KILOMETERS
        self.suggested_display_precision = 1

    @property
    def native_value(self):
        return self.coordinator.data[self._subentry_id]['distance']

class NLObservationStationNameSensor(CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity):
    def __init__(self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_station_name"
        self._attr_name = f"Weerstation Naam {subentry.data[CONF_NAME]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_observations")},
        )
        self._subentry_id = subentry.subentry_id

    @property
    def native_value(self):
        return self.coordinator.data[self._subentry_id]['station_name']

class NLObservationTimeSensor(CoordinatorEntity[NLWeatherEDRCoordinator], SensorEntity):
    def __init__(self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_observation_time"
        self._attr_name = f"Observatie tijd {subentry.data[CONF_NAME]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_observations")},
        )
        self.device_class = SensorDeviceClass.TIMESTAMP
        self._subentry_id = subentry.subentry_id

    @property
    def native_value(self):
        return self.coordinator.data[self._subentry_id]['datetime']