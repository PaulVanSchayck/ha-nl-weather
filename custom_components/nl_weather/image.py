"""Image entity plotting weather warning polygons on the radar basemap."""

from __future__ import annotations

import io
import logging
import os

from homeassistant.components.image import ImageEntity
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import utcnow
from PIL import Image, ImageDraw

from .camera import BACKGROUND_IMAGE_BBOX
from .const import (
    CONF_MARK_LOCATIONS,
    CONF_RADAR_STYLE,
    DEFAULT_RADAR_STYLE,
    DOMAIN,
    LEVEL_COLORS,
    RADAR_STYLES,
)
from .coordinator import NLWeatherConfigEntry
from .KNMI.alerts import Alert
from .KNMI.helpers import Coordinate, add_location_markers, lonlat_to_pixel

_LOGGER = logging.getLogger(__name__)

FILL_ALPHA = 100
OUTLINE_WIDTH = 3


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NLWeatherConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([WeatherAlertsImage(hass, config_entry)])


def render_alerts(
    background: Image.Image,
    alerts: list[Alert],
    locations: list[Coordinate] | None = None,
    marker_color: str = "red",
) -> bytes:
    """Draw alerts on a copy of the background and return PNG bytes.

    Alerts are expected most severe first; they are drawn in reverse so the most
    severe warning ends up on top.
    """
    img = background.copy()
    for alert in reversed(alerts):
        color = LEVEL_COLORS[alert.level]
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for polygon in alert.polygons:
            rings = [
                [
                    lonlat_to_pixel(lon, lat, BACKGROUND_IMAGE_BBOX, img.size)
                    for lon, lat in ring
                ]
                for ring in polygon
            ]
            draw.polygon(rings[0], fill=(*color, FILL_ALPHA))
            for hole in rings[1:]:
                draw.polygon(hole, fill=(0, 0, 0, 0))
            for ring in rings:
                draw.line(ring, fill=(*color, 255), width=OUTLINE_WIDTH, joint="curve")
        img = Image.alpha_composite(img, layer)

    if locations:
        img = add_location_markers(img, locations, marker_color, BACKGROUND_IMAGE_BBOX)

    with io.BytesIO() as output:
        img.save(output, format="PNG")
        return output.getvalue()


class WeatherAlertsImage(ImageEntity):
    """Map of active weather warnings."""

    _attr_content_type = "image/png"
    _attr_should_poll = False
    _attr_translation_key = "weather_alert_map"

    def __init__(self, hass: HomeAssistant, config_entry: NLWeatherConfigEntry) -> None:
        super().__init__(hass)
        self._coordinator = config_entry.runtime_data.alerts_coordinator
        self._style = RADAR_STYLES[
            config_entry.options.get(CONF_RADAR_STYLE, DEFAULT_RADAR_STYLE)
        ]
        self._locations: list[Coordinate] = []
        if config_entry.options.get(CONF_MARK_LOCATIONS, True):
            self._locations = [
                Coordinate(s.data[CONF_LATITUDE], s.data[CONF_LONGITUDE])
                for s in config_entry.subentries.values()
            ]
        self._background: Image.Image | None = None
        self._image: bytes | None = None
        self._attr_unique_id = f"{config_entry.entry_id}_weather_alert_map"
        self._attr_device_info = DeviceInfo(
            name="Waarschuwingenkaart",
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_weather_alerts")},
            manufacturer="KNMI.nl",
            configuration_url="https://www.knmi.nl",
        )

    def _load_background(self) -> None:
        path = os.path.join(os.path.dirname(__file__), self._style.background_image)
        with open(path, "rb") as f:
            self._background = Image.open(f, formats=["PNG"]).convert("RGBA")

    async def _render(self) -> None:
        if self._coordinator.data is None:
            return
        self._image = await self.hass.async_add_executor_job(
            render_alerts,
            self._background,
            self._coordinator.data,
            self._locations,
            self._style.marker_color,
        )
        self._attr_image_last_updated = utcnow()
        self.async_write_ha_state()

    @callback
    def _handle_update(self) -> None:
        self.hass.async_create_task(self._render())

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.hass.async_add_executor_job(self._load_background)
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_update))
        await self._render()

    async def async_image(self) -> bytes | None:
        return self._image
