"""Voice gateway: Echo (LineageOS device) <-> Parakeet STT -> vLLM -> Piper TTS.

WebSocket endpoint at /ws/converse implements the protocol documented in
app/protocol.py, including basic barge-in (a new utterance_start or an
explicit barge_in message cancels any in-flight pipeline/TTS for that
session).
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.clients.parakeet import ParakeetClient
from app.clients.piper import PiperClient
from app.clients.vllm import VLLMClient
from app.config import get_settings
from app.protocol import msg
from app.session import ConversationSession, SessionManager

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("voice_gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.parakeet = ParakeetClient(settings)
    app.state.vllm = VLLMClient(settings)
    app.state.piper = PiperClient(settings)
    app.state.sessions = SessionManager(settings.session_idle_timeout_seconds)
    try:
        yield
    finally:
        await app.state.parakeet.aclose()
        await app.state.vllm.aclose()
        await app.state.piper.aclose()


app = FastAPI(title="voice-assistant-gateway", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ready"}


async def _safe_send_json(ws: WebSocket, payload: dict) -> bool:
    if ws.client_state != WebSocketState.CONNECTED:
        return False
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        return False


async def _safe_send_bytes(ws: WebSocket, data: bytes) -> bool:
    if ws.client_state != WebSocketState.CONNECTED:
        return False
    try:
        await ws.send_bytes(data)
        return True
    except Exception:
        return False


async def process_utterance(ws: WebSocket, session: ConversationSession, audio: bytes) -> None:
    """Run STT -> LLM -> TTS for one utterance and stream the reply back."""
    try:
        text = await ws.app.state.parakeet.transcribe(audio)
        if not text:
            await _safe_send_json(ws, msg("error", message="empty transcription"))
            return
        await _safe_send_json(ws, msg("stt_result", text=text))

        session.append("user", text, settings.max_history_turns)
        messages = [{"role": "system", "content": settings.system_prompt}, *session.history]

        reply = await ws.app.state.vllm.chat(messages)
        session.append("assistant", reply, settings.max_history_turns)
        await _safe_send_json(ws, msg("llm_result", text=reply))

        # Stream TTS audio to the client as Piper produces it, instead of
        # waiting for the entire reply to finish synthesizing.
        tts_started = False
        async for kind, value in ws.app.state.piper.synthesize_stream(reply):
            if kind == "format":
                tts_started = True
                await _safe_send_json(
                    ws,
                    msg(
                        "tts_start",
                        format="pcm16",
                        sample_rate=value.rate,
                        sample_width=value.width,
                        channels=value.channels,
                    ),
                )
            else:
                if not await _safe_send_bytes(ws, value):
                    return
        if tts_started:
            await _safe_send_json(ws, msg("tts_end"))
    except asyncio.CancelledError:
        await _safe_send_json(ws, msg("cancelled"))
        raise
    except Exception as exc:  # noqa: BLE001 - report to client and keep session alive
        logger.exception("pipeline error for session %s", session.session_id)
        await _safe_send_json(ws, msg("error", message=str(exc)))


@app.websocket("/ws/converse")
async def converse(ws: WebSocket) -> None:
    await ws.accept()
    session = ws.app.state.sessions.create()
    logger.info("session %s connected", session.session_id)

    audio_buffer = bytearray()
    in_utterance = False

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if (text := message.get("text")) is not None:
                import json

                try:
                    payload = json.loads(text)
                except ValueError:
                    await _safe_send_json(ws, msg("error", message="invalid json"))
                    continue

                msg_type = payload.get("type")
                session.touch()

                if msg_type == "utterance_start":
                    # Barge-in: cancel whatever the pipeline is currently doing.
                    await session.cancel_active()
                    audio_buffer = bytearray()
                    in_utterance = True

                elif msg_type == "barge_in":
                    await session.cancel_active()
                    await _safe_send_json(ws, msg("cancelled"))

                elif msg_type == "utterance_end":
                    in_utterance = False
                    if audio_buffer:
                        audio_bytes = bytes(audio_buffer)
                        audio_buffer = bytearray()
                        session.active_task = asyncio.create_task(
                            process_utterance(ws, session, audio_bytes)
                        )
                    else:
                        await _safe_send_json(ws, msg("error", message="no audio received"))

                else:
                    await _safe_send_json(ws, msg("error", message=f"unknown type {msg_type}"))

            elif (data := message.get("bytes")) is not None:
                if in_utterance:
                    audio_buffer.extend(data)

    except WebSocketDisconnect:
        pass
    finally:
        await session.cancel_active()
        ws.app.state.sessions.remove(session.session_id)
        logger.info("session %s disconnected", session.session_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_level=settings.log_level)
