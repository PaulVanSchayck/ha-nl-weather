from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import DeviceInfo, DeviceEntryType
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import KNMIDirectConfigEntry, DOMAIN
from .coordinator import NLWeatherUpdateCoordinator
from homeassistant.core import HomeAssistant


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: KNMIDirectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry_id, subentry in config_entry.subentries.items():
        coordinator = config_entry.runtime_data.coordinators[subentry_id]

        async_add_entities(
            [
                NLWeatherAlertSensor(coordinator, config_entry, subentry),
                NLWeatherAlertLevelSensor(coordinator, config_entry, subentry),
            ], config_subentry_id=subentry_id
        )

# TODO: Clean up sensor creation using a base class
# TODO: Not dealing well with multiple alerts yet

class NLWeatherAlertSensor(CoordinatorEntity[NLWeatherUpdateCoordinator], SensorEntity):
    def __init__(self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_alert"
        self._attr_name = f"Weer Waarschuwing {subentry.data[CONF_NAME]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_forecast")},
        )

    @property
    def native_value(self):
        if len(self.coordinator.data['alerts']) > 0:
            return self.coordinator.data['alerts'][0]['description']
        else:
            return "Geen"

class NLWeatherAlertLevelSensor(CoordinatorEntity[NLWeatherUpdateCoordinator], SensorEntity):
    def __init__(self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_alert_level"
        self._attr_name = f"Weer Code {subentry.data[CONF_NAME]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_forecast")},
        )

    @property
    def native_value(self):
        if len(self.coordinator.data['alerts']) > 0:
            return self.coordinator.data['alerts'][0]['level']
        else:
            return "Groen"