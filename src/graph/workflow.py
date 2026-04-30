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
from src.tracing.trace_logger import write_trace_event


class WorkflowState(TypedDict, total=False):
    incident_dir: str
    trace_dir: str | None
    triage_state: TriageState


def _record_trace_event(
    trace_dir: str | None,
    triage_state: TriageState,
    *,
    agent_name: AgentName | None,
    event_type: str,
    message: str,
    metadata: dict[str, object] | None = None,
) -> None:
    if not trace_dir:
        return

    sequence = len(triage_state.trace_events) + 1
    event = TraceEvent(
        event_id=f"trace-{triage_state.metadata.incident_id}-{sequence:03d}",
        agent_name=agent_name,
        event_type=event_type,
        message=message,
        metadata=metadata or {},
    )
    write_trace_event(trace_dir, triage_state.metadata.incident_id, event)
    triage_state.trace_events = [*triage_state.trace_events, event]


def coordinator_node(state: WorkflowState) -> WorkflowState:
    coordinator_input = CoordinatorInput(
        incident_dir=state["incident_dir"],
        trace_dir=state.get("trace_dir"),
    )
    triage_state = initialize_triage_state(coordinator_input)

    trace_dir = state.get("trace_dir")
    incident_context_evidence_count = len(
        [item for item in triage_state.evidence if item.location == "ollama.incident_context"]
    )
    _record_trace_event(
        trace_dir,
        triage_state,
        agent_name=AgentName.COORDINATOR,
        event_type="coordinator.incident_loaded",
        message="Incident artifacts loaded into triage state",
        metadata={
            "artifact_count": len(triage_state.artifacts),
            "llm_incident_context_evidence_count": incident_context_evidence_count,
            "incident_dir": state["incident_dir"],
        },
    )
    return {
        **state,
        "triage_state": triage_state,
    }


def build_test_analyzer_node(state: WorkflowState) -> WorkflowState:
    triage_state: TriageState = state["triage_state"]
    inp = BuildTestAnalyzerInput(state=triage_state)
    updated = run_build_test_analyzer(inp)
    llm_evidence_count = len(
        [
            item
            for item in updated.evidence
            if item.location == "ollama.semantic_interpretation"
        ]
    )
    _record_trace_event(
        state.get("trace_dir"),
        updated,
        agent_name=AgentName.BUILD_TEST_ANALYZER,
        event_type="build_test_analyzer.completed",
        message="Build and test artifacts parsed and interpreted",
        metadata={
            "observed_failure_count": len(updated.observed_failures),
            "finding_count": len(updated.build_test_findings),
            "llm_interpretation_evidence_count": llm_evidence_count,
        },
    )
    return {**state, "triage_state": updated}


def infra_config_analyzer_node(state: WorkflowState) -> WorkflowState:
    triage_state: TriageState = state["triage_state"]
    inp = InfraConfigAnalyzerInput(state=triage_state)
    updated = run_infra_config_analyzer(inp)
    llm_evidence_count = len(
        [
            item
            for item in updated.evidence
            if item.location == "ollama.infra_config_interpretation"
        ]
    )
    _record_trace_event(
        state.get("trace_dir"),
        updated,
        agent_name=AgentName.INFRA_CONFIG_ANALYZER,
        event_type="infra_config_analyzer.completed",
        message="Infrastructure and configuration checks completed",
        metadata={
            "config_finding_count": len(updated.config_findings),
            "dependency_finding_count": len(updated.dependency_findings),
            "llm_interpretation_evidence_count": llm_evidence_count,
            "validated_check_count": len(updated.validated_checks),
        },
    )
    return {**state, "triage_state": updated}


def remediation_planner_node(state: WorkflowState) -> WorkflowState:
    triage_state: TriageState = state["triage_state"]
    inp = RemediationPlannerInput(state=triage_state)
    updated = run_remediation_planner(inp)
    _record_trace_event(
        state.get("trace_dir"),
        updated,
        agent_name=AgentName.REMEDIATION_PLANNER,
        event_type="remediation_planner.completed",
        message="Ollama-backed remediation plan generated",
        metadata={
            "suspected_cause_count": len(updated.suspected_causes),
            "recommended_action_count": len(updated.recommended_actions),
            "confidence_score_count": len(updated.confidence_scores),
        },
    )
    _record_trace_event(
        state.get("trace_dir"),
        updated,
        agent_name=None,
        event_type="workflow.complete",
        message="Triage workflow completed",
        metadata={
            "classification": (
                updated.final_report.failure_classification.value
                if updated.final_report and updated.final_report.failure_classification
                else None
            ),
            "has_final_report": updated.final_report is not None,
        },
    )
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
    "build_test_analyzer_node",
    "infra_config_analyzer_node",
    "remediation_planner_node",
    "run_triage_workflow",
]
