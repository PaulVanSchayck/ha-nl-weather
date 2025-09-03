import asyncio
import io
import json
import logging

import aiohttp

BASE_URL = f"https://api.dataplatform.knmi.nl/wms/adaguc-server"
BASE_PARAMS = {
    'SERVICE': "WMS",
    'REQUEST': "GetMap",
    'VERSION': "1.3.0",
    'FORMAT': 'image/png',
    'TRANSPARENT': 'TRUE',
    'CRS': 'EPSG:4326',
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
            async with self._session.get(f"{BASE_URL}", headers=headers, params=params) as resp:
                _LOGGER.debug(f"Called WMS endpoint (status: {resp.status}): {resp.url}")
                buffer = io.BytesIO(await resp.read())
                try:
                    resp.raise_for_status()
                except aiohttp.ClientResponseError as e:
                    if e.status == 400:
                        raise InvalidRequest(json.load(buffer)) from None
                    if e.status == 404:
                        raise NotFoundError("No data found for query") from None
                    elif e.status == 403:
                        # TODO: Also handle quota exceeded
                        raise TokenInvalid(json.load(buffer)) from None
                    elif e.status >= 500:
                        raise ServerError(f"Status code: {e.status}") from None
                    raise
                    # TODO: Handle 429 errors

        return buffer

    async def radar_real_time_image(self, time, size, bbox):
        params = BASE_PARAMS.copy()
        params['TIME'] = time.isoformat()
        params['DATASET'] = "nl_rdr_data_rtcor_5m"
        params['LAYERS'] = "precipitation_real_time"
        params['STYLES'] = "rainrate-blue-to-purple/nearest"
        params['WIDTH'] = size[0]
        params['HEIGHT'] = size[1]
        params['BBOX'] = bbox
        return await self.get(params)

    async def radar_forecast_image(self, ref_time, time, size, bbox):
        params = BASE_PARAMS.copy()
        params['DIM_REFERENCE_TIME'] = ref_time.isoformat()
        params['TIME'] = time.isoformat()
        params['DATASET'] = "radar_forecast_2.0"
        params['LAYERS'] = "precipitation_nowcast"
        params['STYLES'] = "rainrate-blue-to-purple/nearest"
        params['WIDTH'] = size[0]
        params['HEIGHT'] = size[1]
        params['BBOX'] = bbox
        return await self.get(params)

class NotFoundError(Exception):
    """Exception class for no result found"""

class TokenInvalid(Exception):
    """Exception class when token is not accepted"""

class ServerError(Exception):
    """Exception class for server error"""

class InvalidRequest(Exception):
    """Exception class for invalid request"""