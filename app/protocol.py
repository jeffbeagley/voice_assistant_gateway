"""WebSocket message helpers for the Echo <-> gateway protocol.

Text (JSON) frames are control messages; binary frames carry raw audio.

Client -> Server:
  {"type": "utterance_start"}                  begin a new user utterance
  <binary frames>                               PCM16LE 16kHz mono audio
  {"type": "utterance_end"}                     end of utterance, run pipeline
  {"type": "barge_in"}                          user started talking over TTS playback

Server -> Client:
  {"type": "stt_result", "text": str}
  {"type": "llm_result", "text": str}
  {"type": "tts_start", "format": "pcm16", "sample_rate": int, "sample_width": int, "channels": int}
  <binary frames>                                raw PCM audio chunks
  {"type": "tts_end"}
  {"type": "cancelled"}                          current turn was cancelled (barge-in)
  {"type": "error", "message": str}
"""
from typing import Any


def msg(type_: str, **kwargs: Any) -> dict[str, Any]:
    return {"type": type_, **kwargs}
