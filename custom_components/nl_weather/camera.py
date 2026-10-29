"""Provide animated GIF loops of KNMI radar images fetched from WMS."""

from __future__ import annotations

import asyncio
import io
import logging
import os
from datetime import UTC, datetime, timedelta
from random import randint

from homeassistant.components.camera import Camera
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from PIL import Image, ImageDraw
from PIL.ImageFile import ImageFile

from .const import (
    CONF_CENTER_LATITUDE,
    CONF_CENTER_LONGITUDE,
    CONF_CENTER_MODE,
    CONF_MAP_PROVIDER,
    CONF_MAP_STYLE,
    CONF_MARK_LOCATIONS,
    CONF_RADAR_STYLE,
    CONF_ZOOM_LEVEL,
    DEFAULT_CENTER_MODE,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_OSM_MAP_STYLE,
    DEFAULT_RADAR_STYLE,
    DEFAULT_ZOOM_LEVEL,
    DOMAIN,
    RADAR_STYLES,
    CenterMode,
    MapProvider,
    OSMMapStyle,
    RadarStyle,
)
from .coordinator import NLWeatherConfigEntry
from .KNMI.helpers import Coordinate, epsg4325_to_epsg3857
from .KNMI.osm import (
    OSMTileManager,
    calculate_auto_zoom_and_bbox,
    calculate_bbox_for_zoom,
    calculate_weighted_center,
    get_known_zones,
)
from .KNMI.wms import WMSException

_LOGGER = logging.getLogger(__name__)

