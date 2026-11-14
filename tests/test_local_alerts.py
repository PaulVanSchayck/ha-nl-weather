"""Tests for additive, location-filtered warning entities."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from custom_components.nl_weather.local_alerts import (
    LOCAL_ALERT_DESCRIPTIONS,
    NLWeatherLocalAlertActiveSensor,
    NLWeatherLocalAlertSensor,
    local_alert_attributes,
)
from custom_components.nl_weather.KNMI.alerts import Alert, AlertLevel


def _alert() -> Alert:
    """Build a warning overlapping a configured Dutch location."""
    now = datetime.now(UTC)
    return Alert(
        warning_id="a",
        weather_type=1368,
        headline="Storm warning",
        level=AlertLevel.RED,
        onset=now - timedelta(hours=1),
        expires=now + timedelta(hours=1),
        polygons=[[[(4.0, 51.0), (6.0, 51.0), (6.0, 53.0), (4.0, 53.0)]]],
        description="Strong winds",
        details="Keep indoors",
    )


def _entities(latitude: float, longitude: float):
    """Create local entities using the same location identity as the fork."""
    coordinator = MagicMock()
    coordinator.data = [_alert()]
    entry = MagicMock()
    entry.entry_id = "entry-id"
    subentry = MagicMock()
    subentry.subentry_id = "sub-id"
    subentry.data = {"latitude": latitude, "longitude": longitude}
    sensors = [
        NLWeatherLocalAlertSensor(coordinator, entry, subentry, description)
        for description in LOCAL_ALERT_DESCRIPTIONS
    ]
    active = NLWeatherLocalAlertActiveSensor(coordinator, entry, subentry)
    return sensors, active


def test_local_sensor_values_and_unique_ids() -> None:
    """Only new ID suffixes are used and local warning parts are filtered."""
    sensors, active = _entities(52.0, 5.0)
    assert [sensor.native_value for sensor in sensors] == [
        "Storm warning",
        1,
        "red",
    ]
    assert active.is_on
    assert sensors[0].unique_id == "entry-id_sub-id_local_alert"
    assert active.unique_id == "entry-id_sub-id_local_alert_active"
    assert sensors[0].extra_state_attributes["alerts"][0]["details"] == "Keep indoors"


def test_out_of_area_warning_is_inactive() -> None:
    """Existing regional warning logic is independent of local warnings."""
    sensors, active = _entities(55.0, 10.0)
    assert [sensor.native_value for sensor in sensors] == ["none", 0, "none"]
    assert not active.is_on


def test_local_warning_attributes() -> None:
    """Expose condition, start, end, headline and detailed description."""
    attributes = local_alert_attributes([_alert()])
    warning = attributes["alerts"][0]
    assert warning["headline"] == "Storm warning"
    assert warning["code"] == "red"
    assert warning["condition"] is not None
    assert "T" in warning["onset"]
    assert "T" in warning["expires"]
    assert attributes["alert_count"] == 1
