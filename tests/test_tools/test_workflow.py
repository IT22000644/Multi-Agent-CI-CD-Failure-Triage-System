from __future__ import annotations

import json
from pathlib import Path

from src.graph import build_triage_workflow, run_triage_workflow
from src.state import FailureCategory, TriageState


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

    raw_trace = trace_file.read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw_trace.splitlines()]
    types = [event["event_type"] for event in events]

    assert types[-2:] == ["state_consistency.output", "workflow.output"]
    assert types == [event.event_type for event in state.trace_events]

    required = {
        "coordinator.input",
        "coordinator.output",
        "tool.artifact_loader.input",
        "tool.artifact_loader.output",
        "build_test_analyzer.input",
        "tool.build_log_parser.input",
        "tool.build_log_parser.output",
        "ollama.build_test_analyzer.request",
        "ollama.build_test_analyzer.response",
        "build_test_analyzer.output",
        "infra_config_analyzer.input",
        "tool.ci_config_validator.input",
        "tool.ci_config_validator.output",
        "tool.dockerfile_inspector.input",
        "tool.dockerfile_inspector.output",
        "tool.dependency_inspector.input",
        "tool.dependency_inspector.output",
        "ollama.infra_config_analyzer.request",
        "ollama.infra_config_analyzer.response",
        "infra_config_analyzer.output",
        "remediation_planner.input",
        "ollama.remediation_planner.request",
        "ollama.remediation_planner.response",
        "remediation_planner.output",
        "state_consistency.input",
        "state_consistency.output",
        "workflow.output",
    }
    assert required.issubset(set(types))

    build_parser_out = next(
        e for e in events if e["event_type"] == "tool.build_log_parser.output"
    )
    meta = build_parser_out["metadata"]
    assert "finding_ids" in meta
    assert "evidence_ids" in meta
    assert meta["observed_failure_count"] >= 1

    coord_out = next(e for e in events if e["event_type"] == "coordinator.output")
    assert coord_out["metadata"]["incident_id"] == "incident_001"
    assert "artifact_names" in coord_out["metadata"]

    ollama_bt = next(e for e in events if e["event_type"] == "ollama.build_test_analyzer.request")
    assert "model" in ollama_bt["metadata"]
    assert ollama_bt["metadata"]["prompt_character_count"] >= 1
    assert "finding_count" in ollama_bt["metadata"]["state_context"]

    workflow_out = events[-1]
    assert workflow_out["metadata"]["classification"] == "environment_issue"
    assert workflow_out["metadata"]["state_consistency_passed"] is True

    distinctive_log_line = "test_database_url_is_configured"
    assert distinctive_log_line not in raw_trace


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


def test_workflow_handles_dependency_failure_fixture(tmp_path: Path) -> None:
    state = run_triage_workflow(
        "fixtures/sample_incidents/incident_002_dependency_failure",
        trace_dir=tmp_path,
    )

    assert state.metadata.incident_id == "incident_002_dependency_failure"
    assert any(
        failure.category == FailureCategory.DEPENDENCY_ISSUE
        for failure in state.observed_failures
    )
    assert any(
        finding.category == FailureCategory.DEPENDENCY_ISSUE
        for finding in state.build_test_findings + state.dependency_findings
    )
    assert state.final_report is not None
    assert state.final_report.failure_classification == FailureCategory.DEPENDENCY_ISSUE
    assert state.recommended_actions
    assert any(item.location == "ollama.incident_context" for item in state.evidence)
    assert any(item.location == "ollama.semantic_interpretation" for item in state.evidence)
    assert any(
        item.location == "ollama.infra_config_interpretation"
        for item in state.evidence
    )
    assert (tmp_path / "incident_002_dependency_failure.jsonl").exists()


def test_workflow_handles_ci_config_failure_fixture(tmp_path: Path) -> None:
    state = run_triage_workflow(
        "fixtures/sample_incidents/incident_003_ci_config_failure",
        trace_dir=tmp_path,
    )

    assert state.metadata.incident_id == "incident_003_ci_config_failure"
    assert any(
        finding.category == FailureCategory.CI_CONFIG_ISSUE
        for finding in state.config_findings
    )
    assert state.final_report is not None
    assert state.final_report.failure_classification == FailureCategory.CI_CONFIG_ISSUE
    assert state.recommended_actions
    assert any(item.location == "ollama.incident_context" for item in state.evidence)
    assert any(item.location == "ollama.semantic_interpretation" for item in state.evidence)
    assert any(
        item.location == "ollama.infra_config_interpretation"
        for item in state.evidence
    )
    assert (tmp_path / "incident_003_ci_config_failure.jsonl").exists()
