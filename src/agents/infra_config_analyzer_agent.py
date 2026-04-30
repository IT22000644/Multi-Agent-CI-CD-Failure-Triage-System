from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.llm.ollama_client import generate_with_ollama
from src.state import AgentName, ArtifactType, EvidenceItem, TriageState
from src.tools import (
    inspect_dependencies,
    inspect_dockerfile,
    validate_ci_config,
)


class InfraConfigAnalyzerInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    state: TriageState


def _collect_dependency_artifacts(records: dict[str, object]):
    deps = []
    for name in ("requirements.txt", "package.json", "pyproject.toml"):
        if name in records:
            deps.append(records[name])
    return deps


def _build_infra_config_interpretation_prompt(state: TriageState) -> str:
    parts: list[str] = [
        "Analyze these deterministic CI infrastructure and configuration findings.",
        "Return a concise semantic interpretation of configuration risk and likely impact.",
        "Do not invent artifact names, IDs, secrets, or unsupported remediations.",
    ]

    ci_artifact = state.artifacts.get("ci.yml")
    if ci_artifact and ci_artifact.content:
        parts.append("CI config excerpt:")
        parts.append(ci_artifact.content[:4000])

    docker_artifact = state.artifacts.get("Dockerfile")
    if docker_artifact and docker_artifact.content:
        parts.append("Dockerfile excerpt:")
        parts.append(docker_artifact.content[:2000])

    findings = state.config_findings + state.dependency_findings
    if findings:
        parts.append("Detected infra/config/dependency findings:")
        for finding in findings:
            parts.append(
                f"- {finding.finding_id}: {finding.category.value}: {finding.summary}"
            )

    if state.validated_checks:
        parts.append("Validated checks:")
        for check in state.validated_checks[:20]:
            parts.append(f"- {check.check_id}: {check.summary} (passed={check.passed})")

    return "\n".join(parts)


def _append_llm_interpretation_evidence(state: TriageState, interpretation: str) -> None:
    text = interpretation.strip()
    if not text:
        return

    findings = state.config_findings + state.dependency_findings
    supports = findings[0].finding_id if findings else None
    evidence_id = f"evidence-infra-config-llm-{len(state.evidence) + 1:03d}"
    evidence = EvidenceItem(
        evidence_id=evidence_id,
        artifact_name="ci.yml",
        artifact_type=ArtifactType.WORKFLOW_YAML,
        location="ollama.infra_config_interpretation",
        snippet=f"LLM_INFRA_CONFIG_INTERPRETATION: {text}",
        agent_name=AgentName.INFRA_CONFIG_ANALYZER,
        supports=supports,
    )
    state.evidence.append(evidence)

    if supports:
        findings[0].evidence_ids.append(evidence_id)


def run_infra_config_analyzer(input_data: InfraConfigAnalyzerInput) -> TriageState:
    state = input_data.state.model_copy(deep=True)

    ci_art = state.artifacts.get("ci.yml")
    docker_art = state.artifacts.get("Dockerfile")
    dep_artifacts = _collect_dependency_artifacts(state.artifacts)

    ci_result = validate_ci_config(ci_art)
    docker_result = inspect_dockerfile(docker_art)
    dependency_result = inspect_dependencies(dep_artifacts)

    state.config_findings = list(ci_result.findings) + list(docker_result.findings)
    state.dependency_findings = list(dependency_result.findings)
    state.evidence = (
        list(state.evidence)
        + list(ci_result.evidence)
        + list(dependency_result.evidence)
        + list(docker_result.evidence)
    )
    state.validated_checks = (
        list(state.validated_checks)
        + list(ci_result.validated_checks)
        + list(dependency_result.validated_checks)
        + list(docker_result.validated_checks)
    )

    prompt = _build_infra_config_interpretation_prompt(state)
    interpretation = generate_with_ollama(prompt)
    _append_llm_interpretation_evidence(state, interpretation)

    return state


__all__ = ["InfraConfigAnalyzerInput", "run_infra_config_analyzer"]
