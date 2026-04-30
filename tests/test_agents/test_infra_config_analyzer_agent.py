from __future__ import annotations

import pytest

from src.agents import (
    CoordinatorInput,
    InfraConfigAnalyzerInput,
    initialize_triage_state,
    run_infra_config_analyzer,
)
from src.state import FailureCategory, TriageState


def _initial_state() -> TriageState:
    return initialize_triage_state(
        CoordinatorInput(incident_dir="fixtures/sample_incidents/incident_001")
    )


def _evidence_supports_findings(state: TriageState) -> None:
    finding_ids = {
        f.finding_id for f in (state.config_findings + state.dependency_findings)
    }
    for item in state.evidence:
        if item.supports:
            assert item.supports in finding_ids


def test_infra_config_analyzer_populates_config_dependency_checks_and_evidence() -> None:
    state = _initial_state()
    updated = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))

    assert updated.config_findings
    assert updated.validated_checks
    assert updated.evidence
    assert any(
        item.location == "ollama.infra_config_interpretation"
        for item in updated.evidence
    )


def test_infra_config_analyzer_detects_missing_database_url() -> None:
    state = _initial_state()
    updated = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))

    found_env = False
    for f in updated.config_findings:
        if f.category == FailureCategory.ENVIRONMENT_ISSUE:
            found_env = True
            break

    # Also check evidence and finding text mentions DATABASE_URL
    mentions_db = any(
        "DATABASE_URL" in (e.snippet.upper()) for e in updated.evidence
    ) or any(
        "DATABASE_URL" in ((f.summary or "").upper() + (f.details or "").upper())
        for f in updated.config_findings
    )

    assert found_env
    assert mentions_db


def test_infra_config_analyzer_includes_docker_and_dependency_checks() -> None:
    state = _initial_state()
    updated = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))

    has_docker = any(
        "DOCKERFILE" in vc.summary.upper() for vc in updated.validated_checks
    )
    has_dependency = any(
        "DEPEND" in vc.summary.upper() or "REQUIRE" in vc.summary.upper()
        for vc in updated.validated_checks
    )

    assert has_docker or has_dependency


def test_infra_config_analyzer_does_not_mutate_input_state() -> None:
    state = _initial_state()
    original_evidence = list(state.evidence)

    assert state.config_findings == []
    assert state.dependency_findings == []
    assert state.validated_checks == []

    updated = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))

    # original remains unchanged
    assert state.config_findings == []
    assert state.dependency_findings == []
    assert state.validated_checks == []
    assert state.evidence == original_evidence

    # updated gained data
    assert updated.config_findings
    assert updated.validated_checks
    assert len(updated.evidence) > len(original_evidence)


def test_infra_config_analyzer_evidence_supports_existing_findings() -> None:
    state = _initial_state()
    updated = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))

    _evidence_supports_findings(updated)


def test_infra_config_analyzer_records_llm_interpretation(monkeypatch) -> None:
    from src.agents import infra_config_analyzer_agent

    calls: list[str] = []

    def fake_generate(prompt, config=None):
        calls.append(prompt)
        return (
            '{"config_interpretation": '
            '"DATABASE_URL is absent from the CI environment configuration.", '
            '"risk_summary": "Pytest will fail without database configuration.", '
            '"relevant_check_ids": [], '
            '"limitations": []}'
        )

    monkeypatch.setattr(infra_config_analyzer_agent, "generate_with_ollama", fake_generate)

    state = _initial_state()
    updated = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))

    assert calls
    llm_evidence = [
        item
        for item in updated.evidence
        if item.location == "ollama.infra_config_interpretation"
    ]
    assert llm_evidence
    assert "DATABASE_URL" in llm_evidence[0].snippet
    assert llm_evidence[0].supports == updated.config_findings[0].finding_id
    assert llm_evidence[0].evidence_id in updated.config_findings[0].evidence_ids


def test_infra_config_analyzer_malformed_json_raises(monkeypatch) -> None:
    from src.agents import infra_config_analyzer_agent

    def bad_generate(prompt, config=None):
        return "not json"

    monkeypatch.setattr(infra_config_analyzer_agent, "generate_with_ollama", bad_generate)

    state = _initial_state()

    with pytest.raises(infra_config_analyzer_agent.InfraConfigAnalyzerOutputParseError):
        run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))


def test_infra_config_analyzer_ollama_failure_raises(monkeypatch) -> None:
    from src.agents import infra_config_analyzer_agent
    from src.llm.ollama_client import OllamaGenerationError

    def bad_generate(prompt, config=None):
        raise OllamaGenerationError("no connection")

    monkeypatch.setattr(infra_config_analyzer_agent, "generate_with_ollama", bad_generate)

    state = _initial_state()

    with pytest.raises(OllamaGenerationError):
        run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))
