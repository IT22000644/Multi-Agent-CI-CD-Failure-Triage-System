from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field


class OllamaConfig(BaseModel):
    base_url: str = Field(default="http://localhost:11434")
    model: str = Field(default="llama3.1")
    timeout_seconds: float = Field(default=30.0, gt=0)


class OllamaGenerationError(RuntimeError):
    """Raised when Ollama generation or client initialization fails."""


def load_ollama_config_from_env() -> OllamaConfig:
    base = os.getenv("OLLAMA_BASE_URL")
    model = os.getenv("OLLAMA_MODEL")
    timeout_raw = os.getenv("OLLAMA_TIMEOUT_SECONDS")

    timeout = 30.0
    if timeout_raw:
        try:
            timeout = float(timeout_raw)
            if timeout <= 0:
                timeout = 30.0
        except Exception:
            timeout = 30.0

    return OllamaConfig(
        base_url=base or "http://localhost:11434",
        model=model or "llama3.1",
        timeout_seconds=timeout,
    )


def generate_with_ollama(prompt: str, config: OllamaConfig | None = None) -> str:
    if not prompt or not prompt.strip():
        raise ValueError("prompt must not be blank")

    cfg = config or load_ollama_config_from_env()

    try:
        # import here so tests can monkeypatch/replace the module easily
        from langchain_ollama import ChatOllama  # type: ignore

        llm = ChatOllama(
            model=cfg.model,
            base_url=cfg.base_url,
            timeout=cfg.timeout_seconds,
        )

        response: Any = llm.invoke(prompt)

        # Prefer `.content` attribute if present
        if hasattr(response, "content") and response.content is not None:
            return response.content

        if isinstance(response, str):
            return response

        return str(response)

    except Exception as exc:  # wrap all errors
        raise OllamaGenerationError(str(exc)) from exc
