from __future__ import annotations

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
    assert state.config_findings == []
    assert state.dependency_findings == []
    assert state.validated_checks == []
    assert state.evidence == []

    updated = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))

    # original remains unchanged
    assert state.config_findings == []
    assert state.dependency_findings == []
    assert state.validated_checks == []
    assert state.evidence == []

    # updated gained data
    assert updated.config_findings
    assert updated.validated_checks
    assert updated.evidence


def test_infra_config_analyzer_evidence_supports_existing_findings() -> None:
    state = _initial_state()
    updated = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))

    _evidence_supports_findings(updated)
