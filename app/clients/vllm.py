"""Client for the vLLM OpenAI-compatible chat completions endpoint."""
import httpx

from app.config import Settings


class VLLMClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        headers = {}
        if settings.vllm_api_key:
            headers["Authorization"] = f"Bearer {settings.vllm_api_key}"
        self._client = httpx.AsyncClient(
            base_url=settings.vllm_base_url,
            timeout=settings.vllm_timeout_seconds,
            headers=headers,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """Send a chat history and return the assistant's reply text."""
        payload = {
            "model": self._settings.vllm_model,
            "messages": messages,
            "max_tokens": self._settings.vllm_max_tokens,
            "temperature": self._settings.vllm_temperature,
            "stream": False,
            # Qwen3's "thinking" mode otherwise burns tokens/latency on a
            # reasoning trace and can leave `content` null if it hits max_tokens.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = await self._client.post(self._settings.vllm_chat_path, json=payload)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"].get("content")
        return (content or "").strip()
