"""Tests for EDR API client error handling and response processing."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

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
@pytest.mark.parametrize(
    ("status", "expected_exception"),
    [
        (400, InvalidRequest),
        (404, NotFoundError),
        (500, ServerError),
        (503, ServerError),
        (401, aiohttp.ClientResponseError),
        (429, aiohttp.ClientResponseError),
    ],
)
async def test_edr_get_http_status_exceptions(
    status: int, expected_exception: type[Exception]
) -> None:
    """Quota text must not override classification of statuses other than 403."""
    session = _mock_session_with_response(status, '{"message": "Quota Exceeded"}')

    with pytest.raises(expected_exception) as exc_info:
        await EDR(session, "token").get("")

    assert type(exc_info.value) is expected_exception
    if expected_exception is aiohttp.ClientResponseError:
        assert exc_info.value.status == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"message": "Quota Exceeded"}, id="message"),
        pytest.param({"code": "QUOTA_EXCEEDED"}, id="code"),
        pytest.param({"error": "Daily QuOtA exceeded"}, id="error"),
        pytest.param(
            {"message": "Forbidden", "code": "QuotaExceeded"},
            id="generic-message-quota-code",
        ),
        pytest.param(
            {"message": "Forbidden", "code": "403", "error": "Quota exceeded"},
            id="generic-message-and-code-quota-error",
        ),
        pytest.param(
            {"message": None, "code": "", "error": "Quota exceeded"},
            id="null-and-empty-fields",
        ),
        pytest.param(
            {"message": 403, "code": False, "error": "Quota exceeded"},
            id="non-string-fields",
        ),
        pytest.param("QUOTA exceeded", id="json-string"),
    ],
)
async def test_edr_get_forbidden_quota_payload(payload: object) -> None:
    """Detect quota errors across response fields and preserve decoded details."""
    session = _mock_session_with_response(403, json.dumps(payload))

    with pytest.raises(QuotaExceeded) as exc_info:
        await EDR(session, "token").get("")

    assert exc_info.value.args == (payload,)
    session.get.return_value.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"message": "Forbidden"}, id="forbidden-message"),
        pytest.param(
            {"message": "Forbidden", "code": "InvalidToken", "error": "Expired"},
            id="all-fields-without-quota",
        ),
        pytest.param(
            {"message": None, "code": 403, "error": False}, id="non-string-fields"
        ),
        pytest.param(
            {"message": "Forbidden", "detail": "QUOTA exhausted"}, id="other-field"
        ),
        pytest.param(
            {"details": {"reason": "Quota exceeded"}}, id="nested-object-value"
        ),
        pytest.param({"details": ["Quota exceeded"]}, id="list-value"),
        pytest.param({"quota": "Forbidden"}, id="quota-only-in-key"),
        pytest.param({}, id="empty-object"),
        pytest.param("Forbidden", id="json-string"),
        pytest.param(None, id="json-null"),
        pytest.param(403, id="json-number"),
        pytest.param(False, id="json-boolean"),
        pytest.param([], id="empty-list"),
        pytest.param(["Forbidden"], id="json-list"),
    ],
)
async def test_edr_get_forbidden_without_quota(payload: object) -> None:
    """Non-quota JSON responses retain the token error and original payload."""
    session = _mock_session_with_response(403, json.dumps(payload))

    with pytest.raises(TokenInvalid) as exc_info:
        await EDR(session, "token").get("")

    assert type(exc_info.value) is TokenInvalid
    assert exc_info.value.args == (payload,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected_exception"),
    [
        pytest.param("Daily QUOTA exceeded", QuotaExceeded, id="plain-quota"),
        pytest.param(
            '{"message": "Quota exceeded"', QuotaExceeded, id="truncated-quota-json"
        ),
        pytest.param("<html>Quota exceeded</html>", QuotaExceeded, id="html-quota"),
        pytest.param("Forbidden", TokenInvalid, id="plain-forbidden"),
        pytest.param("<html>Forbidden</html>", TokenInvalid, id="html-forbidden"),
        pytest.param(
            '{"message": "Forbidden"', TokenInvalid, id="truncated-forbidden-json"
        ),
        pytest.param("", TokenInvalid, id="empty-body"),
        pytest.param(" \n\t", TokenInvalid, id="whitespace-body"),
    ],
)
async def test_edr_get_forbidden_non_json_body(
    body: str, expected_exception: type[Exception]
) -> None:
    """Malformed JSON is classified from raw text without losing error details."""
    session = _mock_session_with_response(403, body)

    with pytest.raises(expected_exception) as exc_info:
        await EDR(session, "token").get("")

    assert type(exc_info.value) is expected_exception
    assert exc_info.value.args == (body,)


@pytest.mark.asyncio
async def test_edr_get_success_with_quota_in_payload() -> None:
    """A successful response mentioning quota must remain usable data."""
    payload = {"message": "Quota information", "quota_remaining": 10}
    session = _mock_session_with_response(200, json.dumps(payload))

    assert await EDR(session, "token").get("") == payload


@pytest.mark.asyncio
async def test_edr_ignores_quota_in_unrelated_fields() -> None:
    """Unrelated quota text must not override token error classification."""
    edr = EDR(
        _mock_session_with_response(
            403, '{"message": "Forbidden", "details": "quota docs"}'
        ),
        "token",
    )
    with pytest.raises(TokenInvalid) as exc_info:
        await edr.get("")
    assert type(exc_info.value) is TokenInvalid


@pytest.mark.asyncio
async def test_edr_quota_config_flow_does_not_log_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Quota exhaustion maps to CannotConnect without logging server payload."""
    from custom_components.nl_weather.config_flow import (
        CannotConnect,
        validate_edr_input,
    )
    from custom_components.nl_weather.const import CONF_EDR_API_TOKEN

    with (
        patch("custom_components.nl_weather.config_flow.async_get_clientsession"),
        patch("custom_components.nl_weather.config_flow.EDR") as client,
    ):
        client.return_value.metadata = AsyncMock(
            side_effect=QuotaExceeded({"message": "quota", "private": "secret-marker"})
        )
        with pytest.raises(CannotConnect):
            await validate_edr_input(MagicMock(), {CONF_EDR_API_TOKEN: "e30="})
    assert "secret-marker" not in caplog.text
