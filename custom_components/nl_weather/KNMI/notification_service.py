"""KNMI MQTT notification service."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable

import aiomqtt
import paho.mqtt.client as mqtt
from aiomqtt import MqttError, ProtocolVersion
from homeassistant.util.ssl import get_default_context
from paho.mqtt.properties import Properties

_LOGGER = logging.getLogger(__name__)

BROKER_DOMAIN = "mqtt.dataplatform.knmi.nl"
BROKER_PORT = 443
KEEPALIVE = 60

CONNECT_TIMEOUT = 10.0
RECONNECT_DELAY = 30.0

TOPICS = (
    "dataplatform/file/v1/10-minute-in-situ-meteorological-observations/1.0/#",
    "dataplatform/file/v1/radar_forecast/2.0/#",
)

DATASET_OBSERVATIONS = "10-minute-in-situ-meteorological-observations"
DATASET_RADAR = "radar_forecast"

Callback = Callable[[dict[str, object]], Awaitable[None]]


class TokenInvalid(Exception):
    """Raised when the KNMI MQTT token is rejected."""


class NotificationService:
    """Provide KNMI MQTT notifications on all supported platforms."""

    def __init__(self, token: str) -> None:
        """Initialize the KNMI MQTT notification service."""
        self._token = token
        self._loop = asyncio.get_running_loop()
        self._windows = sys.platform == "win32"

        self._stopping = asyncio.Event()
        self._connected = asyncio.Event()

        self._client: aiomqtt.Client | mqtt.Client | None = None
        self._paho_client: mqtt.Client | None = None

        self._callbacks: dict[str, dict[str, Callback]] = {
            DATASET_OBSERVATIONS: {},
            DATASET_RADAR: {},
        }

        self._connection_error: Exception | None = None

        _LOGGER.debug(
            "KNMI MQTT notification service initialized: windows=%s",
            self._windows,
        )

    def set_callback(
        self,
        dataset: str,
        identifier: str,
        callback: Callback,
    ) -> None:
        """Register a callback for a KNMI MQTT dataset."""
        if dataset not in self._callbacks:
            raise ValueError(
                f"Unsupported KNMI MQTT dataset: {dataset}"
            )

        self._callbacks[dataset][identifier] = callback

        _LOGGER.debug(
            "KNMI MQTT callback registered: dataset=%s identifier=%s",
            dataset,
            identifier,
        )

    async def run(self) -> None:
        """Run the MQTT notification service until stopped."""
        _LOGGER.debug("KNMI MQTT notification service started")

        while not self._stopping.is_set():
            self._connected.clear()
            self._connection_error = None

            try:
                if self._windows:
                    await self._run_paho()
                else:
                    await self._run_aiomqtt()

            except asyncio.CancelledError:
                raise

            except TokenInvalid:
                _LOGGER.error("KNMI MQTT token was rejected")
                return

            except Exception:
                _LOGGER.exception(
                    "Unexpected exception in KNMI MQTT notification service"
                )

            finally:
                await self._disconnect()

            if self._stopping.is_set():
                break

            _LOGGER.debug(
                "KNMI MQTT reconnecting in %d seconds",
                RECONNECT_DELAY,
            )

            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=RECONNECT_DELAY,
                )
            except TimeoutError:
                pass

        _LOGGER.debug("KNMI MQTT notification service stopped")

    async def test_connection(self) -> None:
        """Test the KNMI MQTT connection and validate the token."""
        _LOGGER.debug("KNMI MQTT testing connection")

        self._connected.clear()
        self._connection_error = None

        try:
            if self._windows:
                await self._test_paho_connection()
            else:
                await self._test_aiomqtt_connection()
        finally:
            await self._disconnect()

    async def _test_aiomqtt_connection(self) -> None:
        """Test the MQTT connection using aiomqtt."""
        _LOGGER.debug("KNMI MQTT testing connection using aiomqtt")

        async with self._create_aiomqtt_client():
            _LOGGER.debug("KNMI MQTT aiomqtt connection test succeeded")

    async def _test_paho_connection(self) -> None:
        """Test the MQTT connection using Paho on Windows."""
        _LOGGER.debug("KNMI MQTT testing connection using Paho")

        client = self._create_paho_client()
        self._paho_client = client
        self._client = client

        try:
            client.connect(
                BROKER_DOMAIN,
                BROKER_PORT,
                keepalive=KEEPALIVE,
            )

            client.loop_start()

            await self._wait_for_paho_connection()

            if self._connection_error is not None:
                raise self._connection_error

            _LOGGER.debug("KNMI MQTT Paho connection test succeeded")

        finally:
            client.loop_stop()

    async def _run_aiomqtt(self) -> None:
        """Run the asyncio-native MQTT implementation."""
        _LOGGER.debug("KNMI MQTT using aiomqtt transport")

        async with self._create_aiomqtt_client() as client:
            self._client = client

            _LOGGER.debug("KNMI MQTT connected using aiomqtt")

            for topic in TOPICS:
                await client.subscribe(topic)

                _LOGGER.debug(
                    "KNMI MQTT subscribed: topic=%s",
                    topic,
                )

            self._connected.set()

            async for message in client.messages:
                if self._stopping.is_set():
                    break

                await self._handle_message(
                    bytes(message.payload),
                )

    def _create_aiomqtt_client(self) -> aiomqtt.Client:
        """Create the asyncio-native MQTT client."""
        client_id = str(uuid.uuid4())

        _LOGGER.debug(
            "KNMI MQTT creating aiomqtt client: "
            "broker=%s port=%d transport=websockets protocol=MQTTv5 "
            "client_id=%s",
            BROKER_DOMAIN,
            BROKER_PORT,
            client_id,
        )

        return aiomqtt.Client(
            BROKER_DOMAIN,
            port=BROKER_PORT,
            username="token",
            password=self._token,
            protocol=ProtocolVersion.V5,
            transport="websockets",
            identifier=client_id,
            tls_context=get_default_context(),
            timeout=CONNECT_TIMEOUT,
        )

    async def _run_paho(self) -> None:
        """Run the Windows Paho MQTT implementation."""
        _LOGGER.debug("KNMI MQTT using Paho transport")

        client = self._create_paho_client()
        self._paho_client = client
        self._client = client

        try:
            _LOGGER.debug(
                "KNMI MQTT connecting using Paho: "
                "broker=%s port=%d client_id=%s",
                BROKER_DOMAIN,
                BROKER_PORT,
                client._client_id.decode(),
            )

            client.connect(
                BROKER_DOMAIN,
                BROKER_PORT,
                keepalive=KEEPALIVE,
            )

            # Paho owns the network thread on Windows.
            client.loop_start()

            await self._wait_for_paho_connection()

            await self._stopping.wait()

        finally:
            client.loop_stop()

    def _create_paho_client(self) -> mqtt.Client:
        """Create the Windows Paho MQTT client."""
        client_id = str(uuid.uuid4())

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv5,
            transport="websockets",
            reconnect_on_failure=False,
        )

        client.username_pw_set(
            username="token",
            password=self._token,
        )

        client.tls_set_context(
            get_default_context(),
        )

        client.on_connect = self._on_paho_connect
        client.on_disconnect = self._on_paho_disconnect
        client.on_message = self._on_paho_message

        _LOGGER.debug(
            "KNMI MQTT Paho client created: "
            "broker=%s port=%d transport=websockets "
            "protocol=MQTTv5 client_id=%s",
            BROKER_DOMAIN,
            BROKER_PORT,
            client_id,
        )

        return client

    async def _wait_for_paho_connection(self) -> None:
        """Wait until Paho reports a successful MQTT connection."""
        try:
            await asyncio.wait_for(
                self._connected.wait(),
                timeout=CONNECT_TIMEOUT,
            )
        except TimeoutError as err:
            if self._connection_error is not None:
                raise self._connection_error from err

            raise MqttError(
                "KNMI MQTT connection timed out waiting for CONNACK"
            ) from err

    def _on_paho_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: Properties | None,
    ) -> None:
        """Handle a Paho CONNACK callback."""
        _LOGGER.debug(
            "KNMI MQTT Paho on_connect: reason_code=%s flags=%s",
            reason_code,
            flags,
        )
        if reason_code.is_failure:
            if int(reason_code) == 135:
                error: Exception = TokenInvalid(
                    "KNMI MQTT token was rejected by the broker"
                )
            else:
                error = MqttError(
                    f"KNMI MQTT connection rejected: {reason_code}"
                )

            self._loop.call_soon_threadsafe(
                self._set_connection_error,
                error,
            )
            return

        for topic in TOPICS:
            result, _mid = client.subscribe(topic)

            if result != mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.error(
                    "KNMI MQTT Paho subscribe failed: topic=%s result=%s",
                    topic,
                    result,
                )
                continue

            _LOGGER.debug(
                "KNMI MQTT Paho subscribed: topic=%s",
                topic,
            )

        self._loop.call_soon_threadsafe(
            self._connected.set,
        )

    def _on_paho_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: Properties | None,
    ) -> None:
        """Handle a Paho disconnect callback."""
        _LOGGER.debug(
            "KNMI MQTT Paho on_disconnect: reason_code=%s",
            reason_code,
        )

        self._loop.call_soon_threadsafe(
            self._connected.clear,
        )

    def _on_paho_message(
        self,
        client: mqtt.Client,
        userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        """Handle a Paho MQTT message."""
        payload = bytes(message.payload)

        self._loop.call_soon_threadsafe(
            self._schedule_message,
            payload,
        )

    def _schedule_message(self, payload: bytes) -> None:
        """Schedule MQTT message processing on the asyncio event loop."""
        task = self._loop.create_task(
            self._handle_message(payload),
        )

        task.add_done_callback(
            self._message_task_done,
        )

    @staticmethod
    def _message_task_done(
        task: asyncio.Task[None],
    ) -> None:
        """Handle exceptions from asynchronous MQTT message processing."""
        with contextlib.suppress(asyncio.CancelledError):
            exception = task.exception()

            if exception is not None:
                _LOGGER.error(
                    "KNMI MQTT message handling failed",
                    exc_info=exception,
                )

    async def _execute_callback(
        self,
        dataset: str,
        identifier: str,
        callback: Callback,
        event: dict[str, object],
    ) -> None:
        """Execute one KNMI MQTT callback and log its execution."""
        _LOGGER.debug(
            "KNMI MQTT callback executing: dataset=%s identifier=%s",
            dataset,
            identifier,
        )

        await callback(event)

        _LOGGER.debug(
            "KNMI MQTT callback completed: dataset=%s identifier=%s",
            dataset,
            identifier,
        )

    async def _handle_message(
        self,
        payload: bytes,
    ) -> None:
        """Decode and dispatch an MQTT notification."""
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            _LOGGER.warning(
                "KNMI MQTT received invalid JSON payload"
            )
            return

        if not isinstance(event, dict):
            _LOGGER.warning(
                "KNMI MQTT received unexpected payload type: %s",
                type(event).__name__,
            )
            return

        data = event.get("data")

        if not isinstance(data, dict):
            _LOGGER.warning(
                "KNMI MQTT event does not contain valid data"
            )
            return

        dataset = data.get("datasetName")

        if not isinstance(dataset, str):
            _LOGGER.warning(
                "KNMI MQTT event does not contain datasetName"
            )
            return

        callbacks = self._callbacks.get(dataset)

        if not callbacks:
            _LOGGER.debug(
                "KNMI MQTT event has no registered callbacks: dataset=%s",
                dataset,
            )
            return

        _LOGGER.debug(
            "KNMI MQTT event received: dataset=%s callbacks=%d",
            dataset,
            len(callbacks),
        )

        for identifier in callbacks:
            _LOGGER.debug(
                "KNMI MQTT callback executing: dataset=%s identifier=%s",
                dataset,
                identifier,
            )

        results = await asyncio.gather(
            *(
                self._execute_callback(
                    dataset,
                    identifier,
                    callback,
                    event,
                )
                for identifier, callback in callbacks.items()
            ),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                _LOGGER.error(
                    "KNMI MQTT callback failed: dataset=%s error=%s",
                    dataset,
                    result,
                    exc_info=result,
                )

    def _set_connection_error(
        self,
        error: Exception,
    ) -> None:
        """Store a connection error on the asyncio event loop."""
        self._connection_error = error

        if not self._connected.is_set():
            self._connected.set()

    async def _disconnect(self) -> None:
        """Disconnect the active MQTT client."""
        if self._windows:
            await self._disconnect_paho()
        else:
            self._client = None

    async def _disconnect_paho(self) -> None:
        """Disconnect the Windows Paho client."""
        client = self._paho_client

        if client is None:
            return

        self._paho_client = None
        self._client = None

        _LOGGER.debug("KNMI MQTT Paho disconnecting")

        with contextlib.suppress(Exception):
            client.disconnect()

        # loop_stop() is deliberately called here as well as in
        # _run_paho(). Paho handles the second call safely.
        with contextlib.suppress(Exception):
            client.loop_stop()

    async def disconnect(self) -> None:
        """Stop the MQTT notification service."""
        _LOGGER.debug("KNMI MQTT notification service stopping")

        self._stopping.set()

        await self._disconnect()
