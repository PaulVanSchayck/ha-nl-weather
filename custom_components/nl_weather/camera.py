"""Provide animated GIF loops of KNMI radar and wind particle images."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from random import randint

import aiohttp
from homeassistant.components.camera import Camera
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from PIL import Image, ImageDraw

from .const import (
    CONF_CARTO_API_KEY,
    CONF_CENTER_LATITUDE,
    CONF_CENTER_LONGITUDE,
    CONF_CENTER_MODE,
    CONF_ENABLED_MAPS,
    CONF_MAP_PROVIDER,
    CONF_MAP_STYLE,
    CONF_MARK_LOCATIONS,
    CONF_RADAR_STYLE,
    CONF_ZOOM_LEVEL,
    DEFAULT_CENTER_MODE,
    DEFAULT_ENABLED_MAPS,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_OSM_MAP_STYLE,
    DEFAULT_RADAR_STYLE,
    DEFAULT_ZOOM_LEVEL,
    DOMAIN,
    OSM_CACHE_TTL_SECONDS,
    RADAR_STYLES,
    CenterMode,
    MapProvider,
    MapType,
    OSMMapStyle,
    RadarStyle,
)
from .coordinator import NLWeatherConfigEntry
from .KNMI.edr import InvalidRequest, NotFoundError, ServerError, TokenInvalid
from .KNMI.helpers import Coordinate, epsg4325_to_epsg3857
from .KNMI.osm import (
    OSMTileManager,
    calculate_auto_zoom_and_bbox,
    calculate_bbox_for_zoom,
    calculate_weighted_center,
    get_known_zones,
)
from .KNMI.wind import (
    WindObservation,
    WindParticleEngine,
    WindVectorGrid,
    create_app_target_wind_observation,
    parse_edr_wind_coverages,
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
    """Set up NL Weather camera entities."""
    enabled_maps = config_entry.options.get(CONF_ENABLED_MAPS, DEFAULT_ENABLED_MAPS)
    entities: list[Camera] = []

    if MapType.PRECIPITATION.value in enabled_maps:
        entities.append(PrecipitationRadarCam(config_entry))
    if MapType.WIND.value in enabled_maps:
        entities.append(WindParticlesCam(config_entry))
    if MapType.HYBRID.value in enabled_maps:
        entities.append(HybridWeatherCam(config_entry))

    async_add_entities(entities)


class KNMICamera(Camera):
    """Base camera component for KNMI map imagery with static or OSM background."""

    _radar_style: RadarStyle
    _background_image: Image.Image | None = None
    _last_image: bytes | None = None
    _last_image_dt: datetime | None = None
    _last_modified: datetime | None = None
    _loading: bool = False
    _mark_locations: bool = True
    _locations: list[Coordinate]
    _radar_bbox: tuple[float, float, float, float]
    _radar_bbox_param: str
    _background_mtime: float | None = None

    def __init__(self, config_entry: NLWeatherConfigEntry) -> None:
        """Initialize common KNMI camera configuration."""
        super().__init__()
        self._condition = asyncio.Condition()
        self._config_entry = config_entry

        self._map_provider = config_entry.options.get(
            CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER
        )
        self._map_style = OSMMapStyle(
            config_entry.options.get(CONF_MAP_STYLE, DEFAULT_OSM_MAP_STYLE)
        )
        self._carto_api_key = config_entry.options.get(CONF_CARTO_API_KEY)
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
        """Load or update base map background (OSM or static)."""
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
        carto_key = self._carto_api_key
        img = await tile_manager.async_get_osm_background(
            self.hass,
            bbox,
            osm_size,
            zoom,
            self._map_style,
            is_dark,
            carto_api_key=carto_key,
        )

        if self._mark_locations:
            img = await self.hass.async_add_executor_job(
                self._add_locations_markers, img, bbox
            )

        self._background_image = img
        bg_cache_path = tile_manager._get_background_cache_path(
            bbox, osm_size, zoom, self._map_style.value, is_dark, carto_key
        )
        try:
            self._background_mtime = await asyncio.to_thread(
                os.path.getmtime, bg_cache_path
            )
        except OSError:
            self._background_mtime = time.time()

    async def async_ensure_background(self) -> None:
        """Ensure base background map is loaded and fresh."""
        if self._map_provider == MapProvider.OSM:
            now = time.time()
            if (
                self._background_image is None
                or self._background_mtime is None
                or (now - self._background_mtime) >= OSM_CACHE_TTL_SECONDS
            ):
                await self.async_load_background()
        elif self._background_image is None:
            await self.async_load_background()

    async def _latest_radar_datetime(self) -> datetime | None:
        """Get the latest available radar image datetime from WMS GetCapabilities."""
        wms = getattr(self, "_wms", None) or self._config_entry.runtime_data.wms
        try:
            tree = await wms.get_capabilities_radar()
        except (WMSException, aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.warning("Cannot GetCapabilities from WMS: %s", e)
            return None

        root = tree.getroot()
        for dim in root.findall(".//{*}Dimension[@name='time']"):
            _, end, _ = dim.text.strip().split("/")
            return datetime.fromisoformat(end.replace("Z", "+00:00"))
        return None

    async def _latest_wind_datetime(self) -> datetime | None:
        """Get the latest available wind image datetime from WMS GetCapabilities."""
        wms = getattr(self, "_wms", None) or self._config_entry.runtime_data.wms
        try:
            tree = await wms.get_capabilities_wind()
        except (
            WMSException,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            TypeError,
            AttributeError,
        ) as e:
            _LOGGER.debug("Cannot GetCapabilities for wind from WMS: %s", e)
            return None

        root = tree.getroot()
        for dim in root.findall(".//{*}Dimension[@name='time']"):
            times = dim.text.strip().split("/")
            if len(times) >= 2:
                return datetime.fromisoformat(times[1].replace("Z", "+00:00"))
        return None

    async def _retrieve_wind_speed_raster(
        self,
        masked: bool = False,
    ) -> tuple[Image.Image | None, list[dict] | None, datetime | None]:
        """Retrieve 10m surface wind speed raster image and dynamic legend steps.

        Prioritizes WMS high_resolution_weather_maps (windspeed_mean or windspeed_mean_masked)
        projected natively in EPSG:3857 for pixel-perfect alignment with both static
        and OSM basemaps, falling back to KNMI App API.
        """
        wms = getattr(self, "_wms", None) or getattr(
            self._config_entry.runtime_data, "wms", None
        )
        if wms:
            wind_time = await self._latest_wind_datetime() or dt_util.utcnow()
            try:
                wind_buf = await wms.wind_speed_image(
                    wind_time,
                    (600, 600),
                    self._radar_bbox_param,
                    style="windspeed_0_10",
                    masked=masked,
                )
                img = Image.open(wind_buf, formats=["PNG"]).convert("RGBA")
                return img, None, wind_time
            except (
                WMSException,
                aiohttp.ClientError,
                asyncio.TimeoutError,
                TypeError,
                AttributeError,
                KeyError,
                ValueError,
                OSError,
            ) as e:
                _LOGGER.debug(
                    "Could not fetch wind speed raster from WMS (falling back to App API): %s",
                    e,
                )

        app = getattr(self, "_app", None) or getattr(
            self._config_entry.runtime_data, "app", None
        )
        if app:
            try:
                meas = await app.windspeed_measurements(unit="kilometerPerHour")
                detail_url = meas.get("links", {}).get("detail")
                legend_steps = meas.get("legend", {}).get("steps", [])
                time_str = meas.get("time")
                wind_dt = (
                    datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    if time_str
                    else dt_util.utcnow()
                )
                if detail_url:
                    session = async_get_clientsession(self.hass)
                    async with session.get(
                        detail_url, headers={"User-Agent": "Mozilla/5.0"}
                    ) as resp:
                        img_data = await resp.read()
                        img = Image.open(io.BytesIO(img_data)).convert("RGBA")
                        return img, legend_steps, wind_dt
                return None, legend_steps, wind_dt
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                TypeError,
                AttributeError,
                KeyError,
                ValueError,
                OSError,
            ) as e:
                _LOGGER.debug(
                    "Could not fetch wind speed from App API: %s",
                    e,
                )

        return None, None, dt_util.utcnow()

    def _get_target_wind_observations(self) -> list[WindObservation]:
        """Extract wind observations from configured App API target coordinators."""
        target_observations: list[WindObservation] = []
        runtime_data = getattr(self._config_entry, "runtime_data", None)
        if not runtime_data:
            return target_observations

        app_coordinators = getattr(runtime_data, "app_coordinators", {})
        if not app_coordinators:
            return target_observations

        subentries = getattr(self._config_entry, "subentries", {})
        for subentry_id, subentry in subentries.items():
            coord = app_coordinators.get(subentry_id)
            if not coord or not coord.data:
                continue

            wind_data = coord.data.get("wind")
            if not wind_data and "hourly" in coord.data:
                hourly = coord.data.get("hourly", {}).get("forecast", [])
                if hourly and isinstance(hourly[0], dict):
                    wind_data = hourly[0].get("wind")

            lat = subentry.data.get(CONF_LATITUDE)
            lon = subentry.data.get(CONF_LONGITUDE)
            if lat is None or lon is None:
                continue

            target_obs = create_app_target_wind_observation(
                station_id=f"app_target_{subentry_id}",
                lat=lat,
                lon=lon,
                wind_data=wind_data,
            )
            if target_obs:
                target_observations.append(target_obs)

        return target_observations


class PrecipitationRadarCam(KNMICamera):
    """A camera component producing animated radar-imagery GIFs.

    Rain radar imagery camera based on image URL taken from [0].

    [0]: https://dataplatform.knmi.nl/dataset/radar-forecast-2-0
    """

    def __init__(self, config_entry: NLWeatherConfigEntry) -> None:
        """Initialize precipitation radar camera."""
        super().__init__(config_entry)

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

    def __needs_refresh(self) -> bool:
        if self._last_modified is None or self._last_image_dt is None:
            return True

        return self._last_modified > self._last_image_dt

    async def __retrieve_radar_image(self, ref_time) -> bool:
        """Retrieve new radar image and return whether this succeeded."""
        await self.async_ensure_background()

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


    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of animated radar imagery GIF."""
        if not self.__needs_refresh():
            return self._last_image

        if self._last_modified is None:
            # No event received yet
            self._last_modified = await self._latest_radar_datetime()
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
        """Register radar callbacks and load background."""
        self._ns.set_callback("radar_forecast", self._attr_unique_id, self._set_latest)
        await self.async_load_background()


