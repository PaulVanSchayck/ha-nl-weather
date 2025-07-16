import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import aiomqtt
from aiomqtt import ProtocolVersion, MqttError

from homeassistant.util.ssl import get_default_context

_LOGGER = logging.getLogger(__name__)

BROKER_DOMAIN = "mqtt.dataplatform.knmi.nl"
CLIENT_ID = str(uuid.uuid4())
TOPIC = "dataplatform/file/v1/10-minute-in-situ-meteorological-observations/1.0/#"
PROTOCOL = ProtocolVersion.V5

class NotificationService:
    _client: aiomqtt.Client
    _task: asyncio.Task
    _callback = None

    def __init__(self, token: str):
        tls_context = get_default_context()
        self._client = aiomqtt.Client(BROKER_DOMAIN, username="token", password=token, clean_start=True,
                                      protocol=PROTOCOL, transport="websockets", port=443, identifier=CLIENT_ID,
                                      tls_context=tls_context)

    def set_callback(self, callback):
        self._callback = callback

    async def run(self):
        while True:
            try:
                async with self._client as c:
                    await c.subscribe(TOPIC)
                    _LOGGER.debug("Waiting for messages")
                    async for message in c.messages:
                        await self.handle_message(message)
            except MqttError as e:
                _LOGGER.debug(f"MQTT Error: {e}")
                # TODO: Build in exponential backoff
                await asyncio.sleep(10)
                continue
            except Exception:
                _LOGGER.exception("Exception in NotificationService:")
                raise

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
            async with self._client as c:
                await c.subscribe(TOPIC)
        except aiomqtt.exceptions.MqttConnectError as e:
            if e.rc == 135:
                raise Exception("Invalid token")
        except Exception:
            _LOGGER.exception("Exception occurred")
            return False
        return True