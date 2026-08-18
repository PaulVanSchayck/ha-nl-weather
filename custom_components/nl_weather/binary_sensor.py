from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from typing import Any

from .const import Alert, ATTR_WEATHER_SOLAR_RADIATION, ATTR_WEATHER_SUNSHINE, PARAMETER_ATTRIBUTE_MAP
from . import DOMAIN
from .coordinator import (
    NLWeatherConfigEntry,
    NLWeatherEDRCoordinator,
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
        edr_coordinator = config_entry.runtime_data.edr_coordinators[subentry_id]
        async_add_entities(
            [
                NLWeatherAlertActiveSensor(app_coordinator, config_entry, subentry),
                NLWeatherPrecipitationNowcastSensor(
                    nowcast_coordinator, config_entry, subentry
                ),
                NLWeatherSunSensor(edr_coordinator, config_entry, subentry),
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
            return {"forecast": []}
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


class NLWeatherSunSensor(
    CoordinatorEntity[NLWeatherEDRCoordinator], BinarySensorEntity
):
    def __init__(
        self,
        coordinator: NLWeatherEDRCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_sun"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True
        self.entity_description = BinarySensorEntityDescription(
            key="sun",
            icon="mdi:weather-sunny",
            translation_key="sun",
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        solar = self.coordinator.data.get("params", {}).get(
            PARAMETER_ATTRIBUTE_MAP[ATTR_WEATHER_SOLAR_RADIATION]
        )
        if solar is None:
            return None
        return solar > 50

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        params = self.coordinator.data.get("params", {})
        solar = params.get(PARAMETER_ATTRIBUTE_MAP[ATTR_WEATHER_SOLAR_RADIATION])
        sunshine = params.get(PARAMETER_ATTRIBUTE_MAP[ATTR_WEATHER_SUNSHINE])
        sunshine_pct = round(sunshine * 10) if sunshine is not None else None
        return {"solar_radiation": solar, "sunshine_pct": sunshine_pct}
