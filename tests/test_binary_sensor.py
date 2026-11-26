"""Tests for NL Weather binary sensor platform."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.nl_weather.binary_sensor import NLWeatherAlertActiveSensor
from custom_components.nl_weather.const import Alert
from custom_components.nl_weather.KNMI.alerts import Alert as NationwideAlert
from custom_components.nl_weather.KNMI.alerts import AlertLevel
from custom_components.nl_weather.local_alerts import NLWeatherLocalAlertActiveSensor


def _local_alert() -> NationwideAlert:
    """Create an active warning polygon covering the configured test location."""
    now = datetime.now(UTC)
    return NationwideAlert(
        warning_id="test-warning",
        weather_type=1368,
        headline="Heavy rain",
        level=AlertLevel.ORANGE,
        onset=now - timedelta(minutes=5),
        expires=now + timedelta(minutes=30),
        polygons=[
            [
                [
                    (4.0, 51.0),
                    (6.0, 51.0),
                    (6.0, 53.0),
                    (4.0, 53.0),
                ]
            ]
        ],
    )


def _local_alert_entity(coordinator: MagicMock) -> NLWeatherLocalAlertActiveSensor:
    """Build a location-specific warning binary sensor for the test location."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    subentry = MagicMock()
    subentry.subentry_id = "test_subentry"
    subentry.data = {"latitude": 52.0, "longitude": 5.0}
    return NLWeatherLocalAlertActiveSensor(coordinator, config_entry, subentry)


def test_alert_active_sensor_is_on_when_alert_active() -> None:
    """Test is_on returns True when an active alert is present."""
    coordinator = MagicMock()
    coordinator.data = {"hourly": {"forecast": [{"alertLevel": "yellow"}]}}
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    subentry = MagicMock()
    subentry.subentry_id = "test_subentry"

    sensor = NLWeatherAlertActiveSensor(coordinator, config_entry, subentry)
    assert sensor.is_on is True


def test_alert_active_sensor_is_off_when_later_forecast_item_has_alert() -> None:
    """Test is_on returns False when an alert is only active in a later forecast item."""
    coordinator = MagicMock()
    coordinator.data = {
        "hourly": {
            "forecast": [
                {"alertLevel": "none"},
                {"alertLevel": "orange"},
            ]
        }
    }
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    subentry = MagicMock()
    subentry.subentry_id = "test_subentry"

    sensor = NLWeatherAlertActiveSensor(coordinator, config_entry, subentry)
    assert sensor.is_on is False


def test_alert_active_sensor_is_on_when_no_alert() -> None:
    """Test is_on returns False when alert level is none."""
    coordinator = MagicMock()
    coordinator.data = {"hourly": {"forecast": [{"alertLevel": Alert.NONE}]}}
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    subentry = MagicMock()
    subentry.subentry_id = "test_subentry"

    sensor = NLWeatherAlertActiveSensor(coordinator, config_entry, subentry)
    assert sensor.is_on is False


def test_alert_active_sensor_is_on_when_data_none() -> None:
    """Test is_on returns False when coordinator data is None."""
    coordinator = MagicMock()
    coordinator.data = None
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    subentry = MagicMock()
    subentry.subentry_id = "test_subentry"

    sensor = NLWeatherAlertActiveSensor(coordinator, config_entry, subentry)
    assert sensor.is_on is False


def test_alert_active_sensor_is_on_when_data_malformed() -> None:
    """Test is_on returns False when hourly forecast data is missing or empty."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    subentry = MagicMock()
    subentry.subentry_id = "test_subentry"

    # Empty hourly forecast list
    coordinator = MagicMock()
    coordinator.data = {"hourly": {"forecast": []}}
    sensor = NLWeatherAlertActiveSensor(coordinator, config_entry, subentry)
    assert sensor.is_on is False

    # Missing forecast key
    coordinator.data = {"hourly": {}}
    sensor = NLWeatherAlertActiveSensor(coordinator, config_entry, subentry)
    assert sensor.is_on is False

    # Missing alertLevel key
    coordinator.data = {"hourly": {"forecast": [{}]}}
    sensor = NLWeatherAlertActiveSensor(coordinator, config_entry, subentry)
    assert sensor.is_on is False


def test_local_alert_active_sensor_is_on_for_matching_location() -> None:
    """Report an active nationwide warning covering the configured location."""
    coordinator = MagicMock()
    coordinator.data = [_local_alert()]

    assert _local_alert_entity(coordinator).is_on is True


def test_local_alert_active_sensor_is_off_without_matching_active_warning() -> None:
    """Return off when the warning list is empty or the warning is expired."""
    coordinator = MagicMock()
    coordinator.data = []
    sensor = _local_alert_entity(coordinator)
    assert sensor.is_on is False

    alert = _local_alert()
    alert.expires = datetime.now(UTC) - timedelta(minutes=1)
    coordinator.data = [alert]
    assert sensor.is_on is False


def test_local_alert_active_sensor_is_off_when_coordinator_data_unavailable() -> None:
    """Return off when the nationwide warning coordinator has no data."""
    coordinator = MagicMock()
    coordinator.data = None

    assert _local_alert_entity(coordinator).is_on is False



@pytest.mark.parametrize("coordinator_data", [None, {}, [None]])
def test_local_alert_active_sensor_handles_malformed_coordinator_data(
    coordinator_data: object,
) -> None:
    """Return off rather than raising for unavailable or malformed warning data."""
    coordinator = MagicMock()
    coordinator.data = coordinator_data

    assert _local_alert_entity(coordinator).is_on is False
