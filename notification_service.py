import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import aiomqtt
from aiomqtt import ProtocolVersion, MqttError
from paho.mqtt import properties

from homeassistant.util.ssl import get_default_context

_LOGGER = logging.getLogger(__name__)

BROKER_DOMAIN = "mqtt.dataplatform.knmi.nl"
CLIENT_ID = str(uuid.uuid4())
TOPIC = "dataplatform/file/v1/10-minute-in-situ-meteorological-observations/1.0/#"


class NotificationService:
    _task: asyncio.Task
    _callback = None

    def __init__(self, token: str):
        self._tls_context = get_default_context()
        self._token = token

    def _setup_client(self) -> aiomqtt.Client:
        # TODO: Not reusing the client object. Reusing the client object would not work during reconnect
        connect_properties = properties.Properties(properties.PacketTypes.CONNECT)
        return aiomqtt.Client(BROKER_DOMAIN, username="token", password=self._token,
              protocol=ProtocolVersion.V5, transport="websockets", port=443, identifier=CLIENT_ID,
              tls_context=self._tls_context, properties=connect_properties
      )

    def set_callback(self, callback):
        self._callback = callback

    async def run(self):
        while True:
            try:
                async with self._setup_client() as c:
                    await c.subscribe(TOPIC)
                    _LOGGER.debug("Waiting for messages")
                    async for message in c.messages:
                        await self.handle_message(message)
            except MqttError as e:
                _LOGGER.debug(f"MQTT Error: {e}")
                # TODO: Build in exponential backoff
                await asyncio.sleep(30)
            except Exception as e:
                _LOGGER.error(f"Exception in NotificationService: '{e}'. Restarting...")
                await asyncio.sleep(30)

    async def handle_message(self, message):
        event = json.loads(message.payload)
        _LOGGER.debug(f"MQTT event: {event}")
        dt = datetime.strptime(event["data"]["filename"], "KMDS__OPER_P___10M_OBS_L2_%Y%m%d%H%M.nc").replace(
            tzinfo=timezone.utc)
        if self._callback is not None:
            await self._callback(dt)

    async def disconnect(self):
        _LOGGER.debug("Disconnected")
        self._task.cancel()

    async def test_connection(self):
        try:
            async with self._setup_client() as c:
                await c.subscribe(TOPIC)
        except aiomqtt.exceptions.MqttConnectError as e:
            if e.rc == 135:
                raise Exception("Invalid token")
        except Exception:
            _LOGGER.exception("Exception occurred")
            return False
        return True