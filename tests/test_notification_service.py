"""Regression tests for the KNMI MQTT notification service."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiomqtt import MqttError
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from custom_components.nl_weather.KNMI.notification_service import (
    DATASET_OBSERVATIONS,
    TOPICS,
    NotificationService,
    TokenInvalid,
)


@pytest.mark.asyncio
async def test_handle_message_dispatches_registered_dataset_callback() -> None:
    """Dispatch a valid observation event to its registered callback."""
    service = NotificationService("test-token")
    callback = AsyncMock()
    service.set_callback(DATASET_OBSERVATIONS, "test-location", callback)
    event = {"data": {"datasetName": DATASET_OBSERVATIONS, "id": "event-1"}}

    await service._handle_message(json.dumps(event).encode())

    callback.assert_awaited_once_with(event)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"null",
        json.dumps({"data": None}).encode(),
        json.dumps({"data": {"datasetName": None}}).encode(),
        json.dumps({"data": {"datasetName": "unknown-dataset"}}).encode(),
    ],
)
async def test_handle_message_ignores_invalid_or_unregistered_events(
    payload: bytes,
) -> None:
    """Ignore malformed events without invoking dataset callbacks."""
    service = NotificationService("test-token")
    callback = AsyncMock()
    service.set_callback(DATASET_OBSERVATIONS, "test-location", callback)

    await service._handle_message(payload)

    callback.assert_not_awaited()


def test_set_callback_rejects_unknown_dataset() -> None:
    """Reject registrations for datasets that are not subscribed."""
    service = NotificationService.__new__(NotificationService)
    service._callbacks = {DATASET_OBSERVATIONS: {}}

    with pytest.raises(ValueError, match="Unsupported KNMI MQTT dataset"):
        service.set_callback("unknown-dataset", "test-location", AsyncMock())


@pytest.mark.asyncio
async def test_disconnect_stops_service_and_clears_async_client() -> None:
    """Signal shutdown and release the asyncio MQTT client reference."""
    with patch(
        "custom_components.nl_weather.KNMI.notification_service.sys.platform",
        "linux",
    ):
        service = NotificationService("test-token")
    service._client = MagicMock()

    await service.disconnect()

    assert service._stopping.is_set()
    assert service._client is None


@pytest.mark.asyncio
async def test_windows_connection_test_uses_paho_fallback() -> None:
    """Select the Paho transport on Windows rather than aiomqtt."""
    with patch(
        "custom_components.nl_weather.KNMI.notification_service.sys.platform",
        "win32",
    ):
        service = NotificationService("test-token")

    with (
        patch.object(
            service, "_test_paho_connection", new_callable=AsyncMock
        ) as test_paho,
        patch.object(
            service, "_test_aiomqtt_connection", new_callable=AsyncMock
        ) as test_aiomqtt,
    ):
        await service.test_connection()

    test_paho.assert_awaited_once_with()
    test_aiomqtt.assert_not_awaited()


@pytest.mark.asyncio
async def test_paho_connect_subscribes_to_all_topics() -> None:
    """Subscribe to both KNMI datasets after a successful Paho CONNACK."""
    service = NotificationService("test-token")
    client = MagicMock()
    client.subscribe.return_value = (0, 1)
    reason_code = ReasonCode(PacketTypes.CONNACK, identifier=0)

    service._on_paho_connect(client, None, MagicMock(), reason_code, None)
    await asyncio.sleep(0)

    assert [call.args[0] for call in client.subscribe.call_args_list] == list(TOPICS)
    assert service._connection_ready.is_set()
    assert service._connection_error is None


@pytest.mark.asyncio
async def test_paho_connect_classifies_authentication_rejection() -> None:
    """Convert MQTT reason code 135 into a token error on the event loop."""
    service = NotificationService("test-token")
    reason_code = ReasonCode(PacketTypes.CONNACK, identifier=135)

    service._on_paho_connect(MagicMock(), None, MagicMock(), reason_code, None)
    await asyncio.sleep(0)

    assert service._connection_ready.is_set()
    assert isinstance(service._connection_error, TokenInvalid)


def test_aiomqtt_token_rejection_detection() -> None:
    """Recognize MQTT authorization reason code 135 in broker errors."""
    assert NotificationService._is_token_rejection(MqttError("reason code 135"))
    assert not NotificationService._is_token_rejection(MqttError("connection reset"))


@pytest.mark.asyncio
async def test_paho_disconnect_signals_connection_loss() -> None:
    """Wake the service loop when an established Paho connection drops."""
    from custom_components.nl_weather.KNMI.notification_service import ConnectionState

    service = NotificationService("test-token")
    service._paho_state = ConnectionState.CONNECTED

    service._handle_paho_disconnect()

    assert service._paho_state is ConnectionState.DISCONNECTED
    assert service._connection_lost.is_set()


@pytest.mark.asyncio
async def test_paho_disconnect_releases_client_resources() -> None:
    """Clear Paho client references and stop its network thread on shutdown."""
    with patch(
        "custom_components.nl_weather.KNMI.notification_service.sys.platform",
        "win32",
    ):
        service = NotificationService("test-token")
    client = MagicMock()
    service._paho_client = client
    service._client = client

    await service.disconnect()

    client.disconnect.assert_called_once_with()
    assert service._paho_client is None
    assert service._client is None
    assert service._stopping.is_set()


@pytest.mark.asyncio
async def test_paho_connection_wait_times_out() -> None:
    """Report a bounded connection timeout when no CONNACK arrives."""
    from custom_components.nl_weather.KNMI import notification_service

    service = NotificationService("test-token")
    with (
        patch.object(notification_service, "CONNECT_TIMEOUT", 0.001),
        pytest.raises(MqttError, match="timed out waiting for CONNACK"),
    ):
        await service._wait_for_paho_connection()


@pytest.mark.asyncio
async def test_paho_subscribe_failure_is_reported() -> None:
    """Surface a broker subscription failure through the connection event."""
    service = NotificationService("test-token")
    client = MagicMock()
    client.subscribe.return_value = (1, 0)
    reason_code = ReasonCode(PacketTypes.CONNACK, identifier=0)

    service._on_paho_connect(client, None, MagicMock(), reason_code, None)
    await asyncio.sleep(0)

    assert service._connection_ready.is_set()
    assert isinstance(service._connection_error, MqttError)


@pytest.mark.asyncio
async def test_aiomqtt_connection_converts_authentication_rejection() -> None:
    """Map broker authorization rejection to the integration token error."""
    service = NotificationService("test-token")
    client = MagicMock()
    client.__aenter__ = AsyncMock(side_effect=MqttError("reason code 135"))
    client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(service, "_create_aiomqtt_client", return_value=client),
        pytest.raises(TokenInvalid, match="token was rejected"),
    ):
        await service._test_aiomqtt_connection()


@pytest.mark.asyncio
async def test_aiomqtt_connection_preserves_transport_errors() -> None:
    """Leave ordinary broker failures classified as MQTT connection errors."""
    service = NotificationService("test-token")
    error = MqttError("connection reset")
    client = MagicMock()
    client.__aenter__ = AsyncMock(side_effect=error)
    client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(service, "_create_aiomqtt_client", return_value=client),
        pytest.raises(MqttError) as exc_info,
    ):
        await service._test_aiomqtt_connection()

    assert exc_info.value is error
