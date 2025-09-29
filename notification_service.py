import asyncio
import json
import logging
import uuid

import aiomqtt
from aiomqtt import ProtocolVersion, MqttError
from paho.mqtt import properties

from homeassistant.util.ssl import get_default_context

_LOGGER = logging.getLogger(__name__)

BROKER_DOMAIN = "mqtt.dataplatform.knmi.nl"
CLIENT_ID = str(uuid.uuid4())
TOPICS = [
    "dataplatform/file/v1/10-minute-in-situ-meteorological-observations/1.0/#",
    "dataplatform/file/v1/radar_forecast/2.0/#",
]


class NotificationService:
    _task: asyncio.Task
    _callback = None

    def __init__(self, token: str):
        self._tls_context = get_default_context()
        self._token = token
        self._callbacks = {
            '10-minute-in-situ-meteorological-observations': {},
            'radar_forecast': {},
            'harmonie_arome_cy43_p1': {}
        }

    def _setup_client(self) -> aiomqtt.Client:
        # TODO: Not reusing the client object. Reusing the client object would not work during reconnect
        connect_properties = properties.Properties(properties.PacketTypes.CONNECT)
        return aiomqtt.Client(BROKER_DOMAIN, username="token", password=self._token,
              protocol=ProtocolVersion.V5, transport="websockets", port=443, identifier=CLIENT_ID,
              tls_context=self._tls_context, properties=connect_properties
      )

    def set_callback(self, dataset, identifier, callback):
        self._callbacks[dataset][identifier] = callback

    async def run(self):
        while True:
            try:
                async with self._setup_client() as c:
                    for t in TOPICS:
                        await c.subscribe(t)
                    _LOGGER.debug("Waiting for messages")
                    async for message in c.messages:
                        await self.handle_message(message)
            except MqttError as e:
                _LOGGER.debug(f"MQTT Error: {e}")
                # TODO: Build in exponential backoff
                await asyncio.sleep(30)
            except Exception:
                _LOGGER.exception(f"Exception in NotificationService. Restarting...")
                await asyncio.sleep(30)

    async def handle_message(self, message):
        event = json.loads(message.payload)
        dataset = event["data"]["datasetName"]
        _LOGGER.debug(f"MQTT event: {event}")

        if self._callbacks[dataset] is not None:
            await asyncio.gather(*[c(event) for c in self._callbacks[dataset].values()])

    async def disconnect(self):
        _LOGGER.debug("Disconnected")
        self._task.cancel()

    async def test_connection(self):
        try:
            async with self._setup_client() as c:
                await c.subscribe(TOPICS[0])
        except aiomqtt.exceptions.MqttConnectError as e:
            if e.rc == 135:
                raise TokenInvalid
        except Exception:
            _LOGGER.exception("Exception occurred")
            return False
        return True

class TokenInvalid(Exception):
    """Exception class when token is not accepted"""