from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.llm.ollama_client import generate_with_ollama
from src.state import AgentName, ArtifactType, EvidenceItem, TriageState
from src.tools import run_deterministic_triage


class CoordinatorInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    incident_dir: str | Path
    trace_dir: str | Path | None = None


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

    return "\n".join(parts)


def _append_incident_context_evidence(state: TriageState, context_summary: str) -> None:
    text = context_summary.strip()
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


def _add_incident_context_summary(state: TriageState) -> TriageState:
    prompt = _build_incident_context_prompt(state)
    context_summary = generate_with_ollama(prompt)
    _append_incident_context_evidence(state, context_summary)
    return state


def run_coordinator(input_data: CoordinatorInput) -> TriageState:
    state = run_deterministic_triage(
        input_data.incident_dir,
        trace_dir=input_data.trace_dir,
    )
    return _add_incident_context_summary(state)


def initialize_triage_state(input_data: CoordinatorInput) -> TriageState:
    from src.tools import load_incident_artifacts
    from src.tools.triage_runner import _metadata_from_incident_artifact  # type: ignore

    artifacts = load_incident_artifacts(input_data.incident_dir)
    incident_art = artifacts.records.get("incident.json")
    metadata = _metadata_from_incident_artifact(incident_art)

    state = TriageState(metadata=metadata, artifacts=artifacts.records)
    return _add_incident_context_summary(state)


__all__ = ["CoordinatorInput", "initialize_triage_state", "run_coordinator"]
