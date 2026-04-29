from __future__ import annotations

import json
from pathlib import Path

from src.state import (
    AgentName,
    ArtifactRecord,
    ArtifactStatus,
    IncidentMetadata,
    TraceEvent,
    TriageState,
)
from src.tools import (
    inspect_dependencies,
    inspect_dockerfile,
    load_incident_artifacts,
    parse_build_and_test_logs,
    validate_ci_config,
)
from src.tracing import write_trace_events


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


def _make_trace_event(
    index: int,
    event_type: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> TraceEvent:
    return TraceEvent(
        event_id=f"trace-{index:03d}",
        agent_name=AgentName.COORDINATOR,
        event_type=event_type,
        message=message,
        metadata=metadata or {},
    )


def run_deterministic_triage(
    incident_dir: str | Path,
    trace_dir: str | Path | None = None,
) -> TriageState:
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

    # Build trace events (do not write until state constructed)
    trace_events: list[TraceEvent] = []
    # 1. triage_started
    incident_id_for_trace = state.metadata.incident_id or "unknown"
    trace_events.append(
        _make_trace_event(
            1,
            "triage_started",
            "Deterministic triage started",
            {"incident_dir": str(incident_dir)},
        ),
    )

    # 2. artifacts_loaded
    loaded_count = sum(
        1
        for r in artifacts.records.values()
        if r.status == ArtifactStatus.LOADED
    )
    missing_count = sum(
        1
        for r in artifacts.records.values()
        if r.status == ArtifactStatus.MISSING
    )
    trace_events.append(
        _make_trace_event(
            2,
            "artifacts_loaded",
            "Artifacts loaded",
            {
                "artifact_count": len(artifacts.records),
                "loaded_count": loaded_count,
                "missing_count": missing_count,
            },
        )
    )

    # 3. build_logs_parsed
    trace_events.append(
        _make_trace_event(
            3,
            "build_logs_parsed",
            "Build and test logs parsed",
            {
                "observed_failure_count": len(build_result.observed_failures),
                "finding_count": len(build_result.findings),
                "evidence_count": len(build_result.evidence),
            },
        )
    )

    # 4. ci_config_validated
    trace_events.append(
        _make_trace_event(
            4,
            "ci_config_validated",
            "CI configuration validated",
            {
                "finding_count": len(ci_result.findings),
                "evidence_count": len(ci_result.evidence),
                "validated_check_count": len(ci_result.validated_checks),
            },
        )
    )

    # 5. dependencies_inspected
    trace_events.append(
        _make_trace_event(
            5,
            "dependencies_inspected",
            "Dependencies inspected",
            {
                "dependency_artifact_count": len(dep_artifacts),
                "finding_count": len(dependency_result.findings),
                "evidence_count": len(dependency_result.evidence),
                "validated_check_count": len(dependency_result.validated_checks),
            },
        )
    )

    # 6. dockerfile_inspected
    trace_events.append(
        _make_trace_event(
            6,
            "dockerfile_inspected",
            "Dockerfile inspected",
            {
                "finding_count": len(docker_result.findings),
                "evidence_count": len(docker_result.evidence),
                "validated_check_count": len(docker_result.validated_checks),
            },
        )
    )

    # 7. triage_state_created
    trace_events.append(
        _make_trace_event(
            7,
            "triage_state_created",
            "Triage state created",
            {
                "observed_failure_count": len(state.observed_failures),
                "build_test_finding_count": len(state.build_test_findings),
                "config_finding_count": len(state.config_findings),
                "dependency_finding_count": len(state.dependency_findings),
                "evidence_count": len(state.evidence),
                "validated_check_count": len(state.validated_checks),
            },
        )
    )

    # If tracing enabled, write events and attach to state
    if trace_dir is not None:
        write_trace_events(trace_dir, incident_id_for_trace, trace_events)
        state.trace_events = trace_events

    return state


__all__ = ["run_deterministic_triage"]
