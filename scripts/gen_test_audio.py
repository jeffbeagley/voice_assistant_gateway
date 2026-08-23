#!/usr/bin/env python3
"""Generate a test WAV by asking Piper (via Wyoming protocol) to speak some text.

Useful when no microphone is available for producing test input audio.

Usage:
    python3 scripts/gen_test_audio.py "what is the capital of France" out.wav
"""
import asyncio
import json
import sys
import wave


async def synthesize(host: str, port: int, text: str) -> tuple[dict, bytes]:
    reader, writer = await asyncio.open_connection(host, port)
    writer.write((json.dumps({"type": "synthesize", "data": {"text": text}}) + "\n").encode())
    await writer.drain()

    fmt = None
    chunks = []
    while True:
        line = await reader.readline()
        if not line:
            break
        header = json.loads(line)
        data = dict(header.get("data") or {})
        if header.get("data_length"):
            data.update(json.loads(await reader.readexactly(header["data_length"])))
        payload = b""
        if header.get("payload_length"):
            payload = await reader.readexactly(header["payload_length"])

        if header["type"] == "audio-start":
            fmt = data
        elif header["type"] == "audio-chunk":
            chunks.append(payload)
        elif header["type"] == "audio-stop":
            break

    writer.close()
    await writer.wait_closed()
    return fmt, b"".join(chunks)


def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else "what is the capital of France"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "test_input.wav"
    fmt, pcm = asyncio.run(synthesize("localhost", 10200, text))

    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(fmt["channels"])
        wf.setsampwidth(fmt["width"])
        wf.setframerate(fmt["rate"])
        wf.writeframes(pcm)
    print(f"wrote {out_path} ({len(pcm)} bytes pcm, {fmt})")


if __name__ == "__main__":
    main()
