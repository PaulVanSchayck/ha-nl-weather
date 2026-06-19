from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import Alert
from . import DOMAIN
from .coordinator import (
    NLWeatherConfigEntry,
    NLWeatherNowcastCoordinator,
    NLWeatherUpdateCoordinator,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import utcnow


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NLWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry_id, subentry in config_entry.subentries.items():
        app_coordinator = config_entry.runtime_data.app_coordinators[subentry_id]
        nowcast_coordinator = config_entry.runtime_data.nowcast_coordinators[
            subentry_id
        ]
        async_add_entities(
            [
                NLWeatherAlertActiveSensor(app_coordinator, config_entry, subentry),
                NLWeatherPrecipitationNowcastSensor(
                    nowcast_coordinator, config_entry, subentry
                ),
            ],
            config_subentry_id=subentry_id,
        )


class NLWeatherAlertActiveSensor(
    CoordinatorEntity[NLWeatherUpdateCoordinator], BinarySensorEntity
):
    def __init__(
        self, coordinator, config_entry: NLWeatherConfigEntry, subentry: ConfigSubentry
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_alert_active"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self.entity_description = BinarySensorEntityDescription(
            key="alert_active",
            icon="mdi:alert-box-outline",
            translation_key="weather_alert_active",
        )

    @property
    def is_on(self):
        return (
            self.coordinator.data["hourly"]["forecast"][0]["alertLevel"] != Alert.NONE
        )


class NLWeatherPrecipitationNowcastSensor(
    CoordinatorEntity[NLWeatherNowcastCoordinator], BinarySensorEntity
):
    def __init__(
        self,
        coordinator: NLWeatherNowcastCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_precipitation_nowcast"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self.entity_description = BinarySensorEntityDescription(
            key="precipitation_nowcast",
            icon="mdi:weather-pouring",
            translation_key="precipitation_nowcast",
        )

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return {}
        return {"forecast": self.coordinator.data}

    @property
    def is_on(self):
        if self.coordinator.data is None:
            return False

        now = utcnow()
        return any(
            p["datetime"] > now and p["precipitation"] > 0
            for p in self.coordinator.data
        )
