from __future__ import annotations

import importlib

import pytest

from src.llm.ollama_client import (
    OllamaConfig,
    OllamaGenerationError,
    generate_with_ollama,
    load_ollama_config_from_env,
)


def test_load_ollama_config_defaults(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)

    cfg = load_ollama_config_from_env()
    assert isinstance(cfg, OllamaConfig)
    assert cfg.base_url == "http://localhost:11434"
    assert cfg.model == "llama3.1"
    assert cfg.timeout_seconds == 30.0


def test_load_ollama_config_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "custom-model")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "12.5")

    cfg = load_ollama_config_from_env()
    assert cfg.base_url == "http://example:11434"
    assert cfg.model == "custom-model"
    assert cfg.timeout_seconds == 12.5


def test_load_ollama_config_invalid_timeout(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "not-a-number")
    cfg = load_ollama_config_from_env()
    assert cfg.timeout_seconds == 30.0


def test_generate_with_ollama_returns_content(monkeypatch):
    # Create a fake langchain_ollama module
    class FakeResp:
        def __init__(self, content=None):
            self.content = content

    class FakeChat:
        def __init__(self, model, base_url, timeout):
            pass

        def invoke(self, prompt):
            return FakeResp(content="LLM summary")

    fake_mod = type("m", (), {"ChatOllama": FakeChat})
    monkeypatch.setitem(importlib.sys.modules, "langchain_ollama", fake_mod)

    out = generate_with_ollama("hello")
    assert out == "LLM summary"


def test_generate_with_ollama_blank_prompt():
    with pytest.raises(ValueError):
        generate_with_ollama("")


def test_generate_with_ollama_string_response(monkeypatch):
    class FakeChat:
        def __init__(self, model, base_url, timeout):
            pass

        def invoke(self, prompt):
            return "plain string"

    fake_mod = type("m", (), {"ChatOllama": FakeChat})
    monkeypatch.setitem(importlib.sys.modules, "langchain_ollama", fake_mod)

    out = generate_with_ollama("hi")
    assert out == "plain string"


def test_generate_with_ollama_errors_wrapped(monkeypatch):
    class FakeChat:
        def __init__(self, model, base_url, timeout):
            pass

        def invoke(self, prompt):
            raise RuntimeError("boom")

    fake_mod = type("m", (), {"ChatOllama": FakeChat})
    monkeypatch.setitem(importlib.sys.modules, "langchain_ollama", fake_mod)

    with pytest.raises(OllamaGenerationError):
        generate_with_ollama("prompt")
