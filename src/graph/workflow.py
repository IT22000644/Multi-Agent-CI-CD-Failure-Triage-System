from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph

from src.agents import CoordinatorInput, run_coordinator
from src.state import TriageState


class WorkflowState(TypedDict, total=False):
    incident_dir: str
    trace_dir: str | None
    triage_state: TriageState


def coordinator_node(state: WorkflowState) -> WorkflowState:
    coordinator_input = CoordinatorInput(
        incident_dir=state["incident_dir"],
        trace_dir=state.get("trace_dir"),
    )
    triage_state = run_coordinator(coordinator_input)
    return {
        **state,
        "triage_state": triage_state,
    }


def build_triage_workflow():
    graph = StateGraph(WorkflowState)
    graph.add_node("coordinator", coordinator_node)
    graph.set_entry_point("coordinator")
    graph.set_finish_point("coordinator")
    return graph.compile()


def run_triage_workflow(
    incident_dir: str | Path,
    trace_dir: str | Path | None = None,
) -> TriageState:
    app = build_triage_workflow()
    result = app.invoke(
        {
            "incident_dir": str(incident_dir),
            "trace_dir": str(trace_dir) if trace_dir is not None else None,
        }
    )
    return result["triage_state"]


__all__ = [
    "WorkflowState",
    "build_triage_workflow",
    "coordinator_node",
    "run_triage_workflow",
]
