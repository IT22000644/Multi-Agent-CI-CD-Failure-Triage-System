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
from src.state import AgentName, TriageState
from src.tracing.trace_logger import record_trace_event

from src.tracing.trace_metadata import summarize_artifacts
from src.validation import apply_state_consistency_validation, validate_state_consistency


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

    trace_dir = state.get("trace_dir")
    if trace_dir:
        record_trace_event(
            triage_state,
            trace_dir,
            agent_name=AgentName.COORDINATOR,
            event_type="coordinator.output",
            message="Coordinator finished incident bootstrap",
            metadata={
                "incident_id": triage_state.metadata.incident_id,
                **summarize_artifacts(triage_state),
            },
        )

    return {
        **state,
        "triage_state": triage_state,
    }


def build_test_analyzer_node(state: WorkflowState) -> WorkflowState:
    triage_state: TriageState = state["triage_state"]
    inp = BuildTestAnalyzerInput(
        state=triage_state,
        trace_dir=state.get("trace_dir"),
    )
    updated = run_build_test_analyzer(inp)
    return {**state, "triage_state": updated}


def infra_config_analyzer_node(state: WorkflowState) -> WorkflowState:
    triage_state: TriageState = state["triage_state"]
    inp = InfraConfigAnalyzerInput(
        state=triage_state,
        trace_dir=state.get("trace_dir"),
    )
    updated = run_infra_config_analyzer(inp)
    return {**state, "triage_state": updated}


def remediation_planner_node(state: WorkflowState) -> WorkflowState:
    triage_state: TriageState = state["triage_state"]
    inp = RemediationPlannerInput(
        state=triage_state,
        trace_dir=state.get("trace_dir"),
    )
    updated = run_remediation_planner(inp)
    return {**state, "triage_state": updated}


def state_consistency_validator_node(state: WorkflowState) -> WorkflowState:
    
    triage_state: TriageState = state["triage_state"]
    trace_dir = state.get("trace_dir")

    if trace_dir:
        record_trace_event(
            triage_state,
            trace_dir,
            agent_name=None,
            event_type="state_consistency.input",
            message="Running cross-agent state consistency validation",
            metadata={
                "evidence_count": len(triage_state.evidence),
                "finding_count": len(
                    triage_state.build_test_findings
                    + triage_state.config_findings
                    + triage_state.dependency_findings
                ),
                "cause_count": len(triage_state.suspected_causes),
                "action_count": len(triage_state.recommended_actions),
            },
        )

    result = validate_state_consistency(triage_state)
    updated = apply_state_consistency_validation(triage_state)

    if trace_dir:
        record_trace_event(
            updated,
            trace_dir,
            agent_name=None,
            event_type="state_consistency.output",
            message="State consistency validation finished",
            metadata={
                "passed": result.passed,
                "error_count": len(result.errors),
                "warning_count": len(result.warnings),
            },
        )
        record_trace_event(
            updated,
            trace_dir,
            agent_name=None,
            event_type="workflow.output",
            message="Triage workflow completed",
            metadata={
                "classification": (
                    updated.final_report.failure_classification.value
                    if updated.final_report and updated.final_report.failure_classification
                    else None
                ),
                "has_final_report": updated.final_report is not None,
                "state_consistency_passed": result.passed,
            },
        )

    return {**state, "triage_state": updated}


def build_triage_workflow():
    graph = StateGraph(WorkflowState)
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("build_test_analyzer", build_test_analyzer_node)
    graph.add_node("infra_config_analyzer", infra_config_analyzer_node)
    graph.add_node("remediation_planner", remediation_planner_node)
    graph.add_node("state_consistency_validator", state_consistency_validator_node)
    graph.add_edge("coordinator", "build_test_analyzer")
    graph.add_edge("build_test_analyzer", "infra_config_analyzer")
    graph.add_edge("infra_config_analyzer", "remediation_planner")
    graph.add_edge("remediation_planner", "state_consistency_validator")
    graph.set_entry_point("coordinator")
    graph.set_finish_point("state_consistency_validator")
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
    "build_test_analyzer_node",
    "infra_config_analyzer_node",
    "remediation_planner_node",
    "run_triage_workflow",
    "state_consistency_validator_node",
]
