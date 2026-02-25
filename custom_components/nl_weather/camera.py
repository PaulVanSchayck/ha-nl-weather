"""Provide animated GIF loops of KNMI radar images fetched from WMS."""

from __future__ import annotations

import asyncio
import io
import os
from datetime import datetime, timedelta, timezone
import logging
from PIL import Image, ImageDraw
from PIL.ImageFile import ImageFile

from homeassistant.components.camera import Camera
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo, DeviceEntryType
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import KNMIDirectConfigEntry
from .KNMI.helpers import epsg4325_to_epsg3857
from .const import (
    CONF_MARK_LOCATIONS,
    CONF_RADAR_STYLE,
    DEFAULT_RADAR_STYLE,
    DOMAIN,
    RADAR_STYLES,
    RadarStyle,
)


_LOGGER = logging.getLogger(__name__)

# BBOX in EPSG:3857 (Web Mercator). This is (49.14, 0.0, 54,68, 8.98) in EPSG:4326
BACKGROUND_IMAGE_BBOX = (0.0, 6300000, 1000000, 7300000)
BACKGROUND_IMAGE_BBOX_PARAM = ",".join(map(str, BACKGROUND_IMAGE_BBOX))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: KNMIDirectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([PrecipitationRadarCam(config_entry)])


class PrecipitationRadarCam(Camera):
    """A camera component producing animated radar-imagery GIFs.

    Rain radar imagery camera based on image URL taken from [0].

    [0]: https://dataplatform.knmi.nl/dataset/radar-forecast-2-0
    """

    _radar_style: RadarStyle
    _background_image: ImageFile
    _last_image: bytes | None = None
    _last_image_dt: datetime | None = None
    _last_modified: datetime | None = None
    _loading = False
    _mark_locations = True
    _locations = []

    def __init__(self, config_entry: KNMIDirectConfigEntry) -> None:
        super().__init__()

        # Condition that guards the loading indicator.
        # Ensures that only one reader can cause an http request at the same
        # time, and that all readers are notified after this request completes.
        self._condition = asyncio.Condition()

        self._attr_unique_id = f"{config_entry.entry_id}_precipitation_radar"

        self._attr_device_info = DeviceInfo(
            name="Neerslagradar",
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_precipitation_radar")},
            manufacturer="KNMI.nl",
            configuration_url="https://www.knmi.nl",
        )
        self._attr_translation_key = "precipitation_radar"

        self._ns = config_entry.runtime_data.notification_service
        self._wms = config_entry.runtime_data.wms

        self._radar_style = RADAR_STYLES[
            config_entry.options.get(CONF_RADAR_STYLE, DEFAULT_RADAR_STYLE)
        ]

        self._mark_locations = config_entry.options.get(CONF_MARK_LOCATIONS, True)

        # TODO: Deal with adding/removing location
        self._locations = []
        for s in config_entry.subentries.values():
            if s.subentry_type == "location":
                self._locations.append(
                    {
                        "lat": s.data[CONF_LATITUDE],
                        "lon": s.data[CONF_LONGITUDE],
                    }
                )

    def _add_locations_markers(self, img):
        draw = ImageDraw.Draw(img)
        for location in self._locations:
            # Convert from lat lon in degrees to x y in meters
            x, y = epsg4325_to_epsg3857(location["lon"], location["lat"])
            # Calculate position on image.
            y_img = (
                img.size[0]
                / (BACKGROUND_IMAGE_BBOX[3] - BACKGROUND_IMAGE_BBOX[1])
                * (y - BACKGROUND_IMAGE_BBOX[1])
            )
            x_img = (
                img.size[1]
                / (BACKGROUND_IMAGE_BBOX[2] - BACKGROUND_IMAGE_BBOX[0])
                * (x - BACKGROUND_IMAGE_BBOX[0])
            )
            # Image is downwards from y so flip
            y_img = img.size[0] - y_img

            draw.circle(
                (x_img, y_img), 10, None, self._radar_style.marker_color, width=2
            )

        return img

    def _load_background(self):
        path = os.path.join(
            os.path.dirname(__file__), self._radar_style.background_image
        )

        with open(path, "rb") as f:
            img = Image.open(f, formats=["PNG"]).convert("RGBA")

        if self._mark_locations:
            img = self._add_locations_markers(img)

        self._background_image = img

    def __needs_refresh(self) -> bool:
        if self._last_modified is None or self._last_image_dt is None:
            return True

        return self._last_modified > self._last_image_dt

    async def __retrieve_radar_image(self, ref_time) -> bool:
        """Retrieve new radar image and return whether this succeeded."""
        images = list()
        fetch = list()

        async def fetch_forecast_with_time(r, t):
            return t, await self._wms.radar_forecast_image(
                r,
                t,
                self._background_image.size,
                BACKGROUND_IMAGE_BBOX_PARAM,
                self._radar_style.wms_style,
            )

        async def fetch_realtime_with_time(t):
            return t, await self._wms.radar_real_time_image(
                t,
                self._background_image.size,
                BACKGROUND_IMAGE_BBOX_PARAM,
                self._radar_style.wms_style,
            )

        # Fetch images from previous hour
        time = ref_time - timedelta(minutes=60)
        while time < ref_time:
            fetch.append(fetch_realtime_with_time(time))
            time += timedelta(minutes=10)
        time = ref_time
        # Fetch prediction for next two hour
        while time <= ref_time + timedelta(minutes=120):
            fetch.append(fetch_forecast_with_time(ref_time, time))
            time += timedelta(minutes=10)

        # TODO: Handle errors better here
        radar_images = await asyncio.gather(*fetch)

        _LOGGER.debug("Done retrieving radar images, now converting to gif")

        for time, buf in radar_images:
            img = Image.open(buf, formats=["PNG"]).convert("RGBA")
            draw = ImageDraw.Draw(img)
            draw.text(
                (28, 28),
                dt_util.as_local(time).strftime("%a %H:%M"),
                fill=self._radar_style.time_past_color
                if time <= ref_time
                else self._radar_style.time_future_color,
                font_size=45,
                stroke_width=0.8,
            )
            images.append(Image.composite(img, self._background_image, img))

        _LOGGER.debug("Generated image")

        with io.BytesIO() as output:
            images[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=images[1:],
                optimize=False,
                duration=300,
                loop=1,
                disposal=2,
            )
            self._last_image = output.getvalue()

        _LOGGER.debug("Stored image")

        return True

    async def __latest_image_datetime(self):
        # Get the latest available image from a GetCapabilities call
        tree = await self._wms.get_capabilities_radar()
        root = tree.getroot()

        for dim in root.findall(".//{*}Dimension[@name='time']"):
            start, end, period = dim.text.strip().split("/")
            return datetime.fromisoformat(end.replace("Z", "+00:00"))

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        if not self.__needs_refresh():
            return self._last_image

        if self._last_modified is None:
            # No event received yet
            self._last_modified = await self.__latest_image_datetime()

        # get lock, check if loading, await notification if loading
        async with self._condition:
            # cannot be tested - mocked http response returns immediately
            if self._loading:
                _LOGGER.debug("already loading - waiting for notification")
                await self._condition.wait()
                return self._last_image

            # Set loading status **while holding lock**, makes other tasks wait
            self._loading = True

        try:
            was_updated = await self.__retrieve_radar_image(self._last_modified)

            if was_updated:
                self._last_image_dt = self._last_modified

            return self._last_image
        finally:
            # get lock, unset loading status, notify all waiting tasks
            async with self._condition:
                self._loading = False
                self._condition.notify_all()

    async def _set_latest(self, event):
        # Allowing for some time for the image to be available in WMS
        await asyncio.sleep(15)
        self._last_modified = datetime.strptime(
            event["data"]["filename"], "RAD_NL25_RAC_FM_%Y%m%d%H%M.h5"
        ).replace(tzinfo=timezone.utc)

    async def async_added_to_hass(self):
        self._ns.set_callback("radar_forecast", self._attr_unique_id, self._set_latest)

        # TODO: Best place to do this?
        await self.hass.async_add_executor_job(self._load_background)
