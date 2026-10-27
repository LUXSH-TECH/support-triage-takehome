import os
from dataclasses import dataclass
from typing import Protocol

import httpx


class ModelError(Exception):
    pass


class ModelTimeout(ModelError, TimeoutError):
    pass


@dataclass(frozen=True)
class DraftContext:
    """Everything the model sees. The raw customer message is deliberately NOT included,
    so customer text can't inject instructions into the prompt."""
    retailer: str
    decision: str
    next_action: str
    safe_reply: str
    excerpts: tuple


class ModelProvider(Protocol):
    name: str

    def draft(self, ctx: DraftContext) -> str: ...


class FakeProvider:
    """Deterministic: returns the engine's own safe wording. Used by all tests."""
    name = "fake"

    def draft(self, ctx: DraftContext) -> str:
        return ctx.safe_reply


class HttpChatProvider:
    """Any OpenAI-compatible /chat/completions endpoint (OpenAI, Azure OpenAI, Ollama, ...).
    NOTE: not exercised in the automated tests - needs a real endpoint."""
    name = "http"

    def __init__(self, base_url: str, model: str, api_key: str | None, timeout_s: float):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout_s)
        self._model = model

    def draft(self, ctx: DraftContext) -> str:
        system = (
            f"You write short customer-support replies for the retailer '{ctx.retailer}'. "
            "Use ONLY the facts given. Max 3 sentences and 400 characters. "
            "Never promise a refund, replacement or exception. Never mention other retailers."
        )
        user = (f"Decision: {ctx.decision}\nInternal next action: {ctx.next_action}\n"
                f"Policy evidence: {' '.join(ctx.excerpts)}\nRewrite this reply politely, same meaning: {ctx.safe_reply}")
        try:
            r = self._client.post("/chat/completions", json={
                "model": self._model, "temperature": 0, "max_tokens": 150,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            })
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException as e:
            raise ModelTimeout(str(e)) from e
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise ModelError(str(e)) from e


def build_provider(provider: str, timeout_s: float) -> ModelProvider:
    if provider == "fake":
        return FakeProvider()
    if provider == "http":
        return HttpChatProvider(os.environ["LLM_BASE_URL"], os.environ["LLM_MODEL"],
                                os.getenv("LLM_API_KEY"), timeout_s)
    raise ValueError(f"unknown MODEL_PROVIDER: {provider}")