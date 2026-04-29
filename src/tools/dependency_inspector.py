from __future__ import annotations

import json
import re
import tomllib

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
    ValidatedCheck,
)


class DependencyInspectionResult(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    validated_checks: list[ValidatedCheck] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


_REQUIREMENT_RE = re.compile(
    r"^[A-Za-z0-9_.+-]+(\s*(==|~=|>=|<=|>|<)\s*[^,\s]+)?(\s*,\s*[^\s].*)?$"
)
_VERSION_OPERATOR_RE = re.compile(r"(==|~=|>=|<=|>|<)")


def _next_ids(counter: dict[str, int], prefix: str) -> str:
    counter[prefix] = counter.get(prefix, 0) + 1
    return f"{prefix}-{counter[prefix]:03d}"


def _has_version_operator(value: str) -> bool:
    return bool(_VERSION_OPERATOR_RE.search(value))


def _append_finding_with_evidence(
    findings: list[Finding],
    evidence: list[EvidenceItem],
    counter: dict[str, int],
    artifact_name: str,
    artifact_type: ArtifactType | None,
    location: str,
    snippet: str,
    category: FailureCategory,
    severity: FindingSeverity,
    summary: str,
    details: str | None = None,
) -> str:
    finding_id = _next_ids(counter, "finding-dep")
    evidence_id = _next_ids(counter, "ev-dep")

    evidence.append(
        EvidenceItem(
            evidence_id=evidence_id,
            artifact_name=artifact_name,
            artifact_type=artifact_type,
            location=location,
            snippet=snippet,
            agent_name=AgentName.BUILD_TEST_ANALYZER,
            supports=finding_id,
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
            evidence_ids=[evidence_id],
        )
    )

    return finding_id


def inspect_dependencies(
    dependency_artifacts: list[ArtifactRecord] | None,
) -> DependencyInspectionResult:
    counter: dict[str, int] = {}
    findings: list[Finding] = []
    evidence: list[EvidenceItem] = []
    validated_checks: list[ValidatedCheck] = []

    # Check: artifacts provided
    if not dependency_artifacts:
        validated_checks.append(
            ValidatedCheck(
                check_id=_next_ids(counter, "check-dep"),
                summary="Dependency artifacts provided",
                passed=False,
                details="No dependency artifacts were provided to the inspector.",
                agent_name=AgentName.BUILD_TEST_ANALYZER,
            )
        )
        return DependencyInspectionResult(
            findings=findings, evidence=evidence, validated_checks=validated_checks
        )

    validated_checks.append(
        ValidatedCheck(
            check_id=_next_ids(counter, "check-dep"),
            summary="Dependency artifacts provided",
            passed=True,
            details=f"Found {len(dependency_artifacts)} artifact(s) for inspection.",
            agent_name=AgentName.BUILD_TEST_ANALYZER,
        )
    )

    # Filter dependency file artifacts
    dep_artifacts = [
        artifact
        for artifact in dependency_artifacts
        if artifact.artifact_type == ArtifactType.DEPENDENCY_FILE
    ]

    if not dep_artifacts:
        validated_checks.append(
            ValidatedCheck(
                check_id=_next_ids(counter, "check-dep"),
                summary="Dependency artifacts loaded",
                passed=False,
                details="No artifacts of type DEPENDENCY_FILE were present.",
                agent_name=AgentName.BUILD_TEST_ANALYZER,
            )
        )
        return DependencyInspectionResult(
            findings=findings, evidence=evidence, validated_checks=validated_checks
        )

    validated_checks.append(
        ValidatedCheck(
            check_id=_next_ids(counter, "check-dep"),
            summary="Dependency artifacts loaded",
            passed=True,
            details=f"Found {len(dep_artifacts)} dependency file(s).",
            agent_name=AgentName.BUILD_TEST_ANALYZER,
        )
    )

    # Parse each artifact
    for art in dep_artifacts:
        name = art.name
        if art.status != ArtifactStatus.LOADED or not art.content:
            validated_checks.append(
                ValidatedCheck(
                    check_id=_next_ids(counter, "check-dep"),
                    summary=f"Artifact {name} is loaded",
                    passed=False,
                    details=f"Artifact {name} has status {art.status}.",
                    agent_name=AgentName.BUILD_TEST_ANALYZER,
                )
            )
            continue

        # file-type branch by name
        if name.endswith("requirements.txt"):
            # parse requirements
            malformed = []
            unpinned = []
            for idx, raw in enumerate(art.content.splitlines(), start=1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("-"):
                    # option like -r base.txt; ignore for now
                    continue
                if not _REQUIREMENT_RE.match(line):
                    malformed.append((idx, line))
                    continue
                # detect unpinned (no operator present)
                if not _has_version_operator(line):
                    unpinned.append((idx, line))

            # checks
            parsed_ok = not malformed
            validated_checks.append(
                ValidatedCheck(
                    check_id=_next_ids(counter, "check-dep"),
                    summary=f"Parsed requirements.txt {name}",
                    passed=parsed_ok,
                    details=(
                        "Parsed requirements.txt with no malformed lines."
                        if parsed_ok
                        else "Malformed lines found."
                    ),
                    agent_name=AgentName.BUILD_TEST_ANALYZER,
                )
            )

            if malformed:
                for idx, snippet in malformed:
                    _append_finding_with_evidence(
                        findings,
                        evidence,
                        counter,
                        artifact_name=name,
                        artifact_type=art.artifact_type,
                        location=f"line {idx}",
                        snippet=snippet,
                        category=FailureCategory.DEPENDENCY_ISSUE,
                        severity=FindingSeverity.MEDIUM,
                        summary="Malformed dependency entry in requirements.txt",
                        details=f"Line {idx} appears malformed: {snippet}",
                    )

            if unpinned:
                for idx, snippet in unpinned:
                    _append_finding_with_evidence(
                        findings,
                        evidence,
                        counter,
                        artifact_name=name,
                        artifact_type=art.artifact_type,
                        location=f"line {idx}",
                        snippet=snippet,
                        category=FailureCategory.DEPENDENCY_ISSUE,
                        severity=FindingSeverity.LOW,
                        summary="Unpinned dependency in requirements.txt",
                        details=f"Line {idx} is an unpinned requirement: {snippet}",
                    )

        elif name.endswith("package.json"):
            # json parse
            try:
                data = json.loads(art.content)
            except json.JSONDecodeError as exc:
                _append_finding_with_evidence(
                    findings,
                    evidence,
                    counter,
                    artifact_name=name,
                    artifact_type=art.artifact_type,
                    location="file",
                    snippet=str(exc),
                    category=FailureCategory.DEPENDENCY_ISSUE,
                    severity=FindingSeverity.HIGH,
                    summary="Invalid JSON in package.json",
                    details=str(exc),
                )
                validated_checks.append(
                    ValidatedCheck(
                        check_id=_next_ids(counter, "check-dep"),
                        summary=f"Parsed package.json {name}",
                        passed=False,
                        details="Invalid JSON.",
                        agent_name=AgentName.BUILD_TEST_ANALYZER,
                    )
                )
                continue

            if not isinstance(data, dict):
                _append_finding_with_evidence(
                    findings,
                    evidence,
                    counter,
                    artifact_name=name,
                    artifact_type=art.artifact_type,
                    location="root",
                    snippet=f"package.json root type: {type(data).__name__}",
                    category=FailureCategory.DEPENDENCY_ISSUE,
                    severity=FindingSeverity.HIGH,
                    summary="package.json root must be a JSON object",
                    details="The parsed package.json root value must be an object.",
                )
                validated_checks.append(
                    ValidatedCheck(
                        check_id=_next_ids(counter, "check-dep"),
                        summary=f"Parsed package.json {name}",
                        passed=False,
                        details="Parsed JSON is not an object.",
                        agent_name=AgentName.BUILD_TEST_ANALYZER,
                    )
                )
                continue

            validated_checks.append(
                ValidatedCheck(
                    check_id=_next_ids(counter, "check-dep"),
                    summary=f"Parsed package.json {name}",
                    passed=True,
                    details="Parsed JSON successfully.",
                    agent_name=AgentName.BUILD_TEST_ANALYZER,
                )
            )

            for section in ("dependencies", "devDependencies"):
                deps = data.get(section)
                if isinstance(deps, dict):
                    for pkg, val in deps.items():
                        if val == "":
                            _append_finding_with_evidence(
                                findings,
                                evidence,
                                counter,
                                artifact_name=name,
                                artifact_type=art.artifact_type,
                                location=f"{section}.{pkg}",
                                snippet=str(val),
                                category=FailureCategory.DEPENDENCY_ISSUE,
                                severity=FindingSeverity.MEDIUM,
                                summary=f"Empty version for {pkg} in package.json",
                                details=f"{section}.{pkg} is empty string.",
                            )
                        elif isinstance(val, str) and (
                            val.strip() == "*" or val.strip().lower() == "latest"
                        ):
                            _append_finding_with_evidence(
                                findings,
                                evidence,
                                counter,
                                artifact_name=name,
                                artifact_type=art.artifact_type,
                                location=f"{section}.{pkg}",
                                snippet=str(val),
                                category=FailureCategory.DEPENDENCY_ISSUE,
                                severity=FindingSeverity.LOW,
                                summary=f"Risky version specifier for {pkg} in package.json",
                                details=f"{section}.{pkg} uses non-specific version {val}.",
                            )

        elif name.endswith("pyproject.toml"):
            try:
                data = tomllib.loads(art.content)
            except Exception as exc:
                _append_finding_with_evidence(
                    findings,
                    evidence,
                    counter,
                    artifact_name=name,
                    artifact_type=art.artifact_type,
                    location="file",
                    snippet=str(exc),
                    category=FailureCategory.DEPENDENCY_ISSUE,
                    severity=FindingSeverity.HIGH,
                    summary="Invalid TOML in pyproject.toml",
                    details=str(exc),
                )
                validated_checks.append(
                    ValidatedCheck(
                        check_id=_next_ids(counter, "check-dep"),
                        summary=f"Parsed pyproject.toml {name}",
                        passed=False,
                        details="Invalid TOML.",
                        agent_name=AgentName.BUILD_TEST_ANALYZER,
                    )
                )
                continue

            validated_checks.append(
                ValidatedCheck(
                    check_id=_next_ids(counter, "check-dep"),
                    summary=f"Parsed pyproject.toml {name}",
                    passed=True,
                    details="Parsed TOML successfully.",
                    agent_name=AgentName.BUILD_TEST_ANALYZER,
                )
            )

            # project.dependencies
            project = data.get("project") or {}
            deps = project.get("dependencies") if isinstance(project, dict) else None
            if isinstance(deps, list):
                for idx, item in enumerate(deps, start=1):
                    # simple string dependency detection
                    if isinstance(item, str):
                        if not _has_version_operator(item):
                            _append_finding_with_evidence(
                                findings,
                                evidence,
                                counter,
                                artifact_name=name,
                                artifact_type=art.artifact_type,
                                location=f"project.dependencies[{idx}]",
                                snippet=item,
                                category=FailureCategory.DEPENDENCY_ISSUE,
                                severity=FindingSeverity.LOW,
                                summary="Unpinned dependency in pyproject.toml",
                                details=f"Entry {idx} appears unpinned: {item}",
                            )

            optional_deps = (
                project.get("optional-dependencies")
                if isinstance(project, dict)
                else None
            )
            if isinstance(optional_deps, dict):
                for group_name, group_deps in optional_deps.items():
                    if not isinstance(group_deps, list):
                        continue
                    for idx, item in enumerate(group_deps, start=1):
                        if isinstance(item, str) and not _has_version_operator(item):
                            _append_finding_with_evidence(
                                findings,
                                evidence,
                                counter,
                                artifact_name=name,
                                artifact_type=art.artifact_type,
                                location=(
                                    "project.optional-dependencies."
                                    f"{group_name}[{idx}]"
                                ),
                                snippet=item,
                                category=FailureCategory.DEPENDENCY_ISSUE,
                                severity=FindingSeverity.LOW,
                                summary=(
                                    "Unpinned optional dependency "
                                    "in pyproject.toml"
                                ),
                                details=(
                                    f"Optional dependency {group_name}[{idx}] "
                                    f"appears unpinned: {item}"
                                ),
                            )

            # tool.poetry.dependencies
            tool = data.get("tool") or {}
            poetry = tool.get("poetry") if isinstance(tool, dict) else None
            if isinstance(poetry, dict):
                poetry_deps = poetry.get("dependencies")
                if isinstance(poetry_deps, dict):
                    for pkg, val in poetry_deps.items():
                        if isinstance(val, str) and not _has_version_operator(val):
                            _append_finding_with_evidence(
                                findings,
                                evidence,
                                counter,
                                artifact_name=name,
                                artifact_type=art.artifact_type,
                                location=f"tool.poetry.dependencies.{pkg}",
                                snippet=str(val),
                                category=FailureCategory.DEPENDENCY_ISSUE,
                                severity=FindingSeverity.LOW,
                                summary="Unpinned dependency in pyproject.toml (poetry)",
                                details=f"{pkg} uses {val} which appears unpinned.",
                            )

        else:
            # unsupported file
            _append_finding_with_evidence(
                findings,
                evidence,
                counter,
                artifact_name=name,
                artifact_type=art.artifact_type,
                location="file",
                snippet="Unsupported dependency file type",
                category=FailureCategory.DEPENDENCY_ISSUE,
                severity=FindingSeverity.LOW,
                summary="Unsupported dependency file",
                details=f"File {name} is not a supported dependency manifest.",
            )

    return DependencyInspectionResult(
        findings=findings, evidence=evidence, validated_checks=validated_checks
    )


__all__ = ["DependencyInspectionResult", "inspect_dependencies"]
