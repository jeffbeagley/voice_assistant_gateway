#!/usr/bin/env python3
"""Manual end-to-end test client for the voice gateway's /ws/converse endpoint.

Usage:
    # after `kubectl port-forward svc/<gateway-service> 8080:8080 -n voice-agent`
    python3 scripts/test_client.py path/to/utterance.wav
    python3 scripts/test_client.py --record 4   # record 4s from the default mic

The input WAV is converted to PCM16LE 16kHz mono (what the gateway expects) via
ffmpeg, streamed over the websocket, and the reply audio is saved to
out_reply.wav.
"""
import argparse
import asyncio
import json
import subprocess
import sys
import wave

import websockets

CHUNK_SIZE = 3200  # 100ms of 16kHz/16-bit/mono audio


def to_pcm16_mono_16k(input_path: str) -> bytes:
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, "-f", "s16le", "-ar", "16000", "-ac", "1", "-"],
        capture_output=True,
        check=True,
    )
    return result.stdout


def record_from_mic(seconds: int) -> bytes:
    print(f"Recording {seconds}s from default mic...", file=sys.stderr)
    result = subprocess.run(
        ["arecord", "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(seconds), "-t", "raw"],
        capture_output=True,
        check=True,
    )
    return result.stdout


async def run(uri: str, pcm: bytes) -> None:
    async with websockets.connect(uri, max_size=None) as ws:
        await ws.send(json.dumps({"type": "utterance_start"}))
        for i in range(0, len(pcm), CHUNK_SIZE):
            await ws.send(pcm[i : i + CHUNK_SIZE])
        await ws.send(json.dumps({"type": "utterance_end"}))

        audio_format = None
        audio_chunks: list[bytes] = []
        while True:
            message = await ws.recv()
            if isinstance(message, bytes):
                audio_chunks.append(message)
                continue

            payload = json.loads(message)
            print("<-", payload)
            if payload["type"] == "tts_start":
                audio_format = payload
            elif payload["type"] in ("tts_end", "error", "cancelled"):
                break

        if audio_chunks:
            out_path = "out_reply.wav"
            with wave.open(out_path, "wb") as wf:
                wf.setnchannels(audio_format.get("channels", 1))
                wf.setsampwidth(audio_format.get("sample_width", 2))
                wf.setframerate(audio_format.get("sample_rate", 22050))
                wf.writeframes(b"".join(audio_chunks))
            print(f"Saved reply audio to {out_path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav_file", nargs="?", help="Path to an audio file (any format ffmpeg can read)")
    parser.add_argument("--record", type=int, metavar="SECONDS", help="Record from the default mic instead")
    parser.add_argument("--uri", default="ws://localhost:8080/ws/converse")
    args = parser.parse_args()

    if args.record:
        pcm = record_from_mic(args.record)
    elif args.wav_file:
        pcm = to_pcm16_mono_16k(args.wav_file)
    else:
        parser.error("provide a wav_file or --record SECONDS")

    asyncio.run(run(args.uri, pcm))


if __name__ == "__main__":
    main()
