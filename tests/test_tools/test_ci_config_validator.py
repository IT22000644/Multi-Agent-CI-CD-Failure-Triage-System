from __future__ import annotations

from src.state import ArtifactRecord, ArtifactStatus, ArtifactType, FailureCategory
from src.tools import load_incident_artifacts, validate_ci_config


def _loaded_ci_config(content: str) -> ArtifactRecord:
    return ArtifactRecord(
        name="ci.yml",
        artifact_type=ArtifactType.WORKFLOW_YAML,
        status=ArtifactStatus.LOADED,
        path="/tmp/ci.yml",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )


def _assert_evidence_supports_existing_findings(result) -> None:
    finding_ids = {finding.finding_id for finding in result.findings}
    for item in result.evidence:
        if item.supports:
            assert item.supports in finding_ids


def test_fixture_missing_database_url_is_detected() -> None:
    artifacts = load_incident_artifacts("fixtures/sample_incidents/incident_001")

    result = validate_ci_config(artifacts.records["ci.yml"])

    assert result.findings
    assert any(finding.category == FailureCategory.ENVIRONMENT_ISSUE for finding in result.findings)
    assert any("PYTHONPATH" in item.snippet for item in result.evidence)
    found_in_findings = any(
        "DATABASE_URL" in finding.summary
        or (finding.details is not None and "DATABASE_URL" in finding.details)
        for finding in result.findings
    )
    found_in_evidence = any("DATABASE_URL" in item.snippet for item in result.evidence)
    assert found_in_findings or found_in_evidence
    _assert_evidence_supports_existing_findings(result)
    assert any(
        check.summary == "YAML parsing has passed" and check.passed
        for check in result.validated_checks
    )


def test_missing_ci_config_returns_failed_availability_check() -> None:
    result = validate_ci_config(None)

    assert result.findings == []
    assert result.evidence == []
    assert any(not check.passed for check in result.validated_checks)


def test_invalid_yaml_creates_ci_config_issue_finding() -> None:
    ci_config = _loaded_ci_config("name: ci\njobs: [\n")

    result = validate_ci_config(ci_config)

    assert any(finding.category == FailureCategory.CI_CONFIG_ISSUE for finding in result.findings)
    _assert_evidence_supports_existing_findings(result)
    assert any(not check.passed for check in result.validated_checks)


def test_workflow_with_database_url_passes_required_env_check() -> None:
    ci_config = _loaded_ci_config(
        """name: ci
env:
  DATABASE_URL: postgresql://localhost:5432/app
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Run tests
        run: pytest -q
"""
    )

    result = validate_ci_config(ci_config)

    found_env_issue = any(
        finding.category == FailureCategory.ENVIRONMENT_ISSUE
        for finding in result.findings
    )
    assert not found_env_issue
    assert any(
        check.summary == "Required environment variables are configured" and check.passed
        for check in result.validated_checks
    )


def test_missing_jobs_is_detected() -> None:
    ci_config = _loaded_ci_config(
        """name: ci
env:
  DATABASE_URL: postgresql://localhost:5432/app
"""
    )

    result = validate_ci_config(ci_config)

    assert any(finding.category == FailureCategory.CI_CONFIG_ISSUE for finding in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_no_test_command_is_detected() -> None:
    ci_config = _loaded_ci_config(
        """name: ci
env:
  DATABASE_URL: postgresql://localhost:5432/app
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Check formatting
        run: python -m compileall src
"""
    )

    result = validate_ci_config(ci_config)

    assert any(finding.category == FailureCategory.CI_CONFIG_ISSUE for finding in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_evidence_supports_points_to_existing_findings_for_missing_jobs_regression() -> None:
    ci_config = _loaded_ci_config(
        """name: ci
env:
  DATABASE_URL: postgresql://localhost:5432/app
"""
    )

    result = validate_ci_config(ci_config)

    assert any(finding.category == FailureCategory.CI_CONFIG_ISSUE for finding in result.findings)
    _assert_evidence_supports_existing_findings(result)