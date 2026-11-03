import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp

BASE_URL = "https://api.app.knmi.cloud"
_LOGGER = logging.getLogger(__name__)

# TODO: Remove once the alerts/nationwide endpoint is live
MOCK_ALERTS = True
MOCK_ALERTS_FILE = Path(__file__).parent / "mock_alerts" / "w-three-levels.json"


def _mock_alerts() -> dict:
    """Load the mock snapshot with all time windows set to be active now."""
    snapshot = json.loads(MOCK_ALERTS_FILE.read_text())
    now = datetime.now(UTC)
    window = {
        "onset": (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires": (now + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    for warning in snapshot["warnings"]:
        warning.update(window)
        for part in warning["parts"]:
            part.update(window)
    return snapshot


class App:
    _session: aiohttp.ClientSession
    _area_definition: dict

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

    async def weather(self, cell_id, region):
        params = {"location": cell_id, "region": region}
        return await self.get("weather", params)

    async def weather_detail(self, cell_id, region, date):
        params = {"location": cell_id, "region": region, "date": date}
        return await self.get("weather/detail", params)

    async def alerts_nationwide(self):
        if MOCK_ALERTS:
            return await asyncio.to_thread(_mock_alerts)
        return await self.get("alerts/nationwide")

    async def precipitation_graph(self, radar_cell_id, date):
        params = {"location": radar_cell_id, "time": date}
        return await self.get("precipitation/graph", params)


class AppException(Exception):
    """Base App Exception"""


class NotFoundError(AppException):
    """Exception class for no result found"""


class TokenInvalid(AppException):
    """Exception class when token is not accepted"""


class ServerError(AppException):
    """Exception class for server error"""


class InvalidRequest(AppException):
    """Exception class for invalid request"""
