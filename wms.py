import io
import json
import logging

import aiohttp
from PIL import Image

BASE_URL = f"https://api.dataplatform.knmi.nl/wms/adaguc-server"
PARAMS = {
    'DATASET': "radar_forecast_2.0",
    'SERVICE': "WMS",
    'REQUEST': "GetMap",
    'VERSION': "1.3.0",
    'FORMAT': 'image/png',
    'STYLES': 'rainrate-blue-to-purple/nearest',
    'TRANSPARENT': 'TRUE',
    'LAYERS': 'precipitation_nowcast',
    'WIDTH': 1205, # TODO: This should not be hardcoded here
    'HEIGHT': 1205,
    'CRS': 'EPSG:4326',
    'BBOX': '49.2,0.0,55.0,9.46' # TODO: This should not be hardcoded here

}

_LOGGER = logging.getLogger(__name__)

class WMS:
    _session: aiohttp.ClientSession

    def __init__(self, aiohttp_session, token):
        self._session = aiohttp_session
        self._token = token

    async def get(self, ref_time, time):
        PARAMS['DIM_REFERENCE_TIME'] = ref_time.isoformat()
        PARAMS['TIME'] = time.isoformat()
        headers = {"Authorization": self._token}
        _LOGGER.debug(f"Calling WMS endpoint  with {PARAMS}")
        async with self._session.get(f"{BASE_URL}", headers=headers, params=PARAMS) as resp:
            _LOGGER.debug(resp.url)
            buffer = io.BytesIO(await resp.read())
            _LOGGER.debug(f"Response from WMS endpoint: {resp.status}")
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

        return buffer

class NotFoundError(Exception):
    """Exception class for no result found"""

class TokenInvalid(Exception):
    """Exception class when token is not accepted"""

class ServerError(Exception):
    """Exception class for server error"""

class InvalidRequest(Exception):
    """Exception class for invalid request"""