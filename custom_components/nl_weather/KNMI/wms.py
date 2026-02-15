import aiohttp
import asyncio
import io
import logging
import xml.etree.ElementTree as ET

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

    async def get_capabilities_radar(self) -> ET.ElementTree:
        params = {}
        params["SERVICE"] = "WMS"
        params["DATASET"] = "nl_rdr_data_rtcor_5m"
        params["REQUEST"] = "GetCapabilities"
        buf = await self.get(params)
        return ET.parse(buf)

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
