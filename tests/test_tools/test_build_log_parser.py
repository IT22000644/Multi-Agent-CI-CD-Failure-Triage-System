from __future__ import annotations

from src.state import ArtifactRecord, ArtifactStatus, ArtifactType, FailureCategory
from src.tools import load_incident_artifacts, parse_build_and_test_logs


# Helper function to create a loaded artifact record for testing
def _loaded_artifact(
    name: str,
    artifact_type: ArtifactType,
    content: str,
) -> ArtifactRecord:
    return ArtifactRecord(
        name=name,
        artifact_type=artifact_type,
        status=ArtifactStatus.LOADED,
        path=f"/tmp/{name}",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )


# Test cases for the build and test log parser
def test_fixture_missing_env_var_is_detected() -> None:
    artifacts = load_incident_artifacts("fixtures/sample_incidents/incident_001")

    result = parse_build_and_test_logs(
        artifacts.records["build.log"],
        artifacts.records["test-report.txt"],
    )

    assert result.observed_failures
    assert result.observed_failures[0].category == FailureCategory.ENVIRONMENT_ISSUE
    assert result.findings
    assert any("DATABASE_URL is required" in item.snippet for item in result.evidence)


# Test that the parser can handle a build log with an environment variable issue even if the test report is missing
def test_parser_works_with_only_build_log() -> None:
    build_log = _loaded_artifact(
        "build.log",
        ArtifactType.LOG,
        "E       AssertionError: DATABASE_URL is required\n",
    )

    result = parse_build_and_test_logs(build_log)

    assert result.observed_failures
    assert result.observed_failures[0].category == FailureCategory.ENVIRONMENT_ISSUE


# Test that the parser returns empty results when the build log is missing or not loaded
def test_missing_build_log_returns_empty_result() -> None:
    result = parse_build_and_test_logs(None)

    assert result.observed_failures == []
    assert result.findings == []
    assert result.evidence == []


# Test that the parser returns empty results when the build log is not loaded (e.g., missing content)
def test_non_loaded_build_log_returns_empty_result() -> None:
    build_log = ArtifactRecord(
        name="build.log",
        artifact_type=ArtifactType.LOG,
        status=ArtifactStatus.MISSING,
        path=None,
        content=None,
        size_bytes=None,
    )

    result = parse_build_and_test_logs(build_log)

    assert result.observed_failures == []
    assert result.findings == []
    assert result.evidence == []


# Test that the parser can classify a dependency issue based on a common error message in the build log
def test_dependency_issue_classification() -> None:
    build_log = _loaded_artifact(
        "build.log",
        ArtifactType.LOG,
        "ERROR: Could not find a version that satisfies the requirement fake-package==99.0\n",
    )

    result = parse_build_and_test_logs(build_log)

    assert result.observed_failures
    assert result.observed_failures[0].category == FailureCategory.DEPENDENCY_ISSUE


# Test that the parser can classify a generic test failure based on an assertion error in the build log, even if it doesn't match a specific known pattern
def test_generic_test_failure_classification() -> None:
    build_log = _loaded_artifact(
        "build.log",
        ArtifactType.LOG,
        "FAILED tests/test_example.py::test_example - AssertionError\n",
    )

    result = parse_build_and_test_logs(build_log)

    assert result.observed_failures
    assert result.observed_failures[0].category == FailureCategory.TEST_FAILURE