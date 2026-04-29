from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph

from src.agents import (
    BuildTestAnalyzerInput,
    CoordinatorInput,
    InfraConfigAnalyzerInput,
    RemediationPlannerInput,
    initialize_triage_state,
    run_build_test_analyzer,
    run_infra_config_analyzer,
    run_remediation_planner,
)
from src.state import AgentName, TraceEvent, TriageState
from src.tracing.trace_logger import write_trace_events


class WorkflowState(TypedDict, total=False):
    incident_dir: str
    trace_dir: str | None
    triage_state: TriageState


def coordinator_node(state: WorkflowState) -> WorkflowState:
    coordinator_input = CoordinatorInput(
        incident_dir=state["incident_dir"],
        trace_dir=state.get("trace_dir"),
    )
    triage_state = initialize_triage_state(coordinator_input)

    # If tracing requested, emit a lightweight start event and persist it.
    trace_dir = state.get("trace_dir")
    if trace_dir:
        ev = TraceEvent(
            event_id=f"trace-{triage_state.metadata.incident_id}-001",
            agent_name=AgentName.COORDINATOR,
            event_type="workflow.start",
            message="Workflow initialized",
            metadata={"stage": "coordinator"},
        )
        write_trace_events(trace_dir, triage_state.metadata.incident_id, [ev])
        triage_state.trace_events = [ev]
    return {
        **state,
        "triage_state": triage_state,
    }


def build_test_analyzer_node(state: WorkflowState) -> WorkflowState:
    triage_state: TriageState = state["triage_state"]
    inp = BuildTestAnalyzerInput(state=triage_state)
    updated = run_build_test_analyzer(inp)
    return {**state, "triage_state": updated}


def infra_config_analyzer_node(state: WorkflowState) -> WorkflowState:
    triage_state: TriageState = state["triage_state"]
    inp = InfraConfigAnalyzerInput(state=triage_state)
    updated = run_infra_config_analyzer(inp)
    return {**state, "triage_state": updated}


def remediation_planner_node(state: WorkflowState) -> WorkflowState:
    triage_state: TriageState = state["triage_state"]
    inp = RemediationPlannerInput(state=triage_state)
    updated = run_remediation_planner(inp)
    return {**state, "triage_state": updated}


def build_triage_workflow():
    graph = StateGraph(WorkflowState)
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("build_test_analyzer", build_test_analyzer_node)
    graph.add_node("infra_config_analyzer", infra_config_analyzer_node)
    graph.add_node("remediation_planner", remediation_planner_node)
    # Connect nodes to form a linear pipeline
    graph.add_edge("coordinator", "build_test_analyzer")
    graph.add_edge("build_test_analyzer", "infra_config_analyzer")
    graph.add_edge("infra_config_analyzer", "remediation_planner")
    graph.set_entry_point("coordinator")
    graph.set_finish_point("remediation_planner")
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
