"""Tests for WMS API client error handling and response processing."""

from base64 import b64encode
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.nl_weather.config_flow import validate_wms_input
from custom_components.nl_weather.KNMI.wms import (
    WMS,
    InvalidRequest,
    NotFoundError,
    RateLimitExceeded,
    ServerError,
    TokenInvalid,
)


def _mock_session_with_response(status: int, body: bytes, headers: dict | None = None):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read = AsyncMock(return_value=body)
    mock_resp.json = AsyncMock(return_value={"error": "details"})
    mock_resp.headers = headers or {}
    mock_resp.url = "https://api.dataplatform.knmi.nl/wms/adaguc-server"

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_cm)
    return mock_session


@pytest.mark.asyncio
async def test_wms_get_adaguc_server_error() -> None:
    """Test that WMS.get raises InvalidRequest with complete text when response contains ADAGUC Server error."""
    error_body = b"ADAGUC Server: Invalid layer name\nDetails on line 2"
    session = _mock_session_with_response(200, error_body)
    wms = WMS(session, "dummy_token")

    with pytest.raises(InvalidRequest) as exc_info:
        await wms.get({})

    assert str(exc_info.value) == "ADAGUC Server: Invalid layer name\nDetails on line 2"


@pytest.mark.asyncio
async def test_wms_get_valid_binary_response() -> None:
    """Test that WMS.get returns a seeked BytesIO buffer for valid binary image responses."""
    png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    session = _mock_session_with_response(200, png_data)
    wms = WMS(session, "dummy_token")

    buf = await wms.get({})
    assert buf.tell() == 0
    assert buf.read() == png_data


@pytest.mark.asyncio
async def test_wms_get_png_with_marker_in_later_line() -> None:
    """Test that PNG images containing 'ADAGUC Server:' in subsequent binary data are not misidentified as errors."""
    png_data_with_later_marker = (
        b"\x89PNG\r\n\x1a\nChunk Header\nADAGUC Server: Embedded Metadata"
    )
    session = _mock_session_with_response(200, png_data_with_later_marker)
    wms = WMS(session, "dummy_token")

    buf = await wms.get({})
    assert buf.tell() == 0
    assert buf.read() == png_data_with_later_marker


@pytest.mark.asyncio
async def test_wms_get_http_status_exceptions() -> None:
    """Test HTTP status code exception mapping in WMS.get."""
    session_400 = _mock_session_with_response(400, b'{"error": "bad request"}')
    wms_400 = WMS(session_400, "token")
    with pytest.raises(InvalidRequest):
        await wms_400.get({})

    session_404 = _mock_session_with_response(404, b"not found")
    wms_404 = WMS(session_404, "token")
    with pytest.raises(NotFoundError):
        await wms_404.get({})

    session_403 = _mock_session_with_response(403, b'{"error": "forbidden"}')
    wms_403 = WMS(session_403, "token")
    with pytest.raises(TokenInvalid):
        await wms_403.get({})

    session_429 = _mock_session_with_response(429, b"rate limit")
    wms_429 = WMS(session_429, "token")
    with pytest.raises(RateLimitExceeded):
        await wms_429.get({})

    session_500 = _mock_session_with_response(500, b"server error")
    wms_500 = WMS(session_500, "token")
    with pytest.raises(ServerError):
        await wms_500.get({})


@pytest.mark.asyncio
async def test_validate_wms_input_handles_invalid_request() -> None:
    """Test that validate_wms_input handles InvalidRequest from empty WMS probe call gracefully."""
    valid_token = b64encode(b'{"key": "value"}').decode()
    data = {"wms_token": valid_token}
    mock_hass = MagicMock()

    with (
        patch("custom_components.nl_weather.config_flow.async_get_clientsession"),
        patch("custom_components.nl_weather.config_flow.WMS") as mock_wms_cls,
    ):
        mock_wms_instance = MagicMock()
        mock_wms_instance.get = AsyncMock(
            side_effect=InvalidRequest("ADAGUC Server: Invalid parameters")
        )
        mock_wms_cls.return_value = mock_wms_instance

        # Should complete without raising an exception
        await validate_wms_input(mock_hass, data)
