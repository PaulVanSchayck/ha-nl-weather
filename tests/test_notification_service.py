"""Regression tests for the KNMI MQTT notification service."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiomqtt import MqttError

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
    reason_code = MagicMock()
    reason_code.is_failure = False

    service._on_paho_connect(client, None, MagicMock(), reason_code, None)
    await asyncio.sleep(0)

    assert [call.args[0] for call in client.subscribe.call_args_list] == list(TOPICS)
    assert service._connection_ready.is_set()
    assert service._connection_error is None


@pytest.mark.asyncio
async def test_paho_connect_classifies_authentication_rejection() -> None:
    """Convert MQTT reason code 135 into a token error on the event loop."""
    service = NotificationService("test-token")
    reason_code = MagicMock()
    reason_code.is_failure = True
    reason_code.__int__.return_value = 135

    service._on_paho_connect(MagicMock(), None, MagicMock(), reason_code, None)
    await asyncio.sleep(0)

    assert service._connection_ready.is_set()
    assert isinstance(service._connection_error, TokenInvalid)


def test_aiomqtt_token_rejection_detection() -> None:
    """Recognize MQTT authorization reason code 135 in broker errors."""
    assert NotificationService._is_token_rejection(MqttError("reason code 135"))
    assert not NotificationService._is_token_rejection(MqttError("connection reset"))
