from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import Alert
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
            ],
            config_subentry_id=subentry_id,
        )


class NLWeatherAlertActiveSensor(
    CoordinatorEntity[NLWeatherUpdateCoordinator], BinarySensorEntity
):
    def __init__(
        self, coordinator, config_entry: KNMIDirectConfigEntry, subentry: ConfigSubentry
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_alert_active"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}_forecast")
            },
        )
        self.entity_description = BinarySensorEntityDescription(
            key="alert_active",
            name=f"Weer Waarschuwing Actief {subentry.data[CONF_NAME]}",
            icon="mdi:alert-box-outline",
        )

    @property
    def is_on(self):
        return (
            self.coordinator.data["hourly"]["forecast"][0]["alertLevel"] != Alert.NONE
        )
