from __future__ import annotations

from pathlib import Path

from src.graph import build_triage_workflow, run_triage_workflow
from src.state import TriageState


def test_workflow_runner_returns_populated_triage_state() -> None:
    state = run_triage_workflow("fixtures/sample_incidents/incident_001")

    assert isinstance(state, TriageState)
    assert state.metadata.incident_id == "incident_001"
    assert state.observed_failures
    assert state.build_test_findings


def test_workflow_supports_tracing(tmp_path: Path) -> None:
    state = run_triage_workflow(
        "fixtures/sample_incidents/incident_001",
        trace_dir=tmp_path,
    )

    assert state.trace_events
    assert (tmp_path / "incident_001.jsonl").exists()


def test_compiled_workflow_can_be_invoked_directly() -> None:
    app = build_triage_workflow()
    result = app.invoke(
        {
            "incident_dir": "fixtures/sample_incidents/incident_001",
        }
    )

    assert isinstance(result["triage_state"], TriageState)


def test_workflow_populates_full_pipeline() -> None:
    state = run_triage_workflow("fixtures/sample_incidents/incident_001")

    assert state.observed_failures
    assert state.build_test_findings
    assert state.config_findings
    assert state.validated_checks
    assert state.suspected_causes
    assert state.recommended_actions
    assert state.confidence_scores
    assert state.final_report is not None
