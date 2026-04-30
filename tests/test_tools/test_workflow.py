from __future__ import annotations

import json
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
    trace_file = tmp_path / "incident_001.jsonl"
    assert trace_file.exists()

    events = [
        json.loads(line)
        for line in trace_file.read_text(encoding="utf-8").splitlines()
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "coordinator.incident_loaded",
        "build_test_analyzer.completed",
        "infra_config_analyzer.completed",
        "remediation_planner.completed",
        "workflow.complete",
    ]
    assert event_types == [event.event_type for event in state.trace_events]
    assert events[0]["metadata"]["artifact_count"] >= 1
    assert events[0]["metadata"]["llm_incident_context_evidence_count"] >= 1
    assert events[1]["metadata"]["observed_failure_count"] >= 1
    assert events[1]["metadata"]["llm_interpretation_evidence_count"] >= 1
    assert events[2]["metadata"]["validated_check_count"] >= 1
    assert events[2]["metadata"]["llm_interpretation_evidence_count"] >= 1
    assert events[3]["metadata"]["recommended_action_count"] >= 1
    assert events[4]["metadata"]["classification"] == "environment_issue"


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
