"""Tests for NL Weather binary sensor platform."""

from unittest.mock import MagicMock

from custom_components.nl_weather.binary_sensor import NLWeatherAlertActiveSensor
from custom_components.nl_weather.const import Alert


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
