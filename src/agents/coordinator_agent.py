from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.state import TriageState
from src.tools import run_deterministic_triage


class CoordinatorInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    incident_dir: str | Path
    trace_dir: str | Path | None = None


def run_coordinator(input_data: CoordinatorInput) -> TriageState:
    return run_deterministic_triage(
        input_data.incident_dir,
        trace_dir=input_data.trace_dir,
    )


def initialize_triage_state(input_data: CoordinatorInput) -> TriageState:
    from src.tools import load_incident_artifacts
    from src.tools.triage_runner import _metadata_from_incident_artifact  # type: ignore

    artifacts = load_incident_artifacts(input_data.incident_dir)
    incident_art = artifacts.records.get("incident.json")
    metadata = _metadata_from_incident_artifact(incident_art)

    state = TriageState(metadata=metadata, artifacts=artifacts.records)
    return state


__all__ = ["CoordinatorInput", "initialize_triage_state", "run_coordinator"]
