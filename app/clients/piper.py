"""Client for Piper TTS via the Wyoming protocol (rhasspy/wyoming-piper).

Wyoming is a line-delimited JSON event protocol over a plain TCP socket: each
event is `{"type": ..., "data": {...}, "data_length": N, "payload_length": M}\\n`
optionally followed by N bytes of extra JSON data and then M bytes of binary
payload. See https://github.com/OHF-Voice/wyoming for the full spec.
"""
import asyncio
import json
from dataclasses import dataclass

from app.config import Settings


@dataclass
class AudioFormat:
    rate: int
    width: int
    channels: int


class PiperClient:
    def __init__(self, settings: Settings):
        self._host = settings.piper_host
        self._port = settings.piper_port
        self._voice = settings.piper_voice or None

    async def aclose(self) -> None:
        pass  # connections are opened/closed per request

    @staticmethod
    async def _read_event(reader: asyncio.StreamReader):
        line = await reader.readline()
        if not line:
            return None
        header = json.loads(line)
        data = dict(header.get("data") or {})
        data_length = header.get("data_length")
        if data_length:
            extra = await reader.readexactly(data_length)
            data.update(json.loads(extra))
        payload = b""
        payload_length = header.get("payload_length")
        if payload_length:
            payload = await reader.readexactly(payload_length)
        return header["type"], data, payload

    async def synthesize_stream(self, text: str):
        """Send text to Piper, yielding audio as it's generated (not buffered).

        Yields ("format", AudioFormat) once, followed by ("chunk", bytes) for
        each PCM chunk as Piper produces it. Streaming (instead of waiting for
        audio-stop) avoids adding the full synthesis time as latency before
        the client hears anything.
        """
        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            request: dict = {"type": "synthesize", "data": {"text": text}}
            if self._voice:
                request["data"]["voice"] = {"name": self._voice}
            writer.write((json.dumps(request) + "\n").encode("utf-8"))
            await writer.drain()

            while True:
                event = await self._read_event(reader)
                if event is None:
                    break
                event_type, data, payload = event
                if event_type == "audio-start":
                    yield "format", AudioFormat(
                        rate=data["rate"], width=data["width"], channels=data["channels"]
                    )
                elif event_type == "audio-chunk":
                    yield "chunk", payload
                elif event_type == "audio-stop":
                    break
        finally:
            writer.close()
            await writer.wait_closed()
