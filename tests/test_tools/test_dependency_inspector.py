from __future__ import annotations

from src.state import ArtifactRecord, ArtifactStatus, ArtifactType, FindingSeverity
from src.tools import inspect_dependencies, load_incident_artifacts


def _assert_evidence_supports_existing_findings(result) -> None:
    finding_ids = {finding.finding_id for finding in result.findings}
    for item in result.evidence:
        if item.supports:
            assert item.supports in finding_ids


def test_fixture_requirements_file_passes() -> None:
    artifacts = load_incident_artifacts("fixtures/sample_incidents/incident_001")
    req = artifacts.records["requirements.txt"]

    result = inspect_dependencies([req])

    assert result.validated_checks
    # Should not contain medium/high findings for this fixture
    assert not any(
        f.severity in (FindingSeverity.MEDIUM, FindingSeverity.HIGH)
        for f in result.findings
    )
    assert any(check.passed for check in result.validated_checks)


def test_none_or_empty_returns_failed_check() -> None:
    result_none = inspect_dependencies(None)
    assert any(not check.passed for check in result_none.validated_checks)

    result_empty = inspect_dependencies([])
    assert any(not check.passed for check in result_empty.validated_checks)


def test_missing_not_loaded_artifact_returns_failed_loaded_check() -> None:
    art = ArtifactRecord(
        name="requirements.txt",
        artifact_type=ArtifactType.DEPENDENCY_FILE,
        status=ArtifactStatus.MISSING,
        path=None,
        content=None,
        size_bytes=None,
    )

    result = inspect_dependencies([art])

    assert any(not check.passed for check in result.validated_checks)


def test_unpinned_requirement_creates_low_finding() -> None:
    content = """pytest
pydantic>=2.8.0
"""
    art = ArtifactRecord(
        name="requirements.txt",
        artifact_type=ArtifactType.DEPENDENCY_FILE,
        status=ArtifactStatus.LOADED,
        path="/tmp/requirements.txt",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )

    result = inspect_dependencies([art])
    assert any(f.severity == FindingSeverity.LOW for f in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_malformed_requirement_creates_medium_finding() -> None:
    content = "not a valid requirement !!!\n"
    art = ArtifactRecord(
        name="requirements.txt",
        artifact_type=ArtifactType.DEPENDENCY_FILE,
        status=ArtifactStatus.LOADED,
        path="/tmp/requirements.txt",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )

    result = inspect_dependencies([art])
    assert any(f.severity == FindingSeverity.MEDIUM for f in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_invalid_package_json_creates_high_finding() -> None:
    content = "{ invalid json: }"
    art = ArtifactRecord(
        name="package.json",
        artifact_type=ArtifactType.DEPENDENCY_FILE,
        status=ArtifactStatus.LOADED,
        path="/tmp/package.json",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )

    result = inspect_dependencies([art])
    assert any(f.severity == FindingSeverity.HIGH for f in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_package_json_non_object_root_creates_high_finding() -> None:
    content = "[]"
    art = ArtifactRecord(
        name="package.json",
        artifact_type=ArtifactType.DEPENDENCY_FILE,
        status=ArtifactStatus.LOADED,
        path="/tmp/package.json",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )

    result = inspect_dependencies([art])

    assert any(f.severity == FindingSeverity.HIGH for f in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_risky_package_json_version_creates_low_finding() -> None:
    content = '{"dependencies": {"left-pad": "*"}}'
    art = ArtifactRecord(
        name="package.json",
        artifact_type=ArtifactType.DEPENDENCY_FILE,
        status=ArtifactStatus.LOADED,
        path="/tmp/package.json",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )

    result = inspect_dependencies([art])
    assert any(f.severity == FindingSeverity.LOW for f in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_invalid_pyproject_creates_high_finding() -> None:
    content = "[tool.poetry]\nname = \"myproj\n"
    art = ArtifactRecord(
        name="pyproject.toml",
        artifact_type=ArtifactType.DEPENDENCY_FILE,
        status=ArtifactStatus.LOADED,
        path="/tmp/pyproject.toml",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )

    result = inspect_dependencies([art])
    assert any(f.severity == FindingSeverity.HIGH for f in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_pyproject_optional_dependencies_unpinned_creates_low_finding() -> None:
    content = """[project]
name = "demo"
version = "0.1.0"

[project.optional-dependencies]
dev = ["pytest", "ruff>=0.6.0"]
"""
    art = ArtifactRecord(
        name="pyproject.toml",
        artifact_type=ArtifactType.DEPENDENCY_FILE,
        status=ArtifactStatus.LOADED,
        path="/tmp/pyproject.toml",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )

    result = inspect_dependencies([art])

    assert any(f.severity == FindingSeverity.LOW for f in result.findings)
    _assert_evidence_supports_existing_findings(result)
