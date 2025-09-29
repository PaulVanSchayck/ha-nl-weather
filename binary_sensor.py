from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import DeviceInfo
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
                NLWeatherAlertActiveSensor(coordinator, config_entry, subentry),
            ], config_subentry_id=subentry_id
        )

class NLWeatherAlertActiveSensor(CoordinatorEntity[NLWeatherUpdateCoordinator], BinarySensorEntity):
    def __init__(self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = f"{config_entry.entry_id}_{subentry.subentry_id}_alert_active"
        self._attr_name = f"Weer Waarschuwing Actief {subentry.data[CONF_NAME]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_forecast")},
        )

    @property
    def is_on(self):
        # TODO: We should probably get this from the hourly forecast array
        return len(self.coordinator.data['alerts']) > 0
