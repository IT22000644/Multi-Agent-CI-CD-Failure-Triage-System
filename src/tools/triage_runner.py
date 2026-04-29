from __future__ import annotations

import json
from pathlib import Path

from src.state import ArtifactRecord, IncidentMetadata, TriageState
from src.tools import (
    inspect_dependencies,
    inspect_dockerfile,
    load_incident_artifacts,
    parse_build_and_test_logs,
    validate_ci_config,
)


def _metadata_from_incident_artifact(artifact: ArtifactRecord | None) -> IncidentMetadata:
    if not artifact or artifact.status != artifact.status.LOADED or not artifact.content:
        return IncidentMetadata(incident_id="unknown")

    try:
        parsed = json.loads(artifact.content)
    except Exception:
        return IncidentMetadata(incident_id="unknown")

    if not isinstance(parsed, dict):
        return IncidentMetadata(incident_id="unknown")

    incident_id = parsed.get("incident_id") or "unknown"
    return IncidentMetadata(
        incident_id=str(incident_id),
        title=parsed.get("title"),
        description=parsed.get("description"),
        repository=parsed.get("repository"),
        branch=parsed.get("branch"),
        commit_sha=parsed.get("commit_sha"),
        pipeline_name=parsed.get("pipeline_name"),
        run_id=parsed.get("run_id"),
    )


def _collect_dependency_artifacts(records: dict[str, ArtifactRecord]) -> list[ArtifactRecord]:
    deps = []
    for name in ("requirements.txt", "package.json", "pyproject.toml"):
        if name in records:
            deps.append(records[name])
    return deps


def run_deterministic_triage(incident_dir: str | Path) -> TriageState:
    artifacts = load_incident_artifacts(incident_dir)

    # Build metadata
    incident_art = artifacts.records.get("incident.json")
    metadata = _metadata_from_incident_artifact(incident_art)

    # Run build log parser
    build_log = artifacts.records.get("build.log")
    test_report = artifacts.records.get("test-report.txt")
    build_result = parse_build_and_test_logs(build_log, test_report)

    # CI config
    ci_art = artifacts.records.get("ci.yml")
    ci_result = validate_ci_config(ci_art)

    # Dependencies
    dep_artifacts = _collect_dependency_artifacts(artifacts.records)
    dependency_result = inspect_dependencies(dep_artifacts)

    # Dockerfile
    docker_art = artifacts.records.get("Dockerfile")
    docker_result = inspect_dockerfile(docker_art)

    # Combine findings
    build_findings = list(build_result.findings)
    config_findings = list(ci_result.findings) + list(docker_result.findings)
    dependency_findings = list(dependency_result.findings)

    all_findings = build_findings + config_findings + dependency_findings

    all_evidence = (
        list(build_result.evidence)
        + list(ci_result.evidence)
        + list(dependency_result.evidence)
        + list(docker_result.evidence)
    )

    # Runner-level integrity: ensure evidence.supports points to a real finding id
    finding_ids = {f.finding_id for f in all_findings}
    for ev in all_evidence:
        if ev.supports and ev.supports not in finding_ids:
            ev.supports = None

    validated_checks = (
        list(ci_result.validated_checks)
        + list(dependency_result.validated_checks)
        + list(docker_result.validated_checks)
    )

    state = TriageState(
        metadata=metadata,
        artifacts=artifacts.records,
        observed_failures=list(build_result.observed_failures),
        build_test_findings=build_findings,
        config_findings=config_findings,
        dependency_findings=dependency_findings,
        evidence=all_evidence,
        validated_checks=validated_checks,
    )

    return state


__all__ = ["run_deterministic_triage"]
