from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from scripts import evaluate_fixtures
from src.state import (
    AgentName,
    ArtifactType,
    EvidenceItem,
    FailureCategory,
    FinalReport,
    FindingSeverity,
    IncidentMetadata,
    RecommendedAction,
    TriageState,
)


class DummyReportExport(BaseModel):
    summary_json_path: Path
    markdown_report_path: Path


def _state(category: FailureCategory = FailureCategory.ENVIRONMENT_ISSUE) -> TriageState:
    action = RecommendedAction(
        action_id="action-001",
        summary="Fix incident",
        details="Do the thing.",
        risk_level=FindingSeverity.LOW,
        confidence=0.8,
        rank=1,
    )
    return TriageState(
        metadata=IncidentMetadata(incident_id="incident_test"),
        evidence=[
            EvidenceItem(
                evidence_id="ev-001",
                artifact_name="incident.json",
                artifact_type=ArtifactType.OTHER,
                location="ollama.incident_context",
                snippet="context",
                agent_name=AgentName.COORDINATOR,
            ),
            EvidenceItem(
                evidence_id="ev-002",
                artifact_name="build.log",
                artifact_type=ArtifactType.LOG,
                location="ollama.semantic_interpretation",
                snippet="build",
                agent_name=AgentName.BUILD_TEST_ANALYZER,
            ),
            EvidenceItem(
                evidence_id="ev-003",
                artifact_name="ci.yml",
                artifact_type=ArtifactType.WORKFLOW_YAML,
                location="ollama.infra_config_interpretation",
                snippet="config",
                agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            ),
        ],
        recommended_actions=[action],
        final_report=FinalReport(
            incident_id="incident_test",
            failure_classification=category,
            executive_summary="summary",
            root_cause_summary="root cause",
            recommended_actions=[action],
        ),
    )


def _write_fixture(root: Path, incident_id: str, expected_category: str) -> Path:
    fixture_dir = root / incident_id
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "incident.json").write_text(
        json.dumps(
            {
                "incident_id": incident_id,
                "expected_failure_category": expected_category,
            }
        ),
        encoding="utf-8",
    )
    return fixture_dir


def test_evaluate_fixture_passes_when_expected_category_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture_dir = _write_fixture(tmp_path, "incident_test", "environment_issue")

    def fake_run_workflow(fixture_dir, trace_dir=None):
        trace_file = Path(trace_dir) / "incident_test.jsonl"
        trace_file.parent.mkdir(parents=True, exist_ok=True)
        trace_file.write_text("{}\n", encoding="utf-8")
        return _state()

    def fake_export_report(state, report_root, trace_file=None):
        report_dir = Path(report_root) / state.metadata.incident_id
        report_dir.mkdir(parents=True, exist_ok=True)
        return DummyReportExport(
            summary_json_path=report_dir / "summary.json",
            markdown_report_path=report_dir / "report.md",
        )

    monkeypatch.setattr(evaluate_fixtures, "run_triage_workflow", fake_run_workflow)
    monkeypatch.setattr(evaluate_fixtures, "export_report", fake_export_report)

    result = evaluate_fixtures.evaluate_fixture(
        fixture_dir,
        trace_root=tmp_path / "traces",
        report_root=tmp_path / "reports",
    )

    assert result.passed
    assert result.actual_category == "environment_issue"
    assert result.errors == []


def test_evaluate_fixture_fails_on_classification_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture_dir = _write_fixture(tmp_path, "incident_test", "dependency_issue")

    def fake_run_workflow(fixture_dir, trace_dir=None):
        trace_file = Path(trace_dir) / "incident_test.jsonl"
        trace_file.parent.mkdir(parents=True, exist_ok=True)
        trace_file.write_text("{}\n", encoding="utf-8")
        return _state(FailureCategory.ENVIRONMENT_ISSUE)

    monkeypatch.setattr(evaluate_fixtures, "run_triage_workflow", fake_run_workflow)
    monkeypatch.setattr(
        evaluate_fixtures,
        "export_report",
        lambda state, report_root, trace_file=None: DummyReportExport(
            summary_json_path=Path(report_root) / "summary.json",
            markdown_report_path=Path(report_root) / "report.md",
        ),
    )

    result = evaluate_fixtures.evaluate_fixture(
        fixture_dir,
        trace_root=tmp_path / "traces",
        report_root=tmp_path / "reports",
    )

    assert not result.passed
    assert any("classification mismatch" in error for error in result.errors)


def test_main_prints_json_results(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_fixture(tmp_path, "incident_test", "environment_issue")

    def fake_evaluate_fixture(fixture_dir, trace_root, report_root):
        return evaluate_fixtures.FixtureEvaluation(
            incident_id="incident_test",
            fixture_dir=Path(fixture_dir),
            expected_category="environment_issue",
            actual_category="environment_issue",
            passed=True,
        )

    monkeypatch.setattr(evaluate_fixtures, "evaluate_fixture", fake_evaluate_fixture)

    exit_code = evaluate_fixtures.main(["--fixtures-root", str(tmp_path), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["incident_id"] == "incident_test"
    assert payload[0]["passed"] is True
