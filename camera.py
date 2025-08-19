"""Provide animated GIF loops of Buienradar imagery."""

from __future__ import annotations

import asyncio
import io
import os
from datetime import datetime, timedelta, timezone
import logging
from math import floor
from typing import BinaryIO

import voluptuous as vol
from PIL import Image, ImageDraw

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import KNMIDirectConfigEntry

_LOGGER = logging.getLogger(__name__)

# Maximum range according to docs
DIM_RANGE = vol.All(vol.Coerce(int), vol.Range(min=120, max=700))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: KNMIDirectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    ns = config_entry.runtime_data.notification_service
    wms = config_entry.runtime_data.wms

    async_add_entities([PrecipitationRadarCam(ns, wms)])


class PrecipitationRadarCam(Camera):
    """A camera component producing animated radar-imagery GIFs.

    Rain radar imagery camera based on image URL taken from [0].

    [0]: https://dataplatform.knmi.nl/dataset/radar-forecast-2-0
    """

    _attr_name = "KNMI"
    _background_image: BinaryIO
    _last_image: bytes | None = None
    _last_image_dt: datetime | None = None
    _last_modified: datetime | None = None
    _loading = False

    def __init__(
        self, ns, wms
    ) -> None:
        """Initialize the component.

        This constructor must be run in the event loop.
        """
        super().__init__()

        # Condition that guards the loading indicator.
        #
        # Ensures that only one reader can cause an http request at the same
        # time, and that all readers are notified after this request completes.
        #
        # invariant: this condition is private to and owned by this instance.
        self._condition = asyncio.Condition()

        # TODO: Improve
        self._attr_unique_id = f"radar_foobar"

        self._ns = ns
        self._wms = wms


    def _load_background(self):
        filename = os.path.join(os.path.dirname(__file__), "background.png")
        with open(filename, 'rb') as f:
            self._background_image = io.BytesIO(f.read())

    def __needs_refresh(self) -> bool:
        if self._last_modified is None or self._last_image_dt is None :
            return True

        return self._last_modified > self._last_image_dt

    async def __retrieve_radar_image(self, ref_time) -> bool:
        """Retrieve new radar image and return whether this succeeded."""
        time = ref_time
        images = list()

        while time <= ref_time + timedelta(minutes=120):
            radar_im = await self._wms.get(ref_time, time)
            bg_im = Image.open(self._background_image, formats=["PNG"]).convert("RGBA")
            bg_im.paste(radar_im, (0, 0), radar_im)
            draw = ImageDraw.Draw(bg_im)
            draw.text((28, 28), dt_util.as_local(time).strftime("%a %H:%M"), fill=(255, 255, 255), font_size=45, stroke_width=0.8)
            images.append(bg_im)

            time += timedelta(minutes=5)

        _LOGGER.info("Setting image")

        im = io.BytesIO()
        images[0].save(im, format='GIF', save_all=True, append_images=images[1:], optimize=True, duration=500, loop=0,
                       disposal=0)
        self._last_image = im.getvalue()

        return True


    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:

        if not self.__needs_refresh():
            return self._last_image

        if self._last_modified is None:
            # No event received yet. Retrieve initial image from 5 or more minutes ago
            now = dt_util.utcnow()
            self._last_modified = now.replace(minute=floor(now.minute / 5) * 5, second=0, microsecond=0) - timedelta(
                minutes=5)

        # get lock, check iff loading, await notification if loading
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
        # TODO: Build in retry during loading
        await asyncio.sleep(15)
        self._last_modified = datetime.strptime(event["data"]["filename"],
                                           "RAD_NL25_RAC_FM_%Y%m%d%H%M.h5").replace(
            tzinfo=timezone.utc)

    async def async_added_to_hass(self):
        self._ns.set_callback('radar_forecast', self._set_latest)

        # TODO: Best place to do this?
        await self.hass.async_add_executor_job(self._load_background)