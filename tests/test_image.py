"""Tests for the standalone KNMI nationwide-warning map image."""

from datetime import UTC, datetime, timedelta
from io import BytesIO

from PIL import Image

from custom_components.nl_weather.const import WMS_BBOX_EPSG3857
from custom_components.nl_weather.image import render_alerts
from custom_components.nl_weather.KNMI.alerts import Alert, AlertLevel
from custom_components.nl_weather.KNMI.helpers import Coordinate, lonlat_to_pixel


def _alert(level: AlertLevel) -> Alert:
    """Return a polygon covering the middle of the basemap."""
    now = datetime.now(UTC)
    return Alert(
        warning_id=level.value,
        weather_type=1368,
        headline="Warning",
        level=level,
        onset=now - timedelta(hours=1),
        expires=now + timedelta(hours=1),
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


def test_render_alerts_outputs_png_without_mutating_background() -> None:
    """Draw warning areas with a stable PNG content type."""
    background = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
    result = render_alerts(background, [_alert(AlertLevel.RED)])
    assert result.startswith(b"\x89PNG\r\n\x1a\n")
    assert background.getpixel((100, 100)) == (255, 255, 255, 255)
    with Image.open(BytesIO(result)) as rendered:
        x, y = lonlat_to_pixel(5.0, 52.0, WMS_BBOX_EPSG3857, rendered.size)
        assert rendered.getpixel((int(x), int(y))) != (255, 255, 255, 255)


def test_render_alerts_markers_and_severity_order() -> None:
    """Draw markers and ensure higher severity overlays lower severity."""
    background = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
    yellow = _alert(AlertLevel.YELLOW)
    red = _alert(AlertLevel.RED)
    bytes_without = render_alerts(background, [])
    bytes_with_markers = render_alerts(
        background, [], [Coordinate(52.0, 5.0)], "red"
    )
    assert bytes_with_markers != bytes_without
    assert render_alerts(background, [red, yellow]) != render_alerts(
        background, [yellow, red]
    )
