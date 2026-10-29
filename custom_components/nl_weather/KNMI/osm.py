"""OpenStreetMap tile management, zone calculation, and map assembly."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import math
import os

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from PIL import Image, ImageEnhance, ImageOps

from ..const import (
    DEFAULT_ZOOM_MARGIN,
    MINIMALIST_DARK_TILE_URL,
    MINIMALIST_LIGHT_TILE_URL,
    STANDARD_OSM_TILE_URL,
    OSMMapStyle,
)
from .helpers import (
    EARTH_RADIUS_METERS,
    Coordinate,
    epsg4325_to_epsg3857,
)

_LOGGER = logging.getLogger(__name__)

# Circumference of Earth in Web Mercator meters
WORLD_CIRCUMFERENCE: float = 2.0 * math.pi * EARTH_RADIUS_METERS
TILE_SIZE: int = 256
USER_AGENT: str = "HomeAssistant-ha-nl-weather/0.13.0 (+https://github.com/PaulVanSchayck/ha-nl-weather)"


def get_known_zones(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> list[tuple[float, float, float]]:
    """Return a list of (latitude, longitude, weight/radius) for all known zones and subentries."""
    zones: list[tuple[float, float, float]] = []

    # 1. Collect Home Assistant zone entities
    for state in hass.states.async_all("zone"):
        lat = state.attributes.get("latitude")
        lon = state.attributes.get("longitude")
        radius = state.attributes.get("radius", 100.0)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            zones.append((float(lat), float(lon), max(float(radius), 100.0)))

    # 2. Collect integration subentry locations
    for subentry in config_entry.subentries.values():
        lat = subentry.data.get(CONF_LATITUDE)
        lon = subentry.data.get(CONF_LONGITUDE)
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            zones.append((float(lat), float(lon), 100.0))

    # 3. Fallback to Home Assistant core coordinates or geographical center of the Netherlands
    if not zones:
        if isinstance(hass.config.latitude, (int, float)) and isinstance(
            hass.config.longitude, (int, float)
        ):
            zones.append(
                (float(hass.config.latitude), float(hass.config.longitude), 100.0)
            )
        else:
            # Onze Lieve Vrouwetoren, Amersfoort (Dutch national grid center)
            zones.append((52.15517, 5.38721, 100.0))

    return zones


def calculate_weighted_center(
    zones: list[tuple[float, float, float]],
) -> Coordinate:
    """Calculate the radius-weighted center (centroid) of the given zones."""
    total_weight = sum(w for _, _, w in zones)
    if total_weight <= 0:
        return Coordinate(lat=zones[0][0], lon=zones[0][1])

    center_lat = sum(lat * w for lat, _, w in zones) / total_weight
    center_lon = sum(lon * w for _, lon, w in zones) / total_weight
    return Coordinate(lat=center_lat, lon=center_lon)


def calculate_auto_zoom_and_bbox(
    zones: list[tuple[float, float, float]],
    center: Coordinate,
    image_size: tuple[int, int] = (1024, 1024),
    padding: float = DEFAULT_ZOOM_MARGIN,
    min_span_meters: float = 25000.0,
) -> tuple[int, tuple[float, float, float, float]]:
    """Calculate the optimal integer zoom level and EPSG:3857 BBOX to encompass all zones with margin."""
    cx, cy = epsg4325_to_epsg3857(center)

    max_dx = 0.0
    max_dy = 0.0

    for lat, lon, radius in zones:
        x, y = epsg4325_to_epsg3857(Coordinate(lat=lat, lon=lon))
        dx = abs(x - cx) + radius
        dy = abs(y - cy) + radius
        max_dx = max(max_dx, dx)
        max_dy = max(max_dy, dy)

    half_span_x = max(max_dx * (1.0 + padding), min_span_meters)
    half_span_y = max(max_dy * (1.0 + padding), min_span_meters)
    span_x = 2.0 * half_span_x
    span_y = 2.0 * half_span_y

    width, height = image_size
    res_needed = max(span_x / width, span_y / height)

    z = math.floor(math.log2(WORLD_CIRCUMFERENCE / (TILE_SIZE * res_needed)))
    # Clamp between 6 (Benelux-wide) and 14 (neighborhood)
    z = max(6, min(14, z))

    res = WORLD_CIRCUMFERENCE / (TILE_SIZE * (2**z))
    actual_span_x = width * res
    actual_span_y = height * res

    xmin = cx - actual_span_x / 2.0
    xmax = cx + actual_span_x / 2.0
    ymin = cy - actual_span_y / 2.0
    ymax = cy + actual_span_y / 2.0

    return z, (xmin, ymin, xmax, ymax)


def calculate_bbox_for_zoom(
    center: Coordinate,
    zoom: int,
    image_size: tuple[int, int] = (1024, 1024),
) -> tuple[float, float, float, float]:
    """Calculate the EPSG:3857 BBOX for a fixed center and zoom level."""
    cx, cy = epsg4325_to_epsg3857(center)
    width, height = image_size

    res = WORLD_CIRCUMFERENCE / (TILE_SIZE * (2**zoom))
    actual_span_x = width * res
    actual_span_y = height * res

    xmin = cx - actual_span_x / 2.0
    xmax = cx + actual_span_x / 2.0
    ymin = cy - actual_span_y / 2.0
    ymax = cy + actual_span_y / 2.0

    return xmin, ymin, xmax, ymax


def tile_coordinates(x: float, y: float, zoom: int) -> tuple[int, int]:
    """Return tile (tx, ty) containing EPSG:3857 meters (x, y) at zoom."""
    tile_meters = WORLD_CIRCUMFERENCE / (2**zoom)
    max_idx = (2**zoom) - 1
    tx = math.floor((x + WORLD_CIRCUMFERENCE / 2.0) / tile_meters)
    ty = math.floor((WORLD_CIRCUMFERENCE / 2.0 - y) / tile_meters)
    return max(0, min(max_idx, tx)), max(0, min(max_idx, ty))


def tile_bounds_3857(tx: int, ty: int, zoom: int) -> tuple[float, float, float, float]:
    """Return EPSG:3857 (xmin, ymin, xmax, ymax) bounds for tile (tx, ty) at zoom."""
    tile_meters = WORLD_CIRCUMFERENCE / (2**zoom)
    xmin = tx * tile_meters - WORLD_CIRCUMFERENCE / 2.0
    xmax = (tx + 1) * tile_meters - WORLD_CIRCUMFERENCE / 2.0
    ymax = WORLD_CIRCUMFERENCE / 2.0 - ty * tile_meters
    ymin = WORLD_CIRCUMFERENCE / 2.0 - (ty + 1) * tile_meters
    return xmin, ymin, xmax, ymax


def transform_standard_osm_tile(tile: Image.Image, dark: bool) -> Image.Image:
    """Transform standard OSM tile into a simplified radar basemap."""
    if dark:
        inverted = ImageOps.invert(tile.convert("RGB"))
        sat = ImageEnhance.Color(inverted).enhance(0.15)
        contrast = ImageEnhance.Contrast(sat).enhance(0.85)
        return ImageEnhance.Brightness(contrast).enhance(0.40)

    # Simplified light mode
    sat = ImageEnhance.Color(tile.convert("RGB")).enhance(0.20)
    bright = ImageEnhance.Brightness(sat).enhance(1.08)
    return ImageEnhance.Contrast(bright).enhance(0.70)


def _read_file_sync(path: str) -> bytes | None:
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def _write_file_sync(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


class OSMTileManager:
    """Manages downloading, caching, and stitching OSM tiles into a final background image."""

    def __init__(self, session: aiohttp.ClientSession, cache_dir: str) -> None:
        self._session = session
        self._cache_dir = cache_dir
        self._tiles_dir = os.path.join(cache_dir, "tiles")
        self._semaphore = asyncio.Semaphore(4)
        os.makedirs(self._tiles_dir, exist_ok=True)

    def _get_background_cache_path(
        self,
        bbox: tuple[float, float, float, float],
        size: tuple[int, int],
        zoom: int,
        style: str,
        dark: bool,
    ) -> str:
        key_str = f"{style}_{dark}_{zoom}_{bbox[0]:.1f}_{bbox[1]:.1f}_{bbox[2]:.1f}_{bbox[3]:.1f}_{size[0]}_{size[1]}"
        hash_digest = hashlib.sha256(key_str.encode()).hexdigest()[:16]
        return os.path.join(self._cache_dir, f"bg_{hash_digest}.png")

    def _get_tile_cache_path(self, style: str, zoom: int, tx: int, ty: int) -> str:
        tile_dir = os.path.join(self._tiles_dir, style, str(zoom), str(tx))
        os.makedirs(tile_dir, exist_ok=True)
        return os.path.join(tile_dir, f"{ty}.png")

    async def _fetch_tile(self, url: str, tile_cache_path: str) -> bytes | None:
        cached_data = await asyncio.to_thread(_read_file_sync, tile_cache_path)
        if cached_data is not None:
            return cached_data

        async with self._semaphore:
            headers = {"User-Agent": USER_AGENT}
            try:
                async with self._session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await asyncio.to_thread(_write_file_sync, tile_cache_path, data)
                        return data
                    _LOGGER.warning(
                        "Failed to fetch tile %s (HTTP %s)", url, resp.status
                    )
            except (aiohttp.ClientError, TimeoutError, OSError) as err:
                _LOGGER.warning("Error fetching tile %s: %s", url, err)
        return None

    def _stitch_and_crop(
        self,
        tiles_data: dict[tuple[int, int], bytes],
        txmin: int,
        txmax: int,
        tymin: int,
        tymax: int,
        bbox: tuple[float, float, float, float],
        size: tuple[int, int],
        zoom: int,
        style: str,
        dark: bool,
    ) -> Image.Image:
        cols = txmax - txmin + 1
        rows = tymax - tymin + 1
        canvas = Image.new("RGB", (cols * TILE_SIZE, rows * TILE_SIZE), (240, 240, 240))

        for (tx, ty), data in tiles_data.items():
            if not data:
                continue
            tile_img = Image.open(io.BytesIO(data))
            if style == OSMMapStyle.STANDARD:
                tile_img = transform_standard_osm_tile(tile_img, dark)
            paste_x = (tx - txmin) * TILE_SIZE
            paste_y = (ty - tymin) * TILE_SIZE
            canvas.paste(tile_img, (paste_x, paste_y))

        xmin, _ymin, _xmax, ymax = bbox
        px_min = (xmin + WORLD_CIRCUMFERENCE / 2.0) / WORLD_CIRCUMFERENCE * (
            TILE_SIZE * (2**zoom)
        ) - txmin * TILE_SIZE
        py_top = (WORLD_CIRCUMFERENCE / 2.0 - ymax) / WORLD_CIRCUMFERENCE * (
            TILE_SIZE * (2**zoom)
        ) - tymin * TILE_SIZE

        crop_box = (
            px_min,
            py_top,
            px_min + size[0],
            py_top + size[1],
        )

        cropped = (
            canvas.crop(crop_box).resize(size, Image.Resampling.LANCZOS).convert("RGBA")
        )
        return cropped

    async def async_get_osm_background(
        self,
        hass: HomeAssistant,
        bbox: tuple[float, float, float, float],
        size: tuple[int, int],
        zoom: int,
        style: OSMMapStyle,
        dark: bool,
    ) -> Image.Image:
        """Fetch, stitch, and cache the background map image for the given BBOX."""
        bg_cache_path = self._get_background_cache_path(
            bbox, size, zoom, style.value, dark
        )

        cached_bg = await asyncio.to_thread(os.path.exists, bg_cache_path)
        if cached_bg:
            return await hass.async_add_executor_job(
                lambda: Image.open(bg_cache_path).convert("RGBA")
            )

        xmin, ymin, xmax, ymax = bbox
        txmin, tymax = tile_coordinates(xmin, ymin, zoom)
        txmax, tymin = tile_coordinates(xmax, ymax, zoom)

        if style == OSMMapStyle.MINIMALIST:
            url_template = (
                MINIMALIST_DARK_TILE_URL if dark else MINIMALIST_LIGHT_TILE_URL
            )
            cache_style_key = "minimalist_dark" if dark else "minimalist_light"
        else:
            url_template = STANDARD_OSM_TILE_URL
            cache_style_key = "standard"

        tasks: list[asyncio.Task[tuple[tuple[int, int], bytes | None]]] = []

        async def fetch_indexed(tx: int, ty: int):
            url = url_template.format(z=zoom, x=tx, y=ty)
            path = self._get_tile_cache_path(cache_style_key, zoom, tx, ty)
            data = await self._fetch_tile(url, path)
            return (tx, ty), data

        for tx in range(txmin, txmax + 1):
            for ty in range(tymin, tymax + 1):
                tasks.append(asyncio.create_task(fetch_indexed(tx, ty)))

        results = await asyncio.gather(*tasks)
        tiles_dict = dict(results)

        def generate_and_save():
            img = self._stitch_and_crop(
                tiles_dict,
                txmin,
                txmax,
                tymin,
                tymax,
                bbox,
                size,
                zoom,
                style,
                dark,
            )
            img.save(bg_cache_path, format="PNG")
            return img

        return await hass.async_add_executor_job(generate_and_save)
