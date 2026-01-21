import asyncio
import io
import logging
import math

import aiohttp

BASE_URL = "https://api.dataplatform.knmi.nl/wms/adaguc-server"
BASE_PARAMS = {
    "SERVICE": "WMS",
    "REQUEST": "GetMap",
    "VERSION": "1.3.0",
    "FORMAT": "image/png",
    "TRANSPARENT": "TRUE",
    "CRS": "EPSG:3857",
}

_LOGGER = logging.getLogger(__name__)

R = 6378137.0  # EPSG:3857 radius


def epsg4325_to_epsg3857(lon, lat):
    """Convert lon/lat (deg) to EPSG:3857 meters (x, y)."""
    # clamp latitude to valid Web Mercator range to avoid math domain errors
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = R * math.radians(lon)
    y = R * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


class WMS:
    _session: aiohttp.ClientSession

    def __init__(self, aiohttp_session, token):
        self._session = aiohttp_session
        self._token = token
        # This limits the amount of simultaneous requests
        self._semaphore = asyncio.Semaphore(5)

    async def get(self, params):
        headers = {"Authorization": self._token}
        async with self._semaphore:
            async with self._session.get(
                f"{BASE_URL}", headers=headers, params=params
            ) as resp:
                _LOGGER.debug(
                    f"Called WMS endpoint (status: {resp.status}): {resp.url}"
                )
                if resp.status == 400:
                    raise InvalidRequest(await resp.json()) from None
                if resp.status == 404:
                    raise NotFoundError("No data found for query") from None
                elif resp.status == 403:
                    # TODO: Also handle quota exceeded
                    raise TokenInvalid(await resp.json()) from None
                elif resp.status == 429:
                    raise RateLimitExceeded() from None
                elif resp.status >= 500:
                    raise ServerError(f"Status code: {resp.status}") from None

                buffer = io.BytesIO(await resp.read())

                # TODO: Not sure this check works
                if b"ADAGUC Server:" in buffer.readline():
                    raise InvalidRequest(buffer.read().decode("UTF-8")) from None
                buffer.seek(0)

                return buffer

    async def radar_real_time_image(self, time, size, bbox, style):
        params = BASE_PARAMS.copy()
        params["TIME"] = time.isoformat()
        params["DATASET"] = "nl_rdr_data_rtcor_5m"
        params["LAYERS"] = "precipitation_real_time"
        params["STYLES"] = style
        params["WIDTH"] = size[0]
        params["HEIGHT"] = size[1]
        params["BBOX"] = bbox
        return await self.get(params)

    async def radar_forecast_image(self, ref_time, time, size, bbox, style):
        params = BASE_PARAMS.copy()
        params["DIM_REFERENCE_TIME"] = ref_time.isoformat()
        params["TIME"] = time.isoformat()
        params["DATASET"] = "radar_forecast_2.0"
        params["LAYERS"] = "precipitation_nowcast"
        params["STYLES"] = style
        params["WIDTH"] = size[0]
        params["HEIGHT"] = size[1]
        params["BBOX"] = bbox
        return await self.get(params)


class NotFoundError(Exception):
    """Exception class for no result found"""


class TokenInvalid(Exception):
    """Exception class when token is not accepted"""


class ServerError(Exception):
    """Exception class for server error"""


class InvalidRequest(Exception):
    """Exception class for invalid request"""


class RateLimitExceeded(Exception):
    """Exception class for rate limit exceeded"""
