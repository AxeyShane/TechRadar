"""Thin OpenAI-compatible LLM client -- works against OpenRouter or a local
llama.cpp server, same pattern as ApplyPilot's llm.py."""

import os

import httpx


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._is_local = "127.0.0.1" in base_url or "localhost" in base_url

    def ask(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._is_local:
            # Hybrid-thinking local models (SmolLM3, Qwen3.5) burn the whole
            # token budget on hidden reasoning_content unless told not to --
            # same bug hit and fixed in ApplyPilot's llm.py.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        resp = httpx.post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=60.0)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


_instance: LLMClient | None = None


def get_client() -> LLMClient:
    global _instance
    if _instance is None:
        url = os.environ.get("LLM_URL", "https://openrouter.ai/api/v1")
        model = os.environ.get("LLM_MODEL", "google/gemini-2.5-flash-lite")
        api_key = os.environ.get("LLM_API_KEY", "")
        _instance = LLMClient(url, model, api_key)
    return _instance
