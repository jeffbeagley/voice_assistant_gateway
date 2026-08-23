# voice_assistant_gateway

Thin service that bridges an Echo-style device (custom LineageOS client, TBD)
to a set of self-hosted AI services running in Kubernetes:

- **Parakeet STT** — speech-to-text (OpenAI-compatible `/v1/audio/transcriptions`)
- **vLLM + Qwen** — chat completions (OpenAI-compatible `/v1/chat/completions`)
- **Piper TTS** — text-to-speech

## Pipeline

1. Client opens a WebSocket to `/ws/converse` and streams PCM16LE 16kHz mono
   audio for one utterance (after its own wake-word detection).
2. Gateway sends the audio to Parakeet, gets text back.
3. Gateway appends the text to the session's conversation history and calls
   vLLM for a reply.
4. Gateway sends the reply to Piper and streams the resulting audio back to
   the client in chunks.
5. Barge-in: if the client sends a new `utterance_start` (or explicit
   `barge_in`) while a reply is still being generated/streamed, the gateway
   cancels the in-flight pipeline/TTS stream and starts fresh.

See [app/protocol.py](app/protocol.py) for the full WebSocket message schema.

## Status / open items

- The Echo-side client (LineageOS app) is out of scope for this repo and not
  yet built — the protocol above is what it should implement.
- Piper (`rhasspy/wyoming-piper`) speaks the Wyoming protocol over plain TCP,
  handled in [app/clients/piper.py](app/clients/piper.py). Parakeet and vLLM
  are OpenAI-compatible REST APIs.
- Conversation state is in-memory per pod (single replica). See "Scaling"
  below before running >1 replica.
- Verify the `config.vllm.model` value in `values.yaml` matches whatever your
  vLLM deployment actually serves (check with `GET /v1/models`) — it will not
  match the chart default in a different cluster.

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GATEWAY_PARAKEET_BASE_URL=http://localhost:9000
export GATEWAY_VLLM_BASE_URL=http://localhost:9001
export GATEWAY_PIPER_BASE_URL=http://localhost:9002
uvicorn app.main:app --reload --port 8080
```

Config is entirely via `GATEWAY_*` environment variables — see
[app/config.py](app/config.py) for the full list and defaults.

## Container image

```bash
docker build -t registry.example.com/voice-assistant-gateway:0.1.0 .
docker push registry.example.com/voice-assistant-gateway:0.1.0
```

## Helm chart

Chart lives at [helm/voice-assistant-gateway](helm/voice-assistant-gateway).
All backend URLs, models, timeouts, prompt, history length, etc. are exposed
via `values.yaml` under `config.*` and rendered into a ConfigMap (+ a Secret
for `GATEWAY_VLLM_API_KEY`, or point `existingSecret` at your own).

```bash
helm lint helm/voice-assistant-gateway
helm upgrade --install voice-gateway helm/voice-assistant-gateway \
  --namespace voice-agent --create-namespace \
  --set image.repository=<your-registry>/voice-assistant-gateway \
  --set image.tag=0.0.5 \
  --set config.parakeet.baseUrl=http://parakeet-api.<ns>.svc.cluster.local:5092 \
  --set config.vllm.baseUrl=http://<vllm-service>.<ns>.svc.cluster.local:80 \
  --set config.vllm.model=<model id from GET /v1/models> \
  --set config.piper.host=piper-tts.<ns>.svc.cluster.local \
  --set config.piper.port=10200
```

For Flux, add this chart (or an `OCIRepository`/`HelmRepository` pointing at
it once published) plus a `HelmRelease` with a `values` block matching
`values.yaml`.

## Testing

There's no Echo-side client yet, so `scripts/test_client.py` stands in for it:
it streams a WAV file to `/ws/converse` exactly like a real client would, and
prints/saves the STT/LLM/TTS results.

1. Port-forward the gateway (and Piper, if you need step 2) from the cluster:

   ```bash
   kubectl -n voice-agent port-forward svc/voice-gateway-voice-assistant-gateway 8080:8080
   kubectl -n voice-agent port-forward svc/piper-tts 10200:10200   # only needed for gen_test_audio.py
   ```

   `port-forward` against a Service drops the connection whenever the backing
   pod is replaced (e.g. after a Helm upgrade) — just re-run the command if
   you see connection errors.

2. Set up a local Python env with `websockets` (only needed for the test
   scripts, not the gateway itself):

   ```bash
   python3 -m venv .venv && .venv/bin/pip install websockets
   ```

3. Get a test utterance. Either record one, or — if no mic is available —
   have Piper say something for you:

   ```bash
   .venv/bin/python3 scripts/gen_test_audio.py "what time is it" test_input.wav
   # or: .venv/bin/python3 scripts/test_client.py --record 4   (records from the default mic)
   ```

4. Run the full pipeline against the gateway:

   ```bash
   .venv/bin/python3 scripts/test_client.py test_input.wav
   ```

   Expected output is the `stt_result` / `llm_result` / `tts_start` / `tts_end`
   messages printed as they arrive, plus a `out_reply.wav` file you can play
   back to confirm the TTS audio is valid, e.g. `ffplay -autoexit out_reply.wav`.

5. To sanity-check a single backend in isolation (useful when the gateway
   reports an error), hit it directly from inside the cluster, e.g.:

   ```bash
   kubectl -n voice-agent run curltest --rm -i --restart=Never --image=curlimages/curl -- \
     curl -s http://<vllm-service>.<ns>.svc.cluster.local:80/v1/models
   ```

### Testing hands-free with a wake word in a browser

[web/index.html](web/index.html) is a zero-build, single-file test console
that mimics a real Echo-like client: it runs the pretrained **"hey_jarvis"**
[openWakeWord](https://github.com/dscripka/openWakeWord) model client-side
(via [onnxruntime-web](https://github.com/microsoft/onnxruntime), loaded from
a CDN — no server-side wake word component), auto-connects to the gateway
with indefinite retry, and on detecting the wake word automatically records
until you stop talking (simple energy-based silence detection) and streams
the utterance to the gateway. The reply plays back automatically. No buttons
to press other than a one-time "enable microphone" click.

The ONNX models live in [web/models/](web/models/) (downloaded from the
openWakeWord releases — pretrained models are CC BY-NC-SA 4.0, non-commercial
use only).

```bash
kubectl -n voice-agent port-forward svc/voice-gateway-voice-assistant-gateway 8080:8080
cd web && python3 -m http.server 8081
```

Then open http://localhost:8081 (must be `http://localhost`, or a
`chrome://flags/#unsafely-treat-insecure-origin-as-secure` override for a
plain-HTTP LAN address — mic access requires a secure context). Click
**Enable Microphone & Start**, say "Hey Jarvis", then speak your request. The
orb and status text reflect the pipeline state (listening / wake detected /
recording / thinking / speaking), and the log panel shows the raw
`stt_result` / `llm_result` / `tts_start` / `tts_end` messages as they arrive.

## Scaling beyond one replica

Session/conversation state is currently held in memory per pod. If you need
multiple replicas or restart resilience, swap `app/session.py`'s
`SessionManager` for a Redis-backed implementation and ensure the client
reconnects to a sticky session (or gateway looks up state by a client-supplied
session id in Redis instead of tying it to the websocket connection).
