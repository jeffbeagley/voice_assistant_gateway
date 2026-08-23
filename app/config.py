"""Runtime configuration for the voice gateway.

All values can be overridden via environment variables (prefix ``GATEWAY_``),
which is how the Helm chart wires values.yaml into the container.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"

    # --- Parakeet STT (assumed OpenAI-compatible /v1/audio/transcriptions) ---
    parakeet_base_url: str = "http://parakeet-api.default.svc.cluster.local:8000"
    parakeet_transcribe_path: str = "/v1/audio/transcriptions"
    parakeet_model: str = "parakeet"
    parakeet_timeout_seconds: float = 30.0

    # --- vLLM (OpenAI-compatible /v1/chat/completions) ---
    vllm_base_url: str = "http://vllm.default.svc.cluster.local:8000"
    vllm_chat_path: str = "/v1/chat/completions"
    vllm_model: str = "cyankiwi/Qwen3.5-9B-AWQ-4bit"
    vllm_api_key: str = ""
    vllm_timeout_seconds: float = 60.0
    vllm_max_tokens: int = 512
    vllm_temperature: float = 0.7
    system_prompt: str = (
        "You are a helpful, concise voice assistant. Keep replies short and "
        "conversational since they will be read aloud."
    )

    # --- Piper TTS (rhasspy/wyoming-piper speaks the Wyoming protocol over
    # plain TCP, not HTTP) ---
    piper_host: str = "piper-tts.default.svc.cluster.local"
    piper_port: int = 10200
    piper_voice: str = ""  # empty = use the server's default/only loaded voice

    # --- Session / conversation ---
    max_history_turns: int = 10
    session_idle_timeout_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
