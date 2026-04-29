from __future__ import annotations

from pathlib import Path

import pytest

from src.agents import CoordinatorInput, run_coordinator
from src.state import TriageState


def test_coordinator_returns_populated_triage_state() -> None:
    input_data = CoordinatorInput(
        incident_dir="fixtures/sample_incidents/incident_001",
    )

    state = run_coordinator(input_data)

    assert isinstance(state, TriageState)
    assert state.metadata.incident_id == "incident_001"
    assert state.observed_failures
    assert state.evidence


def test_coordinator_supports_tracing(tmp_path: Path) -> None:
    input_data = CoordinatorInput(
        incident_dir="fixtures/sample_incidents/incident_001",
        trace_dir=tmp_path,
    )

    state = run_coordinator(input_data)

    assert state.trace_events
    assert (tmp_path / "incident_001.jsonl").exists()


def test_coordinator_propagates_invalid_path() -> None:
    input_data = CoordinatorInput(incident_dir="does-not-exist")

    with pytest.raises(FileNotFoundError):
        run_coordinator(input_data)