# BBOX in EPSG:3857 (Web Mercator). This is (49.14, 0.0, 54,68, 8.98) in EPSG:4326
BACKGROUND_IMAGE_BBOX = (0.0, 6300000, 1000000, 7300000)
BACKGROUND_IMAGE_BBOX_PARAM = ",".join(map(str, BACKGROUND_IMAGE_BBOX))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NLWeatherConfigEntry,
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
    _locations: list[Coordinate]
    _radar_bbox: tuple[float, float, float, float]
    _radar_bbox_param: str

    def __init__(self, config_entry: NLWeatherConfigEntry) -> None:
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
        self._config_entry = config_entry

        self._map_provider = config_entry.options.get(
            CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER
        )
        self._map_style = OSMMapStyle(
            config_entry.options.get(CONF_MAP_STYLE, DEFAULT_OSM_MAP_STYLE)
        )
        self._radar_style_key = config_entry.options.get(
            CONF_RADAR_STYLE, DEFAULT_RADAR_STYLE
        )
        self._radar_style = RADAR_STYLES[self._radar_style_key]

        self._zoom_level = config_entry.options.get(CONF_ZOOM_LEVEL, DEFAULT_ZOOM_LEVEL)
        self._center_mode = config_entry.options.get(
            CONF_CENTER_MODE, DEFAULT_CENTER_MODE
        )
        self._center_latitude = config_entry.options.get(CONF_CENTER_LATITUDE)
        self._center_longitude = config_entry.options.get(CONF_CENTER_LONGITUDE)

        self._mark_locations = config_entry.options.get(CONF_MARK_LOCATIONS, True)

        self._radar_bbox = BACKGROUND_IMAGE_BBOX
        self._radar_bbox_param = BACKGROUND_IMAGE_BBOX_PARAM

        # Subentry locations
        self._locations = []
        for s in config_entry.subentries.values():
            self._locations.append(
                Coordinate(s.data[CONF_LATITUDE], s.data[CONF_LONGITUDE])
            )

    def _add_locations_markers(
        self, img: Image.Image, bbox: tuple[float, float, float, float]
    ) -> Image.Image:
        draw = ImageDraw.Draw(img)
        xmin, ymin, xmax, ymax = bbox
        width, height = img.size
        for location in self._locations:
            # Convert from lat lon in degrees to x y in meters
            x, y = epsg4325_to_epsg3857(location)
            if not (xmin <= x <= xmax and ymin <= y <= ymax):
                continue
            # Calculate position on image.
            x_img = (x - xmin) / (xmax - xmin) * width
            y_img = (ymax - y) / (ymax - ymin) * height

            draw.circle(
                (x_img, y_img), 10, None, self._radar_style.marker_color, width=2
            )

        return img

    def _load_static_background(self) -> Image.Image:
        path = os.path.join(
            os.path.dirname(__file__), self._radar_style.background_image
        )

        with open(path, "rb") as f:
            img = Image.open(f, formats=["PNG"]).convert("RGBA")

        if self._mark_locations:
            img = self._add_locations_markers(img, BACKGROUND_IMAGE_BBOX)

        return img

    async def async_load_background(self) -> None:
        if self._map_provider == MapProvider.STATIC:
            self._radar_bbox = BACKGROUND_IMAGE_BBOX
            self._radar_bbox_param = BACKGROUND_IMAGE_BBOX_PARAM
            self._background_image = await self.hass.async_add_executor_job(
                self._load_static_background
            )
            return

        # OSM Provider
        session = async_get_clientsession(self.hass)
        cache_dir = self.hass.config.path(".storage", "ha_nl_weather")
        tile_manager = OSMTileManager(session, cache_dir)

        zones = get_known_zones(self.hass, self._config_entry)
        for lat, lon, _ in zones:
            coord = Coordinate(lat, lon)
            if coord not in self._locations:
                self._locations.append(coord)

        if (
            self._center_mode == CenterMode.CUSTOM
            and self._center_latitude is not None
            and self._center_longitude is not None
        ):
            center = Coordinate(
                lat=float(self._center_latitude),
                lon=float(self._center_longitude),
            )
        else:
            center = calculate_weighted_center(zones)

        osm_size = (1024, 1024)
        if str(self._zoom_level).lower() == DEFAULT_ZOOM_LEVEL:
            zoom, bbox = calculate_auto_zoom_and_bbox(
                zones, center, image_size=osm_size, padding=0.50
            )
        else:
            zoom = int(self._zoom_level)
            bbox = calculate_bbox_for_zoom(center, zoom, image_size=osm_size)

        self._radar_bbox = bbox
        self._radar_bbox_param = (
            f"{bbox[0]:.1f},{bbox[1]:.1f},{bbox[2]:.1f},{bbox[3]:.1f}"
        )

        is_dark = self._radar_style_key == "dark"
        img = await tile_manager.async_get_osm_background(
            self.hass, bbox, osm_size, zoom, self._map_style, is_dark
        )

        if self._mark_locations:
            img = await self.hass.async_add_executor_job(
                self._add_locations_markers, img, bbox
            )

        self._background_image = img

    def __needs_refresh(self) -> bool:
        if self._last_modified is None or self._last_image_dt is None:
            return True

        return self._last_modified > self._last_image_dt

    async def __retrieve_radar_image(self, ref_time) -> bool:
        """Retrieve new radar image and return whether this succeeded."""
        time_to_image = await self._fetch_radar_frames(ref_time)

        if not time_to_image:
            _LOGGER.warning("No radar images were successfully retrieved")
            return self._error_image()

        _LOGGER.debug("Done retrieving radar images, now converting to gif")
        self._assemble_radar_gif(time_to_image)
        return True

    async def _fetch_radar_frames(self, ref_time) -> dict[datetime, Image.Image]:
        async def fetch_forecast_with_time(r, t):
            return t, await self._wms.radar_forecast_image(
                r,
                t,
                self._background_image.size,
                self._radar_bbox_param,
                self._radar_style.wms_style,
            )

        async def fetch_realtime_with_time(t):
            return t, await self._wms.radar_real_time_image(
                t,
                self._background_image.size,
                self._radar_bbox_param,
                self._radar_style.wms_style,
            )

        pending_tasks: dict[asyncio.Task[tuple[datetime, io.BytesIO]], datetime] = {}
        # Fetch images from previous hour
        time = ref_time - timedelta(minutes=60)
        while time < ref_time:
            task = asyncio.create_task(fetch_realtime_with_time(time))
            pending_tasks[task] = time
            time += timedelta(minutes=10)

        # Fetch prediction for next two hour
        time = ref_time
        while time <= ref_time + timedelta(minutes=120):
            task = asyncio.create_task(fetch_forecast_with_time(ref_time, time))
            pending_tasks[task] = time
            time += timedelta(minutes=10)

        time_to_image: dict[datetime, Image.Image] = {}

        _LOGGER.debug(f"Fetching {len(pending_tasks)} radar images")

        try:
            # We seem to have 10 seconds to assemble the image. Wait for 7 seconds and allow for some time to assemble the gif
            async with asyncio.timeout(7):
                for completed_task in asyncio.as_completed(pending_tasks.keys()):
                    try:
                        img_time, buf = await completed_task
                        time_to_image[img_time] = self._process_radar_frame(
                            buf, img_time, ref_time
                        )
                    except (TimeoutError, WMSException) as e:
                        _LOGGER.warning("Error processing radar image: %s", e)
                        continue
                    except Exception:
                        _LOGGER.exception("Error processing radar image")
                        for task in pending_tasks:
                            task.cancel()
                        break
        except TimeoutError:
            for task in pending_tasks:
                task.cancel()
            _LOGGER.warning(
                f"Retrieving radar images timed out after 7 seconds and {len(time_to_image)} radar frames"
            )

        _LOGGER.debug(f"Retrieved and processed {len(time_to_image)} radar frames")
        return time_to_image

    def _process_radar_frame(
        self, buf: io.BytesIO, img_time: datetime, ref_time: datetime
    ) -> Image.Image:
        img = Image.open(buf, formats=["PNG"]).convert("RGBA")
        del buf

        draw = ImageDraw.Draw(img)
        draw.text(
            (28, 28),
            dt_util.as_local(img_time).strftime("%a %H:%M"),
            fill=self._radar_style.time_past_color
            if img_time <= ref_time
            else self._radar_style.time_future_color,
            font_size=45,
            stroke_width=0.8,
        )

        composite = Image.composite(img, self._background_image, img)
        img.close()
        return composite

    def _error_image(self) -> bool:
        with io.BytesIO() as output:
            img = self._background_image.copy()
            draw = ImageDraw.Draw(img)
            draw.text(
                (28, 28),
                "No radar images were successfully retrieved (check log)",
                fill="red",
                font_size=40,
                stroke_width=0.8,
            )
            img.save(output, format="GIF")
            self._last_image = output.getvalue()

        return True

    def _assemble_radar_gif(self, time_to_image: dict[datetime, Image.Image]) -> None:
        sorted_times = sorted(time_to_image.keys())
        images = [time_to_image[t] for t in sorted_times]

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

        for img in images:
            img.close()

        _LOGGER.debug("Stored image")

    async def __latest_image_datetime(self):
        # Get the latest available image from a GetCapabilities call
        try:
            tree = await self._wms.get_capabilities_radar()
        except WMSException as e:
            _LOGGER.warning("Cannot GetCapabilities from WMS: %s", e)
            return None

        root = tree.getroot()

        for dim in root.findall(".//{*}Dimension[@name='time']"):
            _, end, _ = dim.text.strip().split("/")
            return datetime.fromisoformat(end)
        return None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        if not self.__needs_refresh():
            return self._last_image

        if self._last_modified is None:
            # No event received yet
            self._last_modified = await self.__latest_image_datetime()
            if self._last_modified is None:
                return None

        # get lock, check if loading, await notification if loading
        async with self._condition:
            # Check in loop. wait() method may return spuriously
            while self._loading:
                _LOGGER.debug("already loading - waiting for notification")
                await self._condition.wait()

            if not self.__needs_refresh():
                return self._last_image
            else:
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
        # Allowing for some time for the image to be available in WMS, plus some jitter time to allow to hit the cache more often
        await asyncio.sleep(15 + randint(0, 10))
        self._last_modified = datetime.strptime(
            event["data"]["filename"], "RAD_NL25_RAC_FM_%Y%m%d%H%M.h5"
        ).replace(tzinfo=UTC)

    async def async_added_to_hass(self):
        self._ns.set_callback("radar_forecast", self._attr_unique_id, self._set_latest)

        await self.async_load_background()
