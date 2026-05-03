from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.llm import StructuredLLMOutputError, parse_llm_json_output
from src.llm.ollama_client import generate_with_ollama, load_ollama_config_from_env
from src.state import AgentName, ArtifactType, EvidenceItem, TriageState
from src.tools import (
    inspect_dependencies,
    inspect_dockerfile,
    validate_ci_config,
)
from src.tracing.trace_logger import record_trace_event
from src.tracing.trace_metadata import (
    ollama_response_summary,
    slm_state_context,
    summarize_ci_validation_result,
    summarize_dependency_result,
    summarize_dockerfile_result,
)


class InfraConfigAnalyzerInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    state: TriageState
    trace_dir: str | Path | None = None


class InfraConfigAnalyzerOutputParseError(RuntimeError):
    """Raised when the infra/config analyzer LLM response is not valid structured output."""


class InfraConfigAnalyzerLLMOutput(BaseModel):
    config_interpretation: str = Field(min_length=1)
    risk_summary: str | None = None
    relevant_check_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


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

    parts.append(
        "Return only valid JSON with this exact schema: "
        '{"config_interpretation": string, "risk_summary": string | null, '
        '"relevant_check_ids": string[], "limitations": string[]}.'
    )

    return "\n".join(parts)


def _parse_infra_config_llm_output(text: str) -> InfraConfigAnalyzerLLMOutput:
    try:
        return parse_llm_json_output(
            text,
            InfraConfigAnalyzerLLMOutput,
            context="Infra/config analyzer",
        )
    except StructuredLLMOutputError as exc:
        raise InfraConfigAnalyzerOutputParseError(
            f"Infra/config analyzer LLM output parse failed: {exc}"
        ) from exc


def _append_llm_interpretation_evidence(
    state: TriageState,
    output: InfraConfigAnalyzerLLMOutput,
) -> None:
    text = output.config_interpretation.strip()
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
    td = input_data.trace_dir

    ci_art = state.artifacts.get("ci.yml")
    docker_art = state.artifacts.get("Dockerfile")
    dep_artifacts = _collect_dependency_artifacts(state.artifacts)
    dep_names = [a.name for a in dep_artifacts]

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="infra_config_analyzer.input",
            message="Infra/config analyzer inputs",
            metadata={
                "has_ci_yml": ci_art is not None,
                "has_dockerfile": docker_art is not None,
                "dependency_artifact_names": dep_names,
            },
        )

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="tool.ci_config_validator.input",
            message="Validating CI workflow artifact",
            metadata={"artifact_names": ["ci.yml"] if ci_art else []},
        )

    ci_result = validate_ci_config(ci_art)

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="tool.ci_config_validator.output",
            message="CI configuration validation summarized",
            metadata=summarize_ci_validation_result(ci_result),
        )

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="tool.dockerfile_inspector.input",
            message="Inspecting Dockerfile artifact",
            metadata={"artifact_names": ["Dockerfile"] if docker_art else []},
        )

    docker_result = inspect_dockerfile(docker_art)

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="tool.dockerfile_inspector.output",
            message="Dockerfile inspection summarized",
            metadata=summarize_dockerfile_result(docker_result),
        )

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="tool.dependency_inspector.input",
            message="Inspecting dependency artifacts",
            metadata={"artifact_names": dep_names},
        )

    dependency_result = inspect_dependencies(dep_artifacts)

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="tool.dependency_inspector.output",
            message="Dependency inspection summarized",
            metadata=summarize_dependency_result(dependency_result),
        )

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
    cfg = load_ollama_config_from_env()
    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="ollama.infra_config_analyzer.request",
            message="SLM request for infra/config interpretation",
            metadata={
                "model": cfg.model,
                "prompt_character_count": len(prompt),
                "state_context": slm_state_context(state),
            },
        )

    raw_response = generate_with_ollama(prompt)
    interpretation = _parse_infra_config_llm_output(raw_response)

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="ollama.infra_config_analyzer.response",
            message="SLM response for infra/config analyzer",
            metadata=ollama_response_summary(interpretation, raw_text=raw_response),
        )

    _append_llm_interpretation_evidence(state, interpretation)

    if td is not None:
        findings = state.config_findings + state.dependency_findings
        record_trace_event(
            state,
            td,
            agent_name=AgentName.INFRA_CONFIG_ANALYZER,
            event_type="infra_config_analyzer.output",
            message="Infra/config analyzer finished",
            metadata={
                "config_finding_count": len(state.config_findings),
                "dependency_finding_count": len(state.dependency_findings),
                "validated_check_count": len(state.validated_checks),
                "finding_ids": [f.finding_id for f in findings],
                "classification_hints": sorted({f.category.value for f in findings}),
            },
        )

    return state


__all__ = [
    "InfraConfigAnalyzerInput",
    "InfraConfigAnalyzerLLMOutput",
    "InfraConfigAnalyzerOutputParseError",
    "run_infra_config_analyzer",
]
