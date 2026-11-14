"""KNMI warning-area image entity, independent of the animated radar camera."""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime
from pathlib import Path

from homeassistant.components.image import ImageEntity
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from PIL import Image, ImageDraw

from .const import (
    CONF_MARK_LOCATIONS,
    CONF_RADAR_STYLE,
    DEFAULT_RADAR_STYLE,
    DOMAIN,
    LEVEL_COLORS,
    RADAR_STYLES,
    WMS_BBOX_EPSG3857,
)
from .coordinator import NLWeatherConfigEntry
from .KNMI.alerts import Alert
from .KNMI.helpers import Coordinate, add_location_markers, lonlat_to_pixel

FILL_ALPHA = 100
OUTLINE_WIDTH = 3


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NLWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a single nationwide warning map for this configuration entry."""
    if config_entry.runtime_data.alerts_coordinator is not None:
        async_add_entities([WeatherAlertsImage(hass, config_entry)])


def render_alerts(
    background: Image.Image,
    alerts: list[Alert],
    locations: list[Coordinate] | None = None,
    marker_color: str = "red",
) -> bytes:
    """Render active warning polygons onto the existing basemap as PNG bytes.

    Drawing occurs in a Home Assistant executor, never on the event loop.
    """
    image = background.copy().convert("RGBA")
    for alert in reversed(alerts):
        color = LEVEL_COLORS.get(alert.level.value)
        if color is None:
            continue
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for polygon in alert.polygons:
            rings = [
                [
                    lonlat_to_pixel(lon, lat, WMS_BBOX_EPSG3857, image.size)
                    for lon, lat in ring
                ]
                for ring in polygon
            ]
            if not rings or len(rings[0]) < 3:
                continue
            draw.polygon(rings[0], fill=(*color, FILL_ALPHA))
            for hole in rings[1:]:
                if len(hole) >= 3:
                    draw.polygon(hole, fill=(0, 0, 0, 0))
            for ring in rings:
                draw.line(
                    [*ring, ring[0]],
                    fill=(*color, 255),
                    width=OUTLINE_WIDTH,
                    joint="curve",
                )
        image = Image.alpha_composite(image, layer)
        layer.close()

    if locations:
        add_location_markers(
            image, locations, marker_color, WMS_BBOX_EPSG3857
        )

    with io.BytesIO() as output:
        image.save(output, format="PNG")
        result = output.getvalue()
    image.close()
    return result


class WeatherAlertsImage(ImageEntity):
    """A map of active KNMI warnings for the Netherlands."""

    _attr_content_type = "image/png"
    _attr_should_poll = False
    _attr_translation_key = "weather_alert_map"

    def __init__(self, hass: HomeAssistant, config_entry: NLWeatherConfigEntry) -> None:
        """Initialize the warning map with the existing radar appearance."""
        super().__init__(hass)
        self._coordinator = config_entry.runtime_data.alerts_coordinator
        self._config_entry = config_entry
        self._background: Image.Image | None = None
        self._image: bytes | None = None
        self._render_lock = asyncio.Lock()
        self._attr_unique_id = f"{config_entry.entry_id}_weather_alert_map"
        self._attr_device_info = DeviceInfo(
            name="Waarschuwingenkaart",
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_weather_alert_map")},
            manufacturer="KNMI.nl",
            configuration_url="https://www.knmi.nl",
        )

    def _load_background(self) -> None:
        """Load the packaged radar basemap off the event loop."""
        style = RADAR_STYLES[
            self._config_entry.options.get(CONF_RADAR_STYLE, DEFAULT_RADAR_STYLE)
        ]
        path = Path(__file__).with_name(style.background_image)
        with Image.open(path) as image:
            self._background = image.convert("RGBA")

    async def _render(self) -> None:
        """Re-render after coordinator updates, serialized to avoid races."""
        async with self._render_lock:
            if (
                self._coordinator is None
                or self._coordinator.data is None
                or self._background is None
            ):
                return
            now = datetime.now(UTC)
            alerts = [
                alert
                for alert in self._coordinator.data
                if alert.is_active(now)
            ]
            locations = (
                [
                    Coordinate(
                        subentry.data[CONF_LATITUDE],
                        subentry.data[CONF_LONGITUDE],
                    )
                    for subentry in self._config_entry.subentries.values()
                ]
                if self._config_entry.options.get(CONF_MARK_LOCATIONS, True)
                else []
            )
            style = RADAR_STYLES[
                self._config_entry.options.get(
                    CONF_RADAR_STYLE, DEFAULT_RADAR_STYLE
                )
            ]
            self._image = await self.hass.async_add_executor_job(
                render_alerts,
                self._background,
                alerts,
                locations,
                style.marker_color,
            )
            self._attr_image_last_updated = datetime.now(UTC)
            self.async_write_ha_state()

    @callback
    def _handle_update(self) -> None:
        """Schedule an image refresh from the nationwide warning coordinator."""
        self.hass.async_create_task(self._render())

    async def async_added_to_hass(self) -> None:
        """Subscribe to warning changes and render the initial basemap."""
        await super().async_added_to_hass()
        await self.hass.async_add_executor_job(self._load_background)
        if self._coordinator is not None:
            self.async_on_remove(
                self._coordinator.async_add_listener(self._handle_update)
            )
        await self._render()

    async def async_image(self) -> bytes | None:
        """Return the cached PNG produced in an executor."""
        return self._image
