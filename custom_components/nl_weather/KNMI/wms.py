import aiohttp
import asyncio
import io
import logging
import xml.etree.ElementTree as ET

from .helpers import format_dt

BASE_URL = "https://api.dataplatform.knmi.nl/wms/adaguc-server"
BASE_PARAMS = {
    "SERVICE": "WMS",
    "REQUEST": "GetMap",
    "VERSION": "1.3.0",
    "FORMAT": "image/png",
    "TRANSPARENT": "TRUE",
    "CRS": "EPSG:3857",
}
# This is lower than the reported 20, but staying on the safe side
RATE_LIMIT_PER_SECOND = 15

_LOGGER = logging.getLogger(__name__)


class WMS:
    _session: aiohttp.ClientSession

    def __init__(self, aiohttp_session, token):
        self._session = aiohttp_session
        self._token = token
        # This limits the amount of simultaneous requests
        self._semaphore = asyncio.Semaphore(1)
        self.lock = asyncio.Lock()
        self.last_call = 0

    async def wait_for_rate(self):
        async with self.lock:
            now = asyncio.get_event_loop().time()
            wait = 1 / RATE_LIMIT_PER_SECOND - (now - self.last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self.last_call = asyncio.get_event_loop().time()

    async def get(self, params):
        headers = {"Authorization": self._token}
        await self.wait_for_rate()
        async with self._semaphore:
            async with self._session.get(
                f"{BASE_URL}", headers=headers, params=params
            ) as resp:
                cache = resp.headers.get("adaguc-cache", "unknown")
                age = resp.headers.get("age", "unknown")
                _LOGGER.debug(
                    f"Called WMS endpoint (status: {resp.status}, cache: {cache}, age: {age}): {resp.url}"
                )
                if resp.status == 400:
                    raise InvalidRequest(await resp.json()) from None
                if resp.status == 404:
                    raise NotFoundError("No data found for query") from None
                elif resp.status == 403:
                    # TODO: Also handle quota exceeded
                    raise TokenInvalid(await resp.json()) from None
                elif resp.status == 429:
                    raise RateLimitExceeded("Rate limit exceeded") from None
                elif resp.status >= 500:
                    raise ServerError(f"Status code: {resp.status}") from None

                buffer = io.BytesIO(await resp.read())

                # TODO: Not sure this check works
                if b"ADAGUC Server:" in buffer.readline():
                    raise InvalidRequest(buffer.read().decode("UTF-8")) from None
                buffer.seek(0)

                return buffer

    async def get_capabilities_radar(self) -> ET.ElementTree:
        params = {}
        params["SERVICE"] = "WMS"
        params["DATASET"] = "nl_rdr_data_rtcor_5m"
        params["REQUEST"] = "GetCapabilities"
        buf = await self.get(params)
        return ET.parse(buf)

    async def radar_real_time_image(self, time, size, bbox, style):
        params = BASE_PARAMS.copy()
        # The zulu "Z" format (instead of +00:00) is needed to enable long-term caching.
        # https://github.com/KNMI/adaguc-server/issues/719
        params["TIME"] = format_dt(time)
        params["DATASET"] = "nl_rdr_data_rtcor_5m"
        params["LAYERS"] = "precipitation_real_time"
        params["STYLES"] = style
        params["WIDTH"] = size[0]
        params["HEIGHT"] = size[1]
        params["BBOX"] = bbox
        return await self.get(params)

    async def radar_forecast_image(self, ref_time, time, size, bbox, style):
        params = BASE_PARAMS.copy()
        # The zulu "Z" format (instead of +00:00) is needed to enable long-term caching.
        # https://github.com/KNMI/adaguc-server/issues/719
        params["DIM_REFERENCE_TIME"] = format_dt(ref_time)
        params["TIME"] = format_dt(time)
        params["DATASET"] = "radar_forecast_2.0"
        params["LAYERS"] = "precipitation_nowcast"
        params["STYLES"] = style
        params["WIDTH"] = size[0]
        params["HEIGHT"] = size[1]
        params["BBOX"] = bbox
        return await self.get(params)


class WMSException(Exception):
    """Base WMS Exception"""


class NotFoundError(WMSException):
    """Exception class for no result found"""


class TokenInvalid(WMSException):
    """Exception class when token is not accepted"""


class ServerError(WMSException):
    """Exception class for server error"""


class InvalidRequest(WMSException):
    """Exception class for invalid request"""


class RateLimitExceeded(WMSException):
    """Exception class for rate limit exceeded"""
