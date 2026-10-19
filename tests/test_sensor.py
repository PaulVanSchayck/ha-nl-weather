"""Tests for NL Weather sensor platform and helper functions."""

from custom_components.nl_weather.const import Alert
from custom_components.nl_weather.sensor import (
    _get_alert_level,
    _get_cloud_coverage,
    _get_heat_force_index,
    _get_heat_force_index_today,
    _get_wind_direction_cardinal,
    safe_int,
    wind_direction_icon,
)


def test_wind_direction_icon_cardinals_and_intercardinals() -> None:
    """Test wind_direction_icon maps cardinal and intercardinal angles correctly."""
    assert wind_direction_icon(0) == "mdi:arrow-down"
    assert wind_direction_icon(45) == "mdi:arrow-bottom-left"
    assert wind_direction_icon(90) == "mdi:arrow-left"
    assert wind_direction_icon(135) == "mdi:arrow-top-left"
    assert wind_direction_icon(180) == "mdi:arrow-up"
    assert wind_direction_icon(225) == "mdi:arrow-top-right"
    assert wind_direction_icon(270) == "mdi:arrow-right"
    assert wind_direction_icon(315) == "mdi:arrow-bottom-right"


def test_wind_direction_icon_north_wraparound() -> None:
    """Test wind_direction_icon handles angles close to North (360°)."""
    assert wind_direction_icon(360) == "mdi:arrow-down"
    assert wind_direction_icon(355) == "mdi:arrow-down"
    assert wind_direction_icon(350) == "mdi:arrow-down"
    assert wind_direction_icon(338) == "mdi:arrow-down"


def test_wind_direction_icon_negative_and_overflow_angles() -> None:
    """Test wind_direction_icon with negative or angles > 360."""
    assert wind_direction_icon(-45) == "mdi:arrow-bottom-right"
    assert wind_direction_icon(-90) == "mdi:arrow-right"
    assert wind_direction_icon(720) == "mdi:arrow-down"
    assert wind_direction_icon(405) == "mdi:arrow-bottom-left"


def test_safe_int() -> None:
    """Test safe_int conversion helper."""
    assert safe_int(10) == 10
    assert safe_int(10.8) == 10
    assert safe_int("25") == 25
    assert safe_int("invalid") is None
    assert safe_int(None) is None


def test_get_wind_direction_cardinal() -> None:
    """Test cardinal direction extraction from EDR observation data."""
    assert _get_wind_direction_cardinal({"params": {"dd": 0}}) == "n"
    assert _get_wind_direction_cardinal({"params": {"dd": 360}}) == "n"
    assert _get_wind_direction_cardinal({"params": {"dd": 355}}) == "n"
    assert _get_wind_direction_cardinal({"params": {"dd": 90}}) == "e"
    assert _get_wind_direction_cardinal({"params": {"dd": 180}}) == "s"
    assert _get_wind_direction_cardinal({"params": {"dd": 270}}) == "w"
    assert _get_wind_direction_cardinal({"params": {"dd": -90}}) == "w"
    assert _get_wind_direction_cardinal({"params": {}}) is None


def test_get_cloud_coverage() -> None:
    """Test cloud coverage conversion from oktas to percentage."""
    assert _get_cloud_coverage({"params": {"nhc": 0}}) == 0.0
    assert _get_cloud_coverage({"params": {"nhc": 4}}) == 50.0
    assert _get_cloud_coverage({"params": {"nhc": 8}}) == 100.0
    assert _get_cloud_coverage({"params": {"nhc": 9}}) == 100
    assert _get_cloud_coverage({"params": {}}) is None


def test_get_heat_force_index() -> None:
    """Test heat force index extraction from hourly forecast data."""
    # Valid heat index
    assert (
        _get_heat_force_index({"hourly": {"forecast": [{"heatIndex": 24.5}]}}) == 24.5
    )

    # Missing heatIndex key in forecast item
    assert _get_heat_force_index({"hourly": {"forecast": [{}]}}) is None

    # Non-mapping forecast item (e.g. None)
    assert _get_heat_force_index({"hourly": {"forecast": [None]}}) is None

    # Empty forecast list
    assert _get_heat_force_index({"hourly": {"forecast": []}}) is None

    # Missing hourly or forecast structure
    assert _get_heat_force_index({"hourly": {}}) is None
    assert _get_heat_force_index({}) is None


def test_get_heat_force_index_today() -> None:
    """Test daily heat force index extraction from daily forecast data."""
    # Valid heat index
    assert (
        _get_heat_force_index_today({"daily": {"forecast": [{"heatIndex": 21.0}]}})
        == 21.0
    )

    # Missing heatIndex key in forecast item
    assert _get_heat_force_index_today({"daily": {"forecast": [{}]}}) is None

    # Non-mapping forecast item (e.g. None)
    assert _get_heat_force_index_today({"daily": {"forecast": [None]}}) is None

    # Empty forecast list
    assert _get_heat_force_index_today({"daily": {"forecast": []}}) is None

    # Missing daily or forecast structure
    assert _get_heat_force_index_today({"daily": {}}) is None
    assert _get_heat_force_index_today({}) is None


def test_get_alert_level() -> None:
    """Test extraction of highest alert level from hourly forecast data."""
    # First item is "none", later item is "orange" -> should return Alert.ORANGE
    data = {
        "hourly": {
            "forecast": [
                {"alertLevel": "none"},
                {"alertLevel": "yellow"},
                {"alertLevel": "orange"},
                {"alertLevel": "yellow"},
            ]
        }
    }
    assert _get_alert_level(data) == Alert.ORANGE

    # Contains "red" alert -> should return Alert.RED
    data_red = {
        "hourly": {
            "forecast": [
                {"alertLevel": "yellow"},
                {"alertLevel": "red"},
                {"alertLevel": "orange"},
            ]
        }
    }
    assert _get_alert_level(data_red) == Alert.RED

    # All "none" -> should return Alert.NONE
    data_none = {
        "hourly": {
            "forecast": [
                {"alertLevel": "none"},
                {"alertLevel": "none"},
            ]
        }
    }
    assert _get_alert_level(data_none) == Alert.NONE

    # Handles empty, invalid, or missing data structures gracefully
    assert _get_alert_level({"hourly": {"forecast": []}}) == Alert.NONE
    assert _get_alert_level({"hourly": {"forecast": None}}) == Alert.NONE
    assert _get_alert_level({"hourly": {}}) == Alert.NONE
    assert _get_alert_level({}) == Alert.NONE
    assert (
        _get_alert_level({"hourly": {"forecast": [{"alertLevel": "invalid_level"}]}})
        == Alert.NONE
    )
