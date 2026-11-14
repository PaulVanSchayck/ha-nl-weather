"""Additional location-specific nationwide warning entities.

These entities deliberately use distinct unique IDs from the existing region-based
warning sensors and binary sensor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONDITION_FORECAST_MAP, DOMAIN
from .coordinator import NLWeatherAlertsCoordinator, NLWeatherConfigEntry
from .KNMI.alerts import Alert, AlertLevel, get_active_alerts


@dataclass(frozen=True, kw_only=True)
class LocalAlertDescription(SensorEntityDescription):
    """Describe a location-specific warning measurement."""


LOCAL_ALERT_DESCRIPTIONS: tuple[LocalAlertDescription, ...] = (
    LocalAlertDescription(
        key="local_alert",
        translation_key="local_weather_alert",
        icon="mdi:weather-cloudy-alert",
    ),
    LocalAlertDescription(
        key="local_alert_count",
        translation_key="local_weather_alert_count",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    LocalAlertDescription(
        key="local_alert_level",
        translation_key="local_weather_alert_level",
        icon="mdi:alert-box",
        device_class=SensorDeviceClass.ENUM,
        options=[level.value for level in AlertLevel],
    ),
)


def active_location_alerts(
    coordinator: NLWeatherAlertsCoordinator, latitude: float, longitude: float
) -> list[Alert]:
    """Filter currently active warning parts for this configured location."""
    return get_active_alerts(
        coordinator.data, latitude, longitude, datetime.now(UTC)
    )


def local_alert_attributes(alerts: list[Alert]) -> dict[str, object]:
    """Expose warning metadata for dashboards and automations."""
    return {
        "alert_count": len(alerts),
        "alerts": [
            {
                "code": alert.level.value,
                "condition": CONDITION_FORECAST_MAP.get(alert.weather_type),
                "headline": alert.headline,
                "description": alert.description,
                "details": alert.details,
                "onset": alert.onset.isoformat(),
                "expires": alert.expires.isoformat(),
            }
            for alert in alerts
        ],
        "description": ". ".join(
            (alert.description or alert.headline or alert.level.value).removesuffix(
                "."
            )
            for alert in alerts
        ),
    }


class NLWeatherLocalAlertSensor(
    CoordinatorEntity[NLWeatherAlertsCoordinator], SensorEntity
):
    """A nationwide warning value filtered for a configured location."""

    def __init__(
        self,
        coordinator: NLWeatherAlertsCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
        description: LocalAlertDescription,
    ) -> None:
        """Initialize a local warning sensor with its own stable identifier."""
        super().__init__(coordinator)
        self.entity_description = description
        self._latitude = subentry.data[CONF_LATITUDE]
        self._longitude = subentry.data[CONF_LONGITUDE]
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_{description.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> str | int | None:
        """Return the local severity, active count, or short headline."""
        if self.coordinator.data is None:
            return None
        alerts = active_location_alerts(
            self.coordinator, self._latitude, self._longitude
        )
        match self.entity_description.key:
            case "local_alert_count":
                return len(alerts)
            case "local_alert_level":
                return alerts[0].level.value if alerts else AlertLevel.NONE.value
            case _:
                return (
                    (alerts[0].headline or alerts[0].description or alerts[0].level.value)[:255]
                    if alerts
                    else "none"
                )

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Expose details on the description sensor only."""
        if (
            self.coordinator.data is None
            or self.entity_description.key != "local_alert"
        ):
            return None
        return local_alert_attributes(
            active_location_alerts(self.coordinator, self._latitude, self._longitude)
        )


class NLWeatherLocalAlertActiveSensor(
    CoordinatorEntity[NLWeatherAlertsCoordinator], BinarySensorEntity
):
    """Whether a nationwide warning is currently active at this location."""

    _attr_translation_key = "local_weather_alert_active"
    _attr_icon = "mdi:alert-box-outline"

    def __init__(
        self,
        coordinator: NLWeatherAlertsCoordinator,
        config_entry: NLWeatherConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Create an independent local active-warning binary sensor."""
        super().__init__(coordinator)
        self._latitude = subentry.data[CONF_LATITUDE]
        self._longitude = subentry.data[CONF_LONGITUDE]
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{subentry.subentry_id}_local_alert_active"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{config_entry.entry_id}_{subentry.subentry_id}")},
        )
        self._attr_has_entity_name = True

    @property
    def is_on(self) -> bool:
        """Return whether any warning part currently covers this location."""
        return bool(
            active_location_alerts(
                self.coordinator, self._latitude, self._longitude
            )
        )
