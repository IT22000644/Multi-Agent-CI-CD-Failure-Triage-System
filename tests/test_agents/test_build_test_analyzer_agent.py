from __future__ import annotations

import pytest

from src.agents import (
    BuildTestAnalyzerInput,
    CoordinatorInput,
    initialize_triage_state,
    run_build_test_analyzer,
)
from src.state import FailureCategory, TriageState


def _initial_state() -> TriageState:
    return initialize_triage_state(
        CoordinatorInput(incident_dir="fixtures/sample_incidents/incident_001")
    )


def _assert_evidence_supports_existing_findings(state: TriageState) -> None:
    finding_ids = {finding.finding_id for finding in state.build_test_findings}
    for item in state.evidence:
        if item.supports:
            assert item.supports in finding_ids


def test_build_test_analyzer_populates_failures_findings_and_evidence() -> None:
    state = _initial_state()
    updated = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))

    assert updated.observed_failures
    assert updated.build_test_findings
    assert updated.evidence


def test_build_test_analyzer_detects_environment_issue() -> None:
    state = _initial_state()
    updated = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))

    has_env = any(
        (f.category == FailureCategory.ENVIRONMENT_ISSUE) for f in updated.build_test_findings
    ) or any((of.category == FailureCategory.ENVIRONMENT_ISSUE) for of in updated.observed_failures)
    assert has_env


def test_build_test_analyzer_does_not_mutate_input_state() -> None:
    state = _initial_state()
    original_evidence = list(state.evidence)

    # ensure original analyzer-owned fields are empty
    assert state.observed_failures == []
    assert state.build_test_findings == []

    updated = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))

    # original analyzer-owned fields are unchanged
    assert state.observed_failures == []
    assert state.build_test_findings == []
    assert state.evidence == original_evidence

    # updated has values
    assert updated.observed_failures
    assert updated.build_test_findings
    assert len(updated.evidence) > len(original_evidence)


def test_build_test_analyzer_evidence_supports_existing_findings() -> None:
    state = _initial_state()
    updated = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))

    _assert_evidence_supports_existing_findings(updated)


def test_build_test_analyzer_records_llm_interpretation(monkeypatch) -> None:
    from src.agents import build_test_analyzer_agent

    calls: list[str] = []

    def fake_generate(prompt, config=None):
        calls.append(prompt)
        return (
            '{"failure_interpretation": "DATABASE_URL is missing during the test run.", '
            '"likely_failure_mode": "environment_issue", '
            '"relevant_evidence_ids": [], '
            '"limitations": []}'
        )

    monkeypatch.setattr(build_test_analyzer_agent, "generate_with_ollama", fake_generate)

    state = _initial_state()
    updated = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))

    assert calls
    llm_evidence = [
        item
        for item in updated.evidence
        if item.location == "ollama.semantic_interpretation"
    ]
    assert llm_evidence
    assert "DATABASE_URL" in llm_evidence[0].snippet
    assert llm_evidence[0].supports == updated.build_test_findings[0].finding_id
    assert llm_evidence[0].evidence_id in updated.build_test_findings[0].evidence_ids


def test_build_test_analyzer_malformed_json_raises(monkeypatch) -> None:
    from src.agents import build_test_analyzer_agent

    def bad_generate(prompt, config=None):
        return "not json"

    monkeypatch.setattr(build_test_analyzer_agent, "generate_with_ollama", bad_generate)

    state = _initial_state()

    with pytest.raises(build_test_analyzer_agent.BuildTestAnalyzerOutputParseError):
        run_build_test_analyzer(BuildTestAnalyzerInput(state=state))


def test_build_test_analyzer_ollama_failure_raises(monkeypatch) -> None:
    from src.agents import build_test_analyzer_agent
    from src.llm.ollama_client import OllamaGenerationError

    def bad_generate(prompt, config=None):
        raise OllamaGenerationError("no connection")

    monkeypatch.setattr(build_test_analyzer_agent, "generate_with_ollama", bad_generate)

    state = _initial_state()

    with pytest.raises(OllamaGenerationError):
        run_build_test_analyzer(BuildTestAnalyzerInput(state=state))
