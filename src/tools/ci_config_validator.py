from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml
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


class CIConfigValidationResult(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    validated_checks: list[ValidatedCheck] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def _is_loaded_ci_config(ci_config: ArtifactRecord | None) -> bool:
    return bool(ci_config and ci_config.status == ArtifactStatus.LOADED and ci_config.content)


def _next_ids(counter: dict[str, int], prefix: str) -> str:
    counter[prefix] = counter.get(prefix, 0) + 1
    return f"{prefix}-{counter[prefix]:03d}"


def _available_check(
    summary: str,
    passed: bool,
    details: str,
    counter: dict[str, int],
) -> ValidatedCheck:
    return ValidatedCheck(
        check_id=_next_ids(counter, "check-ci"),
        summary=summary,
        passed=passed,
        details=details,
        agent_name=AgentName.INFRA_CONFIG_ANALYZER,
    )


def _collect_env_vars(workflow: Mapping[str, Any]) -> dict[str, set[str]]:
    discovered: dict[str, set[str]] = {"top": set(), "jobs": set(), "steps": set()}

    top_env = workflow.get("env")
    if isinstance(top_env, Mapping):
        discovered["top"].update(str(key) for key in top_env.keys())

    jobs = workflow.get("jobs")
    if isinstance(jobs, Mapping):
        for job in jobs.values():
            if not isinstance(job, Mapping):
                continue
            job_env = job.get("env")
            if isinstance(job_env, Mapping):
                discovered["jobs"].update(str(key) for key in job_env.keys())
            steps = job.get("steps")
            if isinstance(steps, list):
                for step in steps:
                    if not isinstance(step, Mapping):
                        continue
                    step_env = step.get("env")
                    if isinstance(step_env, Mapping):
                        discovered["steps"].update(str(key) for key in step_env.keys())

    return discovered


def _workflow_env_summary(env_vars: dict[str, set[str]]) -> str:
    all_env_vars = sorted(set().union(*env_vars.values())) if any(env_vars.values()) else []
    if not all_env_vars:
        return "Discovered env vars: none"
    return f"Discovered env vars: {', '.join(all_env_vars)}"


def _append_finding(
    findings: list[Finding],
    counter: dict[str, int],
    category: FailureCategory,
    severity: FindingSeverity,
    summary: str,
    details: str,
    evidence_ids: list[str],
) -> str:
    finding_id = _next_ids(counter, "finding-ci")
    findings.append(
        Finding(
            finding_id=finding_id,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            category=category,
            severity=severity,
            summary=summary,
            details=details,
            evidence_ids=evidence_ids,
        )
    )
    return finding_id


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
    details: str,
) -> str:
    finding_id = _next_ids(counter, "finding-ci")
    evidence_id = _next_ids(counter, "ev-ci")

    evidence.append(
        EvidenceItem(
            evidence_id=evidence_id,
            artifact_name=artifact_name,
            artifact_type=artifact_type,
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
            category=category,
            severity=severity,
            summary=summary,
            details=details,
            evidence_ids=[evidence_id],
        )
    )

    return finding_id


def _append_evidence(
    evidence: list[EvidenceItem],
    counter: dict[str, int],
    artifact_name: str,
    artifact_type: ArtifactType | None,
    location: str,
    snippet: str,
    supports: str,
) -> str:
    evidence_id = _next_ids(counter, "ev-ci")
    evidence.append(
        EvidenceItem(
            evidence_id=evidence_id,
            artifact_name=artifact_name,
            artifact_type=artifact_type,
            location=location,
            snippet=snippet,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            supports=supports,
        )
    )
    return evidence_id


