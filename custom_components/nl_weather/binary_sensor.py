from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import utcnow

from . import DOMAIN
from .coordinator import (
    NLWeatherAlertsCoordinator,
    NLWeatherConfigEntry,
    NLWeatherNowcastCoordinator,
)
from .KNMI.alerts import get_active_alerts


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NLWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry_id, subentry in config_entry.subentries.items():
        alerts_coordinator = config_entry.runtime_data.alerts_coordinator
        nowcast_coordinator = config_entry.runtime_data.nowcast_coordinators[
            subentry_id
        ]
        async_add_entities(
            [
                NLWeatherAlertActiveSensor(alerts_coordinator, config_entry, subentry),
                NLWeatherPrecipitationNowcastSensor(
                    nowcast_coordinator, config_entry, subentry
                ),
            ],
            config_subentry_id=subentry_id,
        )


class NLWeatherAlertActiveSensor(
    CoordinatorEntity[NLWeatherAlertsCoordinator], BinarySensorEntity
):
    def __init__(
        self,
        coordinator: NLWeatherAlertsCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(coordinator)

        self._lat = subentry.data[CONF_LATITUDE]
        self._lon = subentry.data[CONF_LONGITUDE]

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
    def available(self) -> bool:
        return self.coordinator.data is not None

    @property
    def is_on(self):
        # Only re-evaluated on coordinator updates, so an alert can start or
        # expire up to one polling interval late.
        return bool(
            get_active_alerts(self.coordinator.data, self._lat, self._lon, utcnow())
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
