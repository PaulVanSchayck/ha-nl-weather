"""Unit tests for EDR credential validation in the configuration flow."""

from base64 import b64encode
from unittest.mock import MagicMock, patch

import aiohttp
import pytest
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MODE,
    CONF_NAME,
    CONF_REGION,
)
from homeassistant.data_entry_flow import FlowResultType

from custom_components.nl_weather.config_flow import (
    CannotConnect,
    InvalidToken,
    LocationSubentryFlowHandler,
    validate_edr_input,
)
from custom_components.nl_weather.const import CONF_EDR_API_TOKEN, StationMode
from custom_components.nl_weather.KNMI.edr import (
    QuotaExceeded,
    ServerError,
    TokenInvalid,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_error", "expected_exception"),
    [
        pytest.param(
            QuotaExceeded({"message": "Quota Exceeded"}),
            CannotConnect,
            id="quota-is-temporary-connection-error",
        ),
        pytest.param(
            TokenInvalid({"message": "Forbidden"}),
            InvalidToken,
            id="invalid-token-is-authentication-error",
        ),
        pytest.param(ServerError("Status code: 503"), CannotConnect, id="server"),
        pytest.param(
            aiohttp.ClientConnectionError("Connection failed"),
            CannotConnect,
            id="connection",
        ),
        pytest.param(TimeoutError(), CannotConnect, id="timeout"),
    ],
)
async def test_validate_edr_input_classifies_api_errors(
    api_error: Exception, expected_exception: type[Exception]
) -> None:
    """Quota exhaustion is retryable; rejected credentials stay invalid."""
    token = b64encode(b'{"key": "test-value"}').decode()
    hass = MagicMock()
    session = MagicMock()

    with (
        patch(
            "custom_components.nl_weather.config_flow.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.nl_weather.config_flow.EDR", autospec=True
        ) as edr_class,
    ):
        edr_class.return_value.metadata.side_effect = api_error

        with pytest.raises(expected_exception) as exc_info:
            await validate_edr_input(hass, {CONF_EDR_API_TOKEN: token})

        assert type(exc_info.value) is expected_exception
        assert exc_info.value.__cause__ is api_error
        edr_class.assert_called_once_with(session, token)
        edr_class.return_value.metadata.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_validate_edr_input_accepts_successful_probe() -> None:
    """Successful metadata validation still accepts the supplied credentials."""
    token = b64encode(b'{"key": "test-value"}').decode()
    hass = MagicMock()
    session = MagicMock()

    with (
        patch(
            "custom_components.nl_weather.config_flow.async_get_clientsession",
            return_value=session,
        ) as get_session,
        patch(
            "custom_components.nl_weather.config_flow.EDR", autospec=True
        ) as edr_class,
    ):
        edr_class.return_value.metadata.return_value = {"id": "observations"}

        assert await validate_edr_input(hass, {CONF_EDR_API_TOKEN: token}) is None

        get_session.assert_called_once_with(hass)
        edr_class.assert_called_once_with(session, token)
        edr_class.return_value.metadata.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_location_subentry_outside_wms_bbox_returns_error() -> None:
    """Test that location coordinates outside WMS bbox return error."""
    handler = LocationSubentryFlowHandler()
    hass = MagicMock()
    hass.config.location_name = "Home"
    hass.config.latitude = 52.0
    hass.config.longitude = 5.0
    handler.hass = hass

    user_input = {
        CONF_NAME: "Far Away",
        CONF_LATITUDE: 0.0,
        CONF_LONGITUDE: 0.0,
        CONF_REGION: "1",
        CONF_MODE: StationMode.AUTO,
    }

    result = await handler.async_step_location(user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "outside_wms_bbox"}


@pytest.mark.asyncio
async def test_location_subentry_inside_wms_bbox_succeeds() -> None:
    """Test that location coordinates inside WMS bbox succeed."""
    handler = LocationSubentryFlowHandler()
    hass = MagicMock()
    hass.config.location_name = "Home"
    hass.config.latitude = 52.0
    hass.config.longitude = 5.0
    handler.hass = hass

    user_input = {
        CONF_NAME: "Amsterdam",
        CONF_LATITUDE: 52.37,
        CONF_LONGITUDE: 4.89,
        CONF_REGION: "9",
        CONF_MODE: StationMode.AUTO,
    }

    result = await handler.async_step_location(user_input)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Amsterdam"
    assert result["data"] == user_input
