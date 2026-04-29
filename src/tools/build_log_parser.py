from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from src.state import (
    AgentName,
    ArtifactRecord,
    ArtifactStatus,
    ArtifactType,
    EvidenceItem,
    FailureCategory,
    Finding,
    FindingSeverity,
    ObservedFailure,
)


class BuildLogParseResult(BaseModel):
    observed_failures: list[ObservedFailure] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


_CATEGORY_PRIORITY: dict[FailureCategory, int] = {
    FailureCategory.ENVIRONMENT_ISSUE: 4,
    FailureCategory.DEPENDENCY_ISSUE: 3,
    FailureCategory.TEST_FAILURE: 2,
    FailureCategory.INFRASTRUCTURE_ISSUE: 1,
}

_CATEGORY_MESSAGES: dict[FailureCategory, tuple[str, str, FindingSeverity]] = {
    FailureCategory.ENVIRONMENT_ISSUE: (
        "Pytest failed because DATABASE_URL is not configured",
        "CI ran pytest without evidence that DATABASE_URL was configured.",
        FindingSeverity.HIGH,
    ),
    FailureCategory.DEPENDENCY_ISSUE: (
        "Dependency installation failed during package resolution",
        "The log shows a dependency resolution problem during install or build.",
        FindingSeverity.MEDIUM,
    ),
    FailureCategory.TEST_FAILURE: (
        "Pytest reported a test failure or assertion error",
        "The log contains failing test output from pytest.",
        FindingSeverity.MEDIUM,
    ),
    FailureCategory.INFRASTRUCTURE_ISSUE: (
        "Build or Docker command failed",
        "The build log indicates a tooling or container build failure.",
        FindingSeverity.MEDIUM,
    ),
}


def _validate_artifact(artifact: ArtifactRecord | None, field_name: str) -> ArtifactRecord | None:
    if artifact is None:
        return None
    if not isinstance(artifact, ArtifactRecord):
        raise TypeError(f"{field_name} must be an ArtifactRecord or None")
    return artifact


def _is_loaded(artifact: ArtifactRecord | None) -> bool:
    return bool(artifact and artifact.status == ArtifactStatus.LOADED and artifact.content)


def _artifact_prefix(artifact: ArtifactRecord) -> str:
    if artifact.artifact_type == ArtifactType.TEST_REPORT:
        return "test"
    return "build"


def _classify_line(line: str) -> FailureCategory | None:
    normalized = line.lower()

    if (
        "database_url is required" in normalized
        or "environment variable" in normalized
        or "os.getenv" in normalized
        or "not configured" in normalized
    ):
        return FailureCategory.ENVIRONMENT_ISSUE

    if (
        "no matching distribution found" in normalized
        or "could not find a version that satisfies the requirement" in normalized
        or "modulenotfounderror" in normalized
        or "importerror" in normalized
    ):
        return FailureCategory.DEPENDENCY_ISSUE

    if (
        "returned a non-zero code" in normalized
        or "failed to solve" in normalized
        or "error: failed to build" in normalized
    ):
        return FailureCategory.INFRASTRUCTURE_ISSUE

    if (
        "failed" in normalized
        or "assertionerror" in normalized
        or "error" in normalized
        or "short test summary info" in normalized
    ):
        return FailureCategory.TEST_FAILURE

    return None


def _sort_categories(categories: set[FailureCategory]) -> list[FailureCategory]:
    return sorted(categories, key=lambda category: _CATEGORY_PRIORITY.get(category, 0), reverse=True)


def _scan_artifact(
    artifact: ArtifactRecord,
    evidence_start: int,
    evidence: list[EvidenceItem],
    category_evidence_ids: dict[FailureCategory, list[str]],
) -> tuple[set[FailureCategory], int]:
    detected_categories: set[FailureCategory] = set()
    prefix = _artifact_prefix(artifact)
    line_prefix = "test-report line" if prefix == "test" else "line"

    for line_number, line in enumerate(artifact.content.splitlines(), start=1):
        category = _classify_line(line)
        if category is None:
            continue

        detected_categories.add(category)
        evidence_id = f"ev-{prefix}-{evidence_start:03d}"
        evidence_start += 1
        evidence_item = EvidenceItem(
            evidence_id=evidence_id,
            artifact_name=artifact.name,
            artifact_type=artifact.artifact_type,
            location=f"{line_prefix} {line_number}",
            snippet=line.strip(),
            agent_name=AgentName.BUILD_TEST_ANALYZER,
            supports="",
        )
        evidence.append(evidence_item)
        category_evidence_ids.setdefault(category, []).append(evidence_id)

    return detected_categories, evidence_start


def _build_result(
    categories: set[FailureCategory],
    category_evidence_ids: dict[FailureCategory, list[str]],
) -> BuildLogParseResult:
    if not categories:
        return BuildLogParseResult()

    ordered_categories = _sort_categories(categories)
    observed_failures: list[ObservedFailure] = []
    findings: list[Finding] = []

    for index, category in enumerate(ordered_categories, start=1):
        summary, details, severity = _CATEGORY_MESSAGES.get(
            category,
            (
                "Build log contains a failure",
                "The build log contains an unclassified failure signal.",
                FindingSeverity.LOW,
            ),
        )
        finding_id = f"finding-build-{index:03d}"
        evidence_ids = category_evidence_ids.get(category, [])
        observed_failures.append(
            ObservedFailure(
                category=category,
                summary=summary if category != FailureCategory.ENVIRONMENT_ISSUE else "DATABASE_URL is missing or not configured in CI",
                source_artifact="build.log",
                evidence_ids=evidence_ids,
            )
        )
        findings.append(
            Finding(
                finding_id=finding_id,
                agent_name=AgentName.BUILD_TEST_ANALYZER,
                category=category,
                severity=severity,
                summary=summary,
                details=details,
                evidence_ids=evidence_ids,
            )
        )

    return BuildLogParseResult(observed_failures=observed_failures, findings=findings)


def parse_build_and_test_logs(
    build_log: ArtifactRecord | None,
    test_report: ArtifactRecord | None = None,
) -> BuildLogParseResult:
    """Parse CI logs into observed failures, findings, and evidence snippets."""

    build_log = _validate_artifact(build_log, "build_log")
    test_report = _validate_artifact(test_report, "test_report")

    if not _is_loaded(build_log):
        return BuildLogParseResult()

    evidence: list[EvidenceItem] = []
    category_evidence_ids: dict[FailureCategory, list[str]] = {}
    categories: set[FailureCategory] = set()

    detected_categories, _ = _scan_artifact(build_log, 1, evidence, category_evidence_ids)
    categories.update(detected_categories)

    if _is_loaded(test_report):
        detected_categories, _ = _scan_artifact(test_report, 1, evidence, category_evidence_ids)
        categories.update(detected_categories)

    if not categories:
        return BuildLogParseResult()

    result = _build_result(categories, category_evidence_ids)

    finding_lookup = {finding.category: finding.finding_id for finding in result.findings}
    for item in evidence:
        for category, evidence_ids in category_evidence_ids.items():
            if item.evidence_id in evidence_ids:
                item.supports = finding_lookup.get(category)
                break

    result.evidence = evidence
    return result


__all__ = ["BuildLogParseResult", "parse_build_and_test_logs"]