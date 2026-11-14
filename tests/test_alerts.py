"""Tests for KNMI nationwide-warning parsing and geographic filtering."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.nl_weather.KNMI.alerts import (
    AlertLevel,
    get_active_alerts,
    parse_alerts,
)

NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)
EXTERIOR = [[4.0, 51.0], [6.0, 51.0], [6.0, 53.0], [4.0, 53.0], [4.0, 51.0]]
HOLE = [[4.8, 51.8], [5.2, 51.8], [5.2, 52.2], [4.8, 52.2], [4.8, 51.8]]


def _part(
    color: str,
    geometry: dict | None = None,
    onset: str | None = None,
    expires: str | None = None,
) -> dict:
    """Construct a warning part with valid UTC defaults."""
    return {
        "id": color,
        "color": color,
        "area": geometry or {"type": "Polygon", "coordinates": [EXTERIOR]},
        "onset": onset or (NOW - timedelta(hours=1)).isoformat(),
        "expires": expires or (NOW + timedelta(hours=1)).isoformat(),
    }


def _snapshot(parts: list[dict]) -> dict:
    """Wrap warning parts in the KNMI response envelope."""
    return {
        "warnings": [
            {
                "id": "warning",
                "weatherType": 1368,
                "headline": "Storm warning",
                "description": "Strong winds",
                "detailedDescription": "Take care near the coast",
                "parts": parts,
            }
        ]
    }


def test_parse_and_sort_severity_with_details() -> None:
    """Sort warning parts by severity without losing metadata."""
    alerts = parse_alerts(_snapshot([_part("yellow"), _part("red"), _part("orange")]))
    assert [alert.level for alert in alerts] == [
        AlertLevel.RED,
        AlertLevel.ORANGE,
        AlertLevel.YELLOW,
    ]
    assert alerts[0].weather_type == 1368
    assert alerts[0].headline == "Storm warning"
    assert alerts[0].description == "Strong winds"
    assert alerts[0].details == "Take care near the coast"
    assert len(get_active_alerts(alerts, 52.5, 5.0, NOW)) == 3
    assert get_active_alerts(alerts, 55.0, 5.0, NOW) == []


def test_polygon_holes_and_multipolygons() -> None:
    """Include any MultiPolygon exterior but exclude interior holes."""
    polygon = {"type": "Polygon", "coordinates": [EXTERIOR, HOLE]}
    other = [[7.0, 53.0], [8.0, 53.0], [8.0, 54.0], [7.0, 54.0]]
    multi = {
        "type": "MultiPolygon",
        "coordinates": [[EXTERIOR, HOLE], [other]],
    }
    with_hole = parse_alerts(_snapshot([_part("yellow", polygon)]))[0]
    assert with_hole.contains(52.5, 5.0)
    assert not with_hole.contains(52.0, 5.0)
    multi_alert = parse_alerts(_snapshot([_part("orange", multi)]))[0]
    assert multi_alert.contains(53.5, 7.5)
    assert not multi_alert.contains(52.0, 5.0)


def test_onset_and_expiry_are_respected() -> None:
    """Do not report future or expired warning parts as active."""
    future = _part(
        "yellow",
        onset=(NOW + timedelta(minutes=1)).isoformat(),
        expires=(NOW + timedelta(hours=1)).isoformat(),
    )
    expired = _part(
        "orange",
        onset=(NOW - timedelta(hours=2)).isoformat(),
        expires=NOW.isoformat(),
    )
    assert (
        get_active_alerts(parse_alerts(_snapshot([future, expired])), 52, 5, NOW) == []
    )
    alert = parse_alerts(_snapshot([_part("red")]))[0]
    assert alert.is_active(NOW)
    assert not alert.is_active(alert.expires)


@pytest.mark.parametrize("snapshot", [None, {}, {"warnings": None}, {"warnings": {}}])
def test_invalid_top_level_response_is_not_silent(snapshot: object) -> None:
    """Reject malformed API envelopes rather than interpreting them as all clear."""
    with pytest.raises(TypeError, match="warnings list"):
        parse_alerts(snapshot)


def test_empty_and_invalid_parts() -> None:
    """Preserve legitimate empty snapshots and ignore invalid individual parts."""
    assert parse_alerts({"warnings": []}) == []
    assert parse_alerts(_snapshot([{"area": {}}, _part("invalid")])) == []
    invalid_coords = {
        "type": "Polygon",
        "coordinates": [[["bad", 51], [6, 51], [6, 53]]],
    }
    assert parse_alerts(_snapshot([_part("red", invalid_coords)])) == []
    invalid_time = _part("red", onset="2026-11-14T00:00:00")
    assert parse_alerts(_snapshot([invalid_time])) == []
