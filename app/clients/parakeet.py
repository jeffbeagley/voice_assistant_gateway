"""Client for the Parakeet STT service (OpenAI-compatible transcription API)."""
import io
import wave

import httpx

from app.config import Settings


def _pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class ParakeetClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.parakeet_base_url,
            timeout=settings.parakeet_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        """Send raw PCM16LE mono audio to Parakeet and return the transcribed text."""
        wav_bytes = _pcm16_to_wav(pcm, sample_rate)
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"model": self._settings.parakeet_model}
        response = await self._client.post(
            self._settings.parakeet_transcribe_path, files=files, data=data
        )
        response.raise_for_status()
        payload = response.json()
        # OpenAI's transcription API returns {"text": "..."}
        return payload.get("text", "").strip()
