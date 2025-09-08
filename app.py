import json
import aiohttp
import logging

BASE_URL = f"https://api.app.knmi.cloud"

_LOGGER = logging.getLogger(__name__)

class App:
    _session: aiohttp.ClientSession

    def __init__(self, aiohttp_session):
        self._session = aiohttp_session

    async def get(self, endpoint: str, params=None):
        _LOGGER.debug(f"Calling KNMI App API endpoint {endpoint} with {params}")
        async with self._session.get(f"{BASE_URL}/{endpoint}", params=params) as resp:
            body = await resp.text()
            try:
                resp.raise_for_status()
            except aiohttp.ClientResponseError as e:
                if e.status == 400:
                    raise InvalidRequest(json.loads(body)) from None
                if e.status == 404:
                    raise NotFoundError("No data found for query") from None
                elif e.status >= 500:
                    raise ServerError(f"Status code: {e.status}: {body}") from None
                raise
            return json.loads(body)

    async def weather(self, location, region):
        params = {
            'location': location,
            'region': region
        }
        return await self.get('weather', params)


class NotFoundError(Exception):
    """Exception class for no result found"""

class TokenInvalid(Exception):
    """Exception class when token is not accepted"""

class ServerError(Exception):
    """Exception class for server error"""

class InvalidRequest(Exception):
    """Exception class for invalid request"""