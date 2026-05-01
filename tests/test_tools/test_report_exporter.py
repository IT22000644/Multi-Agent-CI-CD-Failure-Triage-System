from __future__ import annotations

import json
from pathlib import Path

from src.agents import (
    BuildTestAnalyzerInput,
    CoordinatorInput,
    InfraConfigAnalyzerInput,
    RemediationPlannerInput,
    initialize_triage_state,
    run_build_test_analyzer,
    run_infra_config_analyzer,
    run_remediation_planner,
)
from src.reporting import ReportExportResult, export_report
from src.state import FailureCategory


def _completed_state():
    state = initialize_triage_state(
        CoordinatorInput(incident_dir="fixtures/sample_incidents/incident_001")
    )
    state = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))
    state = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))
    return run_remediation_planner(RemediationPlannerInput(state=state))


def test_export_report_writes_json_and_markdown(tmp_path: Path) -> None:
    state = _completed_state()
    trace_file = tmp_path / "incident_001.jsonl"
    trace_file.write_text("{}\n", encoding="utf-8")

    result = export_report(state, tmp_path / "reports", trace_file=trace_file)

    assert isinstance(result, ReportExportResult)
    assert result.incident_id == "incident_001"
    assert result.summary_json_path.exists()
    assert result.markdown_report_path.exists()


def test_export_report_json_contains_structured_state(tmp_path: Path) -> None:
    state = _completed_state()

    result = export_report(state, tmp_path)
    payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert payload["incident_id"] == "incident_001"
    assert payload["classification"] == "environment_issue"
    assert payload["state"]["metadata"]["incident_id"] == "incident_001"
    assert payload["state"]["recommended_actions"]


def test_export_report_markdown_contains_triage_sections(tmp_path: Path) -> None:
    state = _completed_state()

    result = export_report(state, tmp_path, trace_file="traces/incident_001.jsonl")
    markdown = result.markdown_report_path.read_text(encoding="utf-8")

    assert "# CI/CD Failure Triage Report: incident_001" in markdown
    assert "## Classification" in markdown
    assert "environment_issue" in markdown
    assert "## Evidence" in markdown
    assert "## Recommended Actions" in markdown
    assert "traces/incident_001.jsonl" in markdown


def test_export_report_supports_dependency_failure_fixture(tmp_path: Path) -> None:
    state = initialize_triage_state(
        CoordinatorInput(
            incident_dir="fixtures/sample_incidents/incident_002_dependency_failure"
        )
    )
    state = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))
    state = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))
    state = run_remediation_planner(RemediationPlannerInput(state=state))

    assert state.final_report is not None
    assert state.final_report.failure_classification == FailureCategory.DEPENDENCY_ISSUE

    result = export_report(state, tmp_path)
    markdown = result.markdown_report_path.read_text(encoding="utf-8")
    payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert "incident_002_dependency_failure" in markdown
    assert "dependency_issue" in markdown
    assert payload["classification"] == "dependency_issue"


def test_export_report_supports_ci_config_failure_fixture(tmp_path: Path) -> None:
    state = initialize_triage_state(
        CoordinatorInput(
            incident_dir="fixtures/sample_incidents/incident_003_ci_config_failure"
        )
    )
    state = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))
    state = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))
    state = run_remediation_planner(RemediationPlannerInput(state=state))

    assert state.final_report is not None
    assert state.final_report.failure_classification == FailureCategory.CI_CONFIG_ISSUE

    result = export_report(state, tmp_path)
    markdown = result.markdown_report_path.read_text(encoding="utf-8")
    payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert "incident_003_ci_config_failure" in markdown
    assert "ci_config_issue" in markdown
    assert payload["classification"] == "ci_config_issue"