class WindParticlesCam(KNMICamera):
    """A camera component producing animated particle wind loops from KNMI EDR observations."""

    def __init__(self, config_entry: NLWeatherConfigEntry) -> None:
        """Initialize wind particles camera."""
        super().__init__(config_entry)

        self._attr_unique_id = f"{config_entry.entry_id}_wind_particles"
        self._attr_device_info = DeviceInfo(
            name="Windkaart",
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_wind_particles")},
            manufacturer="KNMI.nl",
            configuration_url="https://www.knmi.nl",
        )
        self._attr_translation_key = "wind_particles"

        self._app = config_entry.runtime_data.app
        self._edr = config_entry.runtime_data.edr
        self._wms = config_entry.runtime_data.wms
        self._ns = config_entry.runtime_data.notification_service

    def __needs_refresh(self) -> bool:
        if self._last_image is None or self._last_image_dt is None:
            return True

        if self._last_modified and self._last_modified > self._last_image_dt:
            return True

        # Refresh every 10 minutes matching KNMI 10-minute in-situ observations cadence
        return (dt_util.utcnow() - self._last_image_dt) >= timedelta(minutes=10)

    async def _retrieve_wind_image(self) -> bool:
        """Retrieve wind observations and render seamless particle animation GIF."""
        await self.async_ensure_background()

        if self._background_image is None:
            _LOGGER.warning("No background image loaded for wind particles camera")
            return False

        (
            wind_speed_img,
            legend_steps,
            wind_time,
        ) = await self._retrieve_wind_speed_raster()
        if wind_time is None:
            wind_time = dt_util.utcnow()

        base_composite = self._background_image.resize(
            (600, 600), Image.Resampling.LANCZOS
        ).convert("RGBA")

        observations = []
        try:
            coverages = await self._edr.get_wind_observations()
            observations = parse_edr_wind_coverages(coverages)
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ServerError,
            NotFoundError,
            TokenInvalid,
            InvalidRequest,
            KeyError,
        ) as e:
            _LOGGER.warning("Error fetching wind observations from EDR: %s", e)

        # Mix in hyper-local target wind observations from the KNMI App API
        observations.extend(self._get_target_wind_observations())

        if not observations and wind_speed_img is None:
            _LOGGER.warning("No valid wind observations returned from EDR or App API")
            if self._last_image:
                return True
            return self._error_image("No wind observations available")

        grid = WindVectorGrid(
            observations,
            self._radar_bbox,
            grid_w=40,
            grid_h=40,
        )
        if wind_speed_img:
            grid.apply_speed_raster(wind_speed_img, legend_steps=legend_steps)

        engine = WindParticleEngine(
            grid,
            canvas_size=(600, 600),
            n_particles=750,
            n_frames=30,
            frame_duration_ms=70,
            vel_scale=0.85,
        )

        now = dt_util.as_local(wind_time)
        header_color = self._radar_style.time_past_color

        self._last_image = await self.hass.async_add_executor_job(
            engine.render_animation,
            base_composite,
            now,
            header_color,
        )
        self._last_image_dt = dt_util.utcnow()
        return True

    def _error_image(self, message: str) -> bool:
        with io.BytesIO() as output:
            img = (
                self._background_image.copy()
                if self._background_image
                else Image.new("RGBA", (600, 600), (30, 30, 30, 255))
            )
            draw = ImageDraw.Draw(img)
            draw.text(
                (24, 24),
                message,
                fill="red",
                font_size=28,
                stroke_width=1,
            )
            img.save(output, format="GIF")
            self._last_image = output.getvalue()

        return True

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of animated wind particles GIF."""
        if not self.__needs_refresh():
            return self._last_image

        async with self._condition:
            while self._loading:
                _LOGGER.debug("Wind camera already loading - waiting for notification")
                await self._condition.wait()

            if not self.__needs_refresh():
                return self._last_image

            self._loading = True

        try:
            await self._retrieve_wind_image()
            return self._last_image
        finally:
            async with self._condition:
                self._loading = False
                self._condition.notify_all()

    async def _set_latest(self, event):
        """Notification callback when new in-situ observation file arrives."""
        self._last_modified = dt_util.utcnow()

    async def async_added_to_hass(self):
        """Register notification callback and load base map background."""
        self._ns.set_callback(
            "10-minute-in-situ-meteorological-observations",
            self._attr_unique_id,
            self._set_latest,
        )
        await self.async_load_background()


class HybridWeatherCam(KNMICamera):
    """A camera component producing hybrid precipitation radar and wind particle animations."""

    def __init__(self, config_entry: NLWeatherConfigEntry) -> None:
        """Initialize hybrid weather camera."""
        super().__init__(config_entry)

        self._attr_unique_id = f"{config_entry.entry_id}_hybrid_weather"
        self._attr_device_info = DeviceInfo(
            name="Hybride kaart",
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, f"{config_entry.entry_id}_hybrid_weather")},
            manufacturer="KNMI.nl",
            configuration_url="https://www.knmi.nl",
        )
        self._attr_translation_key = "hybrid_weather"

        self._app = config_entry.runtime_data.app
        self._wms = config_entry.runtime_data.wms
        self._edr = config_entry.runtime_data.edr
        self._ns = config_entry.runtime_data.notification_service

    def __needs_refresh(self) -> bool:
        if self._last_image is None or self._last_image_dt is None:
            return True

        if self._last_modified and self._last_modified > self._last_image_dt:
            return True

        return (dt_util.utcnow() - self._last_image_dt) >= timedelta(minutes=10)

    async def _retrieve_hybrid_image(self) -> bool:
        """Retrieve latest radar frame and wind observations, compositing into animated GIF."""
        await self.async_ensure_background()

        if self._background_image is None:
            _LOGGER.warning("No background image loaded for hybrid camera")
            return False

        ref_time = await self._latest_radar_datetime()
        if ref_time is None:
            ref_time = dt_util.utcnow()

        radar_img = None
        try:
            radar_buf = await self._wms.radar_forecast_image(
                ref_time,
                ref_time,
                (600, 600),
                self._radar_bbox_param,
                self._radar_style.wms_style,
            )
            radar_img = Image.open(radar_buf, formats=["PNG"]).convert("RGBA")
        except (WMSException, aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.warning("Could not fetch radar image for hybrid camera: %s", e)

        observations = []
        try:
            coverages = await self._edr.get_wind_observations()
            observations = parse_edr_wind_coverages(coverages)
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ServerError,
            NotFoundError,
            TokenInvalid,
            InvalidRequest,
            KeyError,
        ) as e:
            _LOGGER.warning(
                "Could not fetch wind observations for hybrid camera: %s", e
            )

        # Mix in hyper-local target wind observations from the KNMI App API
        observations.extend(self._get_target_wind_observations())

        if not observations and radar_img is None:
            if self._last_image:
                return True
            return self._error_image("No radar or wind observations available")

        # Resize base map to 600x600 for performance and composite radar layer
        base_map = self._background_image.resize(
            (600, 600), Image.Resampling.LANCZOS
        ).convert("RGBA")
        if radar_img:
            if radar_img.size != base_map.size:
                radar_img = radar_img.resize(base_map.size)
            base_composite = Image.alpha_composite(base_map, radar_img)
            radar_img.close()
        else:
            base_composite = base_map

        now = dt_util.as_local(ref_time)
        header_color = self._radar_style.time_past_color

        wind_speed_img, legend_steps, _ = await self._retrieve_wind_speed_raster()

        if observations:
            grid = WindVectorGrid(
                observations,
                self._radar_bbox,
                grid_w=40,
                grid_h=40,
            )
            if wind_speed_img:
                grid.apply_speed_raster(wind_speed_img, legend_steps=legend_steps)
            engine = WindParticleEngine(
                grid,
                canvas_size=(600, 600),
                n_particles=750,
                n_frames=30,
                frame_duration_ms=70,
                vel_scale=0.85,
            )
            self._last_image = await self.hass.async_add_executor_job(
                engine.render_animation,
                base_composite,
                now,
                header_color,
            )
        else:
            with io.BytesIO() as out:
                draw_comp = ImageDraw.Draw(base_composite)
                draw_comp.text(
                    (16, 16),
                    now.strftime("%a %H:%M"),
                    fill=header_color,
                    font_size=26,
                    stroke_width=0.8,
                )
                base_composite.save(out, format="GIF")
                self._last_image = out.getvalue()

        self._last_image_dt = dt_util.utcnow()
        return True

    def _error_image(self, message: str) -> bool:
        with io.BytesIO() as output:
            img = (
                self._background_image.copy()
                if self._background_image
                else Image.new("RGBA", (600, 600), (30, 30, 30, 255))
            )
            draw = ImageDraw.Draw(img)
            draw.text(
                (24, 24),
                message,
                fill="red",
                font_size=28,
                stroke_width=1,
            )
            img.save(output, format="GIF")
            self._last_image = output.getvalue()

        return True

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of animated hybrid radar + wind particle GIF."""
        if not self.__needs_refresh():
            return self._last_image

        async with self._condition:
            while self._loading:
                _LOGGER.debug(
                    "Hybrid camera already loading - waiting for notification"
                )
                await self._condition.wait()

            if not self.__needs_refresh():
                return self._last_image

            self._loading = True

        try:
            await self._retrieve_hybrid_image()
            return self._last_image
        finally:
            async with self._condition:
                self._loading = False
                self._condition.notify_all()

    async def _set_latest(self, event):
        """Notification callback when new data arrives."""
        self._last_modified = dt_util.utcnow()

    async def async_added_to_hass(self):
        """Register callbacks and load base map background."""
        self._ns.set_callback(
            "radar_forecast", f"{self._attr_unique_id}_radar", self._set_latest
        )
        self._ns.set_callback(
            "10-minute-in-situ-meteorological-observations",
            f"{self._attr_unique_id}_wind",
            self._set_latest,
        )
        await self.async_load_background()
