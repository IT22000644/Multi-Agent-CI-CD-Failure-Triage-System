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


__all__ = ["CoordinatorInput", "run_coordinator"]
