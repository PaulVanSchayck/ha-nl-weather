"""Tests for EDR API client error handling and response processing."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.nl_weather.KNMI.edr import (
    EDR,
    InvalidRequest,
    NotFoundError,
    QuotaExceeded,
    ServerError,
    TokenInvalid,
)


def _mock_session_with_response(status: int, text_body: str):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.text = AsyncMock(return_value=text_body)
    if status >= 400:
        mock_resp.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=status,
            message=f"HTTP {status}",
        )
    else:
        mock_resp.raise_for_status.return_value = None

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_cm)
    return mock_session


def test_quota_exceeded_inheritance() -> None:
    """Test that QuotaExceeded is independent of TokenInvalid."""
    assert not issubclass(QuotaExceeded, TokenInvalid)
    assert issubclass(QuotaExceeded, Exception)


@pytest.mark.asyncio
async def test_edr_get_http_status_exceptions() -> None:
    """Test HTTP status code exception mapping in EDR.get."""
    session_400 = _mock_session_with_response(400, '{"error": "bad request"}')
    edr_400 = EDR(session_400, "token")
    with pytest.raises(InvalidRequest):
        await edr_400.get("")

    session_404 = _mock_session_with_response(404, '{"error": "not found"}')
    edr_404 = EDR(session_404, "token")
    with pytest.raises(NotFoundError):
        await edr_404.get("")

    session_403_token = _mock_session_with_response(403, '{"message": "Forbidden"}')
    edr_403_token = EDR(session_403_token, "token")
    with pytest.raises(TokenInvalid) as exc_info:
        await edr_403_token.get("")
    assert type(exc_info.value) is TokenInvalid

    session_403_quota = _mock_session_with_response(
        403, '{"message": "Quota Exceeded"}'
    )
    edr_403_quota = EDR(session_403_quota, "token")
    with pytest.raises(QuotaExceeded):
        await edr_403_quota.get("")

    # Payload with generic message but quota code should raise QuotaExceeded
    session_403_code_quota = _mock_session_with_response(
        403, '{"message": "Forbidden", "code": "QuotaExceeded"}'
    )
    edr_403_code_quota = EDR(session_403_code_quota, "token")
    with pytest.raises(QuotaExceeded):
        await edr_403_code_quota.get("")

    session_500 = _mock_session_with_response(500, "server error")
    edr_500 = EDR(session_500, "token")
    with pytest.raises(ServerError):
        await edr_500.get("")
