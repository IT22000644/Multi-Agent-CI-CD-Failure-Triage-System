from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.llm import StructuredLLMOutputError, parse_llm_json_output
from src.llm.ollama_client import generate_with_ollama
from src.state import AgentName, ArtifactType, EvidenceItem, TriageState
from src.tools import run_deterministic_triage
from src.tools.artifact_loader import OPTIONAL_ARTIFACTS, REQUIRED_ARTIFACTS
from src.tracing.trace_logger import record_trace_event
from src.tracing.trace_metadata import summarize_artifacts


class CoordinatorInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    incident_dir: str | Path
    trace_dir: str | Path | None = None


class CoordinatorOutputParseError(RuntimeError):
    """Raised when the coordinator LLM response is not valid structured output."""


class CoordinatorLLMOutput(BaseModel):
    incident_context_summary: str = Field(min_length=1)
    notable_artifacts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _build_incident_context_prompt(state: TriageState) -> str:
    metadata = state.metadata
    parts: list[str] = [
        "Summarize the CI/CD incident context from the loaded metadata and artifacts.",
        "Do not invent missing details or root causes.",
        f"Incident ID: {metadata.incident_id}",
    ]

    if metadata.title:
        parts.append(f"Title: {metadata.title}")
    if metadata.description:
        parts.append(f"Description: {metadata.description}")
    if metadata.repository:
        parts.append(f"Repository: {metadata.repository}")
    if metadata.branch:
        parts.append(f"Branch: {metadata.branch}")
    if metadata.pipeline_name:
        parts.append(f"Pipeline: {metadata.pipeline_name}")
    if metadata.run_id:
        parts.append(f"Run ID: {metadata.run_id}")

    parts.append("Loaded artifacts:")
    for artifact in state.artifacts.values():
        parts.append(
            f"- {artifact.name}: "
            f"type={artifact.artifact_type.value}, status={artifact.status.value}"
        )

    parts.append(
        "Return only valid JSON with this exact schema: "
        '{"incident_context_summary": string, '
        '"notable_artifacts": string[], "limitations": string[]}.'
    )

    return "\n".join(parts)


def _parse_coordinator_llm_output(text: str) -> CoordinatorLLMOutput:
    try:
        return parse_llm_json_output(text, CoordinatorLLMOutput, context="Coordinator")
    except StructuredLLMOutputError as exc:
        raise CoordinatorOutputParseError(
            f"Coordinator LLM output parse failed: {exc}"
        ) from exc


def _append_incident_context_evidence(
    state: TriageState,
    output: CoordinatorLLMOutput,
) -> None:
    text = output.incident_context_summary.strip()
    if not text:
        return

    evidence = EvidenceItem(
        evidence_id=f"evidence-coordinator-llm-{len(state.evidence) + 1:03d}",
        artifact_name="incident.json",
        artifact_type=ArtifactType.OTHER,
        location="ollama.incident_context",
        snippet=f"LLM_INCIDENT_CONTEXT: {text}",
        agent_name=AgentName.COORDINATOR,
    )
    state.evidence.append(evidence)


def _add_incident_context_summary(
    state: TriageState,
    trace_dir: str | Path | None = None,
) -> TriageState:
    prompt = _build_incident_context_prompt(state)
    context_summary = _parse_coordinator_llm_output(generate_with_ollama(prompt))
    _append_incident_context_evidence(state, context_summary)
    return state


def run_coordinator(input_data: CoordinatorInput) -> TriageState:
    state = run_deterministic_triage(
        input_data.incident_dir,
        trace_dir=input_data.trace_dir,
    )
    return _add_incident_context_summary(state, trace_dir=input_data.trace_dir)


def initialize_triage_state(input_data: CoordinatorInput) -> TriageState:
    from src.tools import load_incident_artifacts
    from src.tools.triage_runner import _metadata_from_incident_artifact  # type: ignore

    td = input_data.trace_dir
    artifacts = load_incident_artifacts(input_data.incident_dir)
    incident_art = artifacts.records.get("incident.json")
    metadata = _metadata_from_incident_artifact(incident_art)

    state = TriageState(metadata=metadata, artifacts=artifacts.records)

    if td is not None:
        incident_path = Path(input_data.incident_dir)
        optional_attempted = sorted(
            name for name in OPTIONAL_ARTIFACTS if (incident_path / name).exists()
        )
        record_trace_event(
            state,
            td,
            agent_name=AgentName.COORDINATOR,
            event_type="coordinator.input",
            message="Coordinator received incident directory",
            metadata={"incident_dir": str(input_data.incident_dir)},
        )
        record_trace_event(
            state,
            td,
            agent_name=AgentName.COORDINATOR,
            event_type="tool.artifact_loader.input",
            message="Artifact loader targets",
            metadata={
                "artifact_names": sorted(REQUIRED_ARTIFACTS.keys()) + optional_attempted,
            },
        )
        record_trace_event(
            state,
            td,
            agent_name=AgentName.COORDINATOR,
            event_type="tool.artifact_loader.output",
            message="Artifacts loaded into triage state",
            metadata=summarize_artifacts(state),
        )

    return _add_incident_context_summary(state, trace_dir=td)


__all__ = [
    "CoordinatorInput",
    "CoordinatorLLMOutput",
    "CoordinatorOutputParseError",
    "initialize_triage_state",
    "run_coordinator",
]
