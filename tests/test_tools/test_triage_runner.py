from __future__ import annotations

from pathlib import Path

import pytest

from src.state import FailureCategory, TriageState
from src.tools import run_deterministic_triage


def _assert_evidence_supports_existing_findings(state: TriageState) -> None:
    finding_ids = {
        finding.finding_id
        for finding in (
            state.build_test_findings
            + state.config_findings
            + state.dependency_findings
        )
    }
    for item in state.evidence:
        if item.supports:
            assert item.supports in finding_ids


def test_fixture_produces_populated_triage_state() -> None:
    state = run_deterministic_triage("fixtures/sample_incidents/incident_001")

    assert isinstance(state, TriageState)
    assert state.metadata.incident_id == "incident_001"
    assert "build.log" in state.artifacts
    assert state.observed_failures
    assert state.build_test_findings
    assert state.config_findings
    assert state.validated_checks
    assert state.evidence
    # Expect missing DATABASE_URL to be classified as environment issue
    assert any(
        (f.category == FailureCategory.ENVIRONMENT_ISSUE)
        for f in (
            state.build_test_findings + state.config_findings + state.dependency_findings
        )
    )
    _assert_evidence_supports_existing_findings(state)


def test_invalid_incident_json_falls_back_to_unknown(tmp_path: Path) -> None:
    d = tmp_path / "incident"
    d.mkdir()
    # create invalid incident.json
    (d / "incident.json").write_text("not a json")
    # add minimal required artifact
    (d / "build.log").write_text("")
    (d / "ci.yml").write_text("")

    state = run_deterministic_triage(str(d))
    assert state.metadata.incident_id == "unknown"


def test_missing_incident_dir_raises() -> None:
    with pytest.raises(FileNotFoundError):
        run_deterministic_triage("nonexistent_dir_12345")


def test_path_instead_of_dir_raises(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("")
    with pytest.raises(NotADirectoryError):
        run_deterministic_triage(str(f))


def test_no_trace_by_default() -> None:
    state = run_deterministic_triage("fixtures/sample_incidents/incident_001")
    assert state.trace_events == []


def test_tracing_writes_jsonl_and_populates_state(tmp_path: Path) -> None:
    state = run_deterministic_triage("fixtures/sample_incidents/incident_001", trace_dir=tmp_path)

    trace_file = tmp_path / "incident_001.jsonl"
    assert trace_file.exists()
    assert state.trace_events

    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 7

    import json as _json

    records = [_json.loads(line) for line in lines]
    types = [r.get("event_type") for r in records]
    assert types == [
        "triage_started",
        "artifacts_loaded",
        "build_logs_parsed",
        "ci_config_validated",
        "dependencies_inspected",
        "dockerfile_inspected",
        "triage_state_created",
    ]

    ids = [r.get("event_id") for r in records]
    assert ids == [f"trace-{i:03d}" for i in range(1, 8)]

    # metadata checks
    artifacts_loaded = records[1]
    assert artifacts_loaded.get("metadata", {}).get("artifact_count", 0) > 0

    triage_state_created = records[-1]
    assert triage_state_created.get("metadata", {}).get("evidence_count") == len(state.evidence)
