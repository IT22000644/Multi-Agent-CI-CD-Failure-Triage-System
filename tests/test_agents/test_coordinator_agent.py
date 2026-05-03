from __future__ import annotations

from pathlib import Path

import pytest

from src.agents import CoordinatorInput, coordinator_agent, initialize_triage_state, run_coordinator
from src.state import TriageState


def test_coordinator_returns_populated_triage_state() -> None:
    input_data = CoordinatorInput(
        incident_dir="fixtures/sample_incidents/incident_001",
    )

    state = run_coordinator(input_data)

    assert isinstance(state, TriageState)
    assert state.metadata.incident_id == "incident_001"
    assert state.observed_failures
    assert state.evidence
    assert any(item.location == "ollama.incident_context" for item in state.evidence)


def test_coordinator_supports_tracing(tmp_path: Path) -> None:
    input_data = CoordinatorInput(
        incident_dir="fixtures/sample_incidents/incident_001",
        trace_dir=tmp_path,
    )

    state = run_coordinator(input_data)

    assert state.trace_events
    assert (tmp_path / "incident_001.jsonl").exists()


def test_coordinator_propagates_invalid_path() -> None:
    input_data = CoordinatorInput(incident_dir="does-not-exist")

    with pytest.raises(FileNotFoundError):
        run_coordinator(input_data)


def test_coordinator_records_llm_incident_context(monkeypatch) -> None:
    from src.agents import coordinator_agent

    calls: list[str] = []

    def fake_generate(prompt, config=None):
        calls.append(prompt)
        return (
            '{"incident_context_summary": '
            '"Incident context summary from metadata and artifacts.", '
            '"notable_artifacts": ["incident.json"], '
            '"limitations": []}'
        )

    monkeypatch.setattr(coordinator_agent, "generate_with_ollama", fake_generate)

    state = run_coordinator(
        CoordinatorInput(incident_dir="fixtures/sample_incidents/incident_001")
    )

    assert calls
    context_evidence = [
        item for item in state.evidence if item.location == "ollama.incident_context"
    ]
    assert context_evidence
    assert "Incident context summary" in context_evidence[0].snippet


def test_coordinator_malformed_json_raises(monkeypatch) -> None:
    from src.agents import coordinator_agent
    from src.llm import StructuredLLMOutputError

    def bad_generate(prompt, config=None):
        return "not json"

    monkeypatch.setattr(coordinator_agent, "generate_with_ollama", bad_generate)

    with pytest.raises(coordinator_agent.CoordinatorOutputParseError) as excinfo:
        run_coordinator(
            CoordinatorInput(incident_dir="fixtures/sample_incidents/incident_001")
        )

    assert isinstance(excinfo.value.__cause__, StructuredLLMOutputError)


def test_initialize_triage_state_malformed_llm_json_raises_parse_error(monkeypatch) -> None:
    from src.llm import StructuredLLMOutputError

    monkeypatch.setattr(coordinator_agent, "generate_with_ollama", lambda *a, **k: "not json")

    with pytest.raises(coordinator_agent.CoordinatorOutputParseError) as excinfo:
        initialize_triage_state(
            CoordinatorInput(incident_dir="fixtures/sample_incidents/incident_001")
        )

    assert isinstance(excinfo.value.__cause__, StructuredLLMOutputError)


def test_coordinator_ollama_failure_raises(monkeypatch) -> None:
    from src.agents import coordinator_agent
    from src.llm.ollama_client import OllamaGenerationError

    def bad_generate(prompt, config=None):
        raise OllamaGenerationError("no connection")

    monkeypatch.setattr(coordinator_agent, "generate_with_ollama", bad_generate)

    with pytest.raises(OllamaGenerationError):
        run_coordinator(
            CoordinatorInput(incident_dir="fixtures/sample_incidents/incident_001")
        )