def validate_ci_config(
    ci_config: ArtifactRecord | None,
    required_env_vars: list[str] | None = None,
) -> CIConfigValidationResult:
    """Validate CI workflow YAML and surface grounded configuration findings."""

    required_env_vars = required_env_vars or ["DATABASE_URL"]
    counter: dict[str, int] = {}

    if not _is_loaded_ci_config(ci_config):
        return CIConfigValidationResult(
            validated_checks=[
                _available_check(
                    summary="CI config artifact availability check",
                    passed=False,
                    details="CI config was not available or was not loaded.",
                    counter=counter,
                )
            ]
        )

    try:
        parsed = yaml.safe_load(ci_config.content)
    except yaml.YAMLError as exc:
        evidence: list[EvidenceItem] = []
        findings: list[Finding] = []
        _append_finding_with_evidence(
            findings=findings,
            evidence=evidence,
            counter=counter,
            artifact_name=ci_config.name,
            artifact_type=ci_config.artifact_type,
            location="yaml parse",
            snippet=str(exc),
            category=FailureCategory.CI_CONFIG_ISSUE,
            severity=FindingSeverity.HIGH,
            summary="Invalid YAML in CI workflow configuration",
            details=f"The CI workflow YAML could not be parsed: {exc}",
        )
        return CIConfigValidationResult(
            findings=findings,
            evidence=evidence,
            validated_checks=[
                _available_check(
                    summary="YAML parsing has passed",
                    passed=False,
                    details=f"YAML parsing failed: {exc}",
                    counter=counter,
                )
            ],
        )

    if not isinstance(parsed, Mapping):
        evidence: list[EvidenceItem] = []
        findings: list[Finding] = []
        _append_finding_with_evidence(
            findings=findings,
            evidence=evidence,
            counter=counter,
            artifact_name=ci_config.name,
            artifact_type=ci_config.artifact_type,
            location="workflow root",
            snippet=f"Parsed YAML is not a mapping: {type(parsed).__name__}",
            category=FailureCategory.CI_CONFIG_ISSUE,
            severity=FindingSeverity.HIGH,
            summary="Invalid YAML in CI workflow configuration",
            details="The CI workflow YAML must parse into a mapping.",
        )
        return CIConfigValidationResult(
            findings=findings,
            evidence=evidence,
            validated_checks=[
                _available_check(
                    summary="YAML parsing has passed",
                    passed=False,
                    details="The parsed YAML was not a workflow mapping.",
                    counter=counter,
                )
            ],
        )

    findings: list[Finding] = []
    evidence: list[EvidenceItem] = []
    validated_checks: list[ValidatedCheck] = []

    validated_checks.append(
        _available_check(
            summary="YAML parsing has passed",
            passed=True,
            details="CI workflow YAML parsed successfully.",
            counter=counter,
        )
    )

    env_vars = _collect_env_vars(parsed)
    workflow_env_summary = _workflow_env_summary(env_vars)

    missing_required_envs: list[str] = []
    for env_var in required_env_vars:
        if (
            env_var not in env_vars["top"]
            and env_var not in env_vars["jobs"]
            and env_var not in env_vars["steps"]
        ):
            missing_required_envs.append(env_var)
    if missing_required_envs:
        missing_list = ", ".join(missing_required_envs)
        finding_summary = (
            f"CI workflow does not configure required environment variable {missing_list}"
        )
        finding_details = (
            "The workflow defines environment variables but does not include "
            f"{missing_list}."
        )
        _append_finding_with_evidence(
            findings=findings,
            evidence=evidence,
            counter=counter,
            artifact_name=ci_config.name,
            artifact_type=ci_config.artifact_type,
            location="workflow env scan",
            snippet=workflow_env_summary,
            category=FailureCategory.ENVIRONMENT_ISSUE,
            severity=FindingSeverity.HIGH,
            summary=finding_summary,
            details=finding_details,
        )
        validated_checks.append(
            _available_check(
                summary="Required environment variables are configured",
                passed=False,
                details=f"Missing required env vars: {', '.join(missing_required_envs)}",
                counter=counter,
            )
        )
    else:
        validated_checks.append(
            _available_check(
                summary="Required environment variables are configured",
                passed=True,
                details=f"Required env vars found: {', '.join(required_env_vars)}",
                counter=counter,
            )
        )

    jobs = parsed.get("jobs")
    if not isinstance(jobs, Mapping) or not jobs:
        _append_finding_with_evidence(
            findings=findings,
            evidence=evidence,
            counter=counter,
            artifact_name=ci_config.name,
            artifact_type=ci_config.artifact_type,
            location="workflow jobs",
            snippet="Workflow does not define any jobs.",
            category=FailureCategory.CI_CONFIG_ISSUE,
            severity=FindingSeverity.MEDIUM,
            summary="CI workflow does not define any jobs",
            details="The workflow YAML is missing a jobs mapping.",
        )
        validated_checks.append(
            _available_check(
                summary="Workflow defines jobs",
                passed=False,
                details="No jobs were found in the CI workflow.",
                counter=counter,
            )
        )
    else:
        validated_checks.append(
            _available_check(
                summary="Workflow defines jobs",
                passed=True,
                details=f"Found {len(jobs)} job(s) in the CI workflow.",
                counter=counter,
            )
        )

        job_without_steps: list[str] = []
        test_command_found = False

        for job_name, job in jobs.items():
            if not isinstance(job, Mapping):
                continue

            steps = job.get("steps")
            if not isinstance(steps, list) or not steps:
                job_without_steps.append(str(job_name))
                continue

            for step in steps:
                if not isinstance(step, Mapping):
                    continue
                run_command = str(step.get("run", ""))
                lowered = run_command.lower()
                if (
                    "pytest" in lowered
                    or "python -m pytest" in lowered
                    or "npm test" in lowered
                    or "mvn test" in lowered
                    or "gradle test" in lowered
                ):
                    test_command_found = True

        if job_without_steps:
            _append_finding_with_evidence(
                findings=findings,
                evidence=evidence,
                counter=counter,
                artifact_name=ci_config.name,
                artifact_type=ci_config.artifact_type,
                location="workflow jobs.steps",
                snippet=f"Jobs without steps: {', '.join(sorted(job_without_steps))}",
                category=FailureCategory.CI_CONFIG_ISSUE,
                severity=FindingSeverity.MEDIUM,
                summary="CI workflow has jobs with no steps",
                details="At least one job does not define any executable steps.",
            )
            validated_checks.append(
                _available_check(
                    summary="All jobs define steps",
                    passed=False,
                    details=f"Jobs without steps: {', '.join(sorted(job_without_steps))}",
                    counter=counter,
                )
            )
        else:
            validated_checks.append(
                _available_check(
                    summary="All jobs define steps",
                    passed=True,
                    details="Every job has at least one step.",
                    counter=counter,
                )
            )

        if not test_command_found:
            _append_finding_with_evidence(
                findings=findings,
                evidence=evidence,
                counter=counter,
                artifact_name=ci_config.name,
                artifact_type=ci_config.artifact_type,
                location="workflow steps",
                snippet="No test command found in workflow steps.",
                category=FailureCategory.CI_CONFIG_ISSUE,
                severity=FindingSeverity.MEDIUM,
                summary="CI workflow does not run a test command",
                details="No step run command contains pytest, npm test, mvn test, or gradle test.",
            )
            validated_checks.append(
                _available_check(
                    summary="Workflow runs a test command",
                    passed=False,
                    details="No test command was detected in workflow steps.",
                    counter=counter,
                )
            )
        else:
            validated_checks.append(
                _available_check(
                    summary="Workflow runs a test command",
                    passed=True,
                    details="A test command was detected in the workflow.",
                    counter=counter,
                )
            )

    return CIConfigValidationResult(
        findings=findings,
        evidence=evidence,
        validated_checks=validated_checks,
    )


__all__ = ["CIConfigValidationResult", "validate_ci_config"]