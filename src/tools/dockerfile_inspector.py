from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.state import (
    AgentName,
    ArtifactRecord,
    ArtifactStatus,
    ArtifactType,
    EvidenceItem,
    FailureCategory,
    Finding,
    FindingSeverity,
    ValidatedCheck,
)


class DockerfileInspectionResult(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    validated_checks: list[ValidatedCheck] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def _next_ids(counter: dict[str, int], prefix: str) -> str:
    counter[prefix] = counter.get(prefix, 0) + 1
    return f"{prefix}-{counter[prefix]:03d}"


def _append_finding_with_evidence(
    findings: list[Finding],
    evidence: list[EvidenceItem],
    counter: dict[str, int],
    artifact_name: str,
    location: str,
    snippet: str,
    severity: FindingSeverity,
    summary: str,
    details: str,
) -> str:
    finding_id = _next_ids(counter, "finding-docker")
    evidence_id = _next_ids(counter, "ev-docker")

    evidence.append(
        EvidenceItem(
            evidence_id=evidence_id,
            artifact_name=artifact_name,
            artifact_type=ArtifactType.DOCKERFILE,
            location=location,
            snippet=snippet,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            supports=finding_id,
        )
    )
    findings.append(
        Finding(
            finding_id=finding_id,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            category=FailureCategory.INFRASTRUCTURE_ISSUE,
            severity=severity,
            summary=summary,
            details=details,
            evidence_ids=[evidence_id],
        )
    )
    return finding_id


def _check(
    counter: dict[str, int],
    summary: str,
    passed: bool,
    details: str,
) -> ValidatedCheck:
    return ValidatedCheck(
        check_id=_next_ids(counter, "check-docker"),
        summary=summary,
        passed=passed,
        details=details,
        agent_name=AgentName.INFRA_CONFIG_ANALYZER,
    )


def inspect_dockerfile(
    dockerfile: ArtifactRecord | None,
) -> DockerfileInspectionResult:
    counter: dict[str, int] = {}
    findings: list[Finding] = []
    evidence: list[EvidenceItem] = []
    validated_checks: list[ValidatedCheck] = []

    if dockerfile is None:
        validated_checks.append(
            _check(
                counter,
                summary="Dockerfile artifact available",
                passed=False,
                details="No Dockerfile artifact was provided.",
            )
        )
        return DockerfileInspectionResult(
            findings=findings,
            evidence=evidence,
            validated_checks=validated_checks,
        )

    if dockerfile.artifact_type != ArtifactType.DOCKERFILE:
        validated_checks.append(
            _check(
                counter,
                summary="Dockerfile artifact available",
                passed=False,
                details="The provided artifact is not a Dockerfile.",
            )
        )
        return DockerfileInspectionResult(
            findings=findings,
            evidence=evidence,
            validated_checks=validated_checks,
        )

    if dockerfile.status != ArtifactStatus.LOADED or not dockerfile.content:
        validated_checks.append(
            _check(
                counter,
                summary="Dockerfile artifact available",
                passed=False,
                details=f"Dockerfile status is {dockerfile.status}.",
            )
        )
        return DockerfileInspectionResult(
            findings=findings,
            evidence=evidence,
            validated_checks=validated_checks,
        )

    lines = dockerfile.content.splitlines()
    has_from = False
    has_workdir = False
    has_cmd = False
    has_entrypoint = False
    install_seen = False
    copy_before_install = False

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        upper = line.upper()
        lower = line.lower()

        if not line or line.startswith("#"):
            continue

        if upper.startswith("FROM "):
            has_from = True
            base_image = line.split(None, 1)[1].strip()
            if base_image.endswith(":latest") or ":latest@" in base_image:
                _append_finding_with_evidence(
                    findings=findings,
                    evidence=evidence,
                    counter=counter,
                    artifact_name=dockerfile.name,
                    location=f"line {line_number}",
                    snippet=line,
                    severity=FindingSeverity.LOW,
                    summary="Dockerfile base image uses latest tag",
                    details="Using latest tags weakens reproducibility.",
                )
            continue

        if upper.startswith("WORKDIR "):
            has_workdir = True
            continue

        if upper.startswith("COPY "):
            if not install_seen and ("COPY . ." in line or line.endswith("COPY . .")):
                copy_before_install = True
            continue

        if upper.startswith("RUN "):
            if "pip install" in lower and "--no-cache-dir" not in lower:
                _append_finding_with_evidence(
                    findings=findings,
                    evidence=evidence,
                    counter=counter,
                    artifact_name=dockerfile.name,
                    location=f"line {line_number}",
                    snippet=line,
                    severity=FindingSeverity.LOW,
                    summary="Dockerfile pip install should use --no-cache-dir",
                    details=(
                        "Installing Python packages without --no-cache-dir "
                        "increases image size."
                    ),
                )
            if (
                "pip install" in lower
                or "poetry install" in lower
                or "uv pip install" in lower
            ):
                install_seen = True
            continue

        if upper.startswith("CMD "):
            has_cmd = True
            continue

        if upper.startswith("ENTRYPOINT "):
            has_entrypoint = True
            continue

    if not has_from:
        _append_finding_with_evidence(
            findings=findings,
            evidence=evidence,
            counter=counter,
            artifact_name=dockerfile.name,
            location="file",
            snippet="Missing FROM instruction",
            severity=FindingSeverity.HIGH,
            summary="Dockerfile is missing a FROM instruction",
            details="A Dockerfile must declare a base image with FROM.",
        )

    if not has_workdir:
        _append_finding_with_evidence(
            findings=findings,
            evidence=evidence,
            counter=counter,
            artifact_name=dockerfile.name,
            location="file",
            snippet="Missing WORKDIR instruction",
            severity=FindingSeverity.LOW,
            summary="Dockerfile is missing a WORKDIR instruction",
            details="Setting WORKDIR improves clarity and avoids implicit paths.",
        )

    if copy_before_install:
        _append_finding_with_evidence(
            findings=findings,
            evidence=evidence,
            counter=counter,
            artifact_name=dockerfile.name,
            location="file",
            snippet="COPY . . before dependency install",
            severity=FindingSeverity.LOW,
            summary="Dockerfile copies the full source tree before dependency install",
                details=(
                    "Copying the whole source tree before installing dependencies "
                    "can reduce Docker layer cache efficiency."
                ),
        )

    if not has_cmd and not has_entrypoint:
        _append_finding_with_evidence(
            findings=findings,
            evidence=evidence,
            counter=counter,
            artifact_name=dockerfile.name,
            location="file",
            snippet="Missing CMD or ENTRYPOINT",
            severity=FindingSeverity.MEDIUM,
            summary="Dockerfile is missing a default command",
            details="A runtime command should be declared with CMD or ENTRYPOINT.",
        )

    validated_checks.extend(
        [
            _check(
                counter,
                summary="Dockerfile artifact available",
                passed=True,
                details="Dockerfile artifact was loaded and inspected.",
            ),
            _check(
                counter,
                summary="Dockerfile has FROM",
                passed=has_from,
                details="FROM instruction found." if has_from else "FROM instruction not found.",
            ),
            _check(
                counter,
                summary="Dockerfile has WORKDIR",
                passed=has_workdir,
                details=(
                    "WORKDIR instruction found."
                    if has_workdir
                    else "WORKDIR instruction not found."
                ),
            ),
            _check(
                counter,
                summary="Dockerfile has CMD or ENTRYPOINT",
                passed=has_cmd or has_entrypoint,
                details="CMD or ENTRYPOINT found."
                if (has_cmd or has_entrypoint)
                else "Neither CMD nor ENTRYPOINT was found.",
            ),
            _check(
                counter,
                summary="Dockerfile inspection completed",
                passed=True,
                details="Dockerfile inspection finished successfully.",
            ),
        ]
    )

    return DockerfileInspectionResult(
        findings=findings,
        evidence=evidence,
        validated_checks=validated_checks,
    )


__all__ = ["DockerfileInspectionResult", "inspect_dockerfile"]
