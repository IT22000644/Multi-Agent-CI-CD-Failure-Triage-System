from __future__ import annotations

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
    # ensure original is empty
    assert state.observed_failures == []
    assert state.build_test_findings == []
    assert state.evidence == []

    updated = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))

    # original still empty
    assert state.observed_failures == []
    assert state.build_test_findings == []
    assert state.evidence == []

    # updated has values
    assert updated.observed_failures
    assert updated.build_test_findings
    assert updated.evidence


def test_build_test_analyzer_evidence_supports_existing_findings() -> None:
    state = _initial_state()
    updated = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))

    _assert_evidence_supports_existing_findings(updated)
