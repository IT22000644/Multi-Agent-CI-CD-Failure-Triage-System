from __future__ import annotations

from src.state import ArtifactRecord, ArtifactStatus, ArtifactType, FindingSeverity
from src.tools import inspect_dockerfile, load_incident_artifacts


def _assert_evidence_supports_existing_findings(result) -> None:
    finding_ids = {finding.finding_id for finding in result.findings}
    for item in result.evidence:
        if item.supports:
            assert item.supports in finding_ids


def _loaded_dockerfile(content: str) -> ArtifactRecord:
    return ArtifactRecord(
        name="Dockerfile",
        artifact_type=ArtifactType.DOCKERFILE,
        status=ArtifactStatus.LOADED,
        path="/tmp/Dockerfile",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )


def test_fixture_dockerfile_passes_basic_inspection() -> None:
    artifacts = load_incident_artifacts("fixtures/sample_incidents/incident_001")
    dockerfile = artifacts.records["Dockerfile"]

    result = inspect_dockerfile(dockerfile)

    assert result.validated_checks
    assert not any(finding.severity == FindingSeverity.HIGH for finding in result.findings)


def test_missing_dockerfile_returns_failed_check() -> None:
    result = inspect_dockerfile(None)

    assert result.findings == []
    assert any(not check.passed for check in result.validated_checks)


def test_non_dockerfile_artifact_returns_failed_check() -> None:
    art = ArtifactRecord(
        name="build.log",
        artifact_type=ArtifactType.LOG,
        status=ArtifactStatus.LOADED,
        path="/tmp/build.log",
        content="FROM python:3.12-slim\n",
        size_bytes=len(b"FROM python:3.12-slim\n"),
    )

    result = inspect_dockerfile(art)

    assert result.findings == []
    assert any(not check.passed for check in result.validated_checks)


def test_missing_from_creates_high_finding() -> None:
    result = inspect_dockerfile(
        _loaded_dockerfile(
            """WORKDIR /app
CMD ["python", "-m", "src.main"]
"""
        )
    )

    assert any(finding.severity == FindingSeverity.HIGH for finding in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_latest_base_image_creates_low_finding() -> None:
    result = inspect_dockerfile(
        _loaded_dockerfile(
            """FROM python:latest
WORKDIR /app
CMD ["python", "-m", "src.main"]
"""
        )
    )

    assert any(finding.severity == FindingSeverity.LOW for finding in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_missing_cmd_or_entrypoint_creates_medium_finding() -> None:
    result = inspect_dockerfile(
        _loaded_dockerfile(
            """FROM python:3.12-slim
WORKDIR /app
"""
        )
    )

    assert any(finding.severity == FindingSeverity.MEDIUM for finding in result.findings)
    _assert_evidence_supports_existing_findings(result)


def test_pip_install_without_no_cache_dir_creates_low_finding() -> None:
    result = inspect_dockerfile(
        _loaded_dockerfile(
            """FROM python:3.12-slim
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["python", "-m", "src.main"]
"""
        )
    )

    assert any(finding.severity == FindingSeverity.LOW for finding in result.findings)
    _assert_evidence_supports_existing_findings(result)
