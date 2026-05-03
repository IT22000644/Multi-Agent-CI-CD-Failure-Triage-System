from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.llm import StructuredLLMOutputError, parse_llm_json_output
from src.llm.ollama_client import generate_with_ollama, load_ollama_config_from_env
from src.state import (
    AgentName,
    ConfidenceLevel,
    ConfidenceScore,
    ConfidenceSubjectType,
    FailureCategory,
    FinalReport,
    FindingSeverity,
    RecommendedAction,
    SuspectedCause,
    TriageState,
)
from src.tracing.trace_logger import record_trace_event
from src.tracing.trace_metadata import (
    ollama_response_summary,
    slm_state_context,
    summarize_actions,
    summarize_causes,
    summarize_confidence_scores,
)


class RemediationPlannerInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    state: TriageState
    trace_dir: str | Path | None = None


class RemediationPlannerOutputParseError(RuntimeError):
    """Raised when the remediation planner LLM response is not valid structured output."""


class RemediationPlannerLLMOutput(BaseModel):
    executive_summary: str = Field(min_length=1)
    root_cause_summary: str = Field(min_length=1)
    recommended_action_details: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


def _run_deterministic_planner(state: TriageState) -> TriageState:
    # Preserve previous deterministic planner behaviour
    all_findings = (
        state.build_test_findings + state.config_findings + state.dependency_findings
    )
    env_findings = [
        f
        for f in all_findings
        if f.category == FailureCategory.ENVIRONMENT_ISSUE
    ]

    suspected: list[SuspectedCause] = []
    actions: list[RecommendedAction] = []
    confidences: list[ConfidenceScore] = []

    if env_findings:
        cause = SuspectedCause(
            cause_id="cause-001",
            summary="Missing required environment variables in CI",
            rationale=(
                "Analyzer evidence indicates DATABASE_URL is missing or not configured in CI."
            ),
            related_finding_ids=[f.finding_id for f in env_findings],
            evidence_ids=[],
            confidence=0.9,
            rank=1,
        )
        action = RecommendedAction(
            action_id="action-001",
            summary="Configure required environment variables in CI",
            details=(
                "Add DATABASE_URL to the CI workflow environment or repository secrets."
            ),
            related_cause_ids=[cause.cause_id],
            risk_level=FindingSeverity.LOW,
            confidence=0.9,
            rank=1,
        )
        confidence_score = ConfidenceScore(
            score_id="confidence-001",
            subject_type=ConfidenceSubjectType.CAUSE,
            subject_id=cause.cause_id,
            score=0.9,
            level=ConfidenceLevel.HIGH,
            rationale=(
                "Multiple findings point to a missing CI environment variable."
            ),
            evidence_ids=cause.evidence_ids,
        )

        suspected.append(cause)
        actions.append(action)
        confidences.append(confidence_score)
    else:
        # Generic fallback using first finding if available
        if all_findings:
            f = all_findings[0]
            cause = SuspectedCause(
                cause_id="cause-001",
                summary=f"Likely root cause related to {f.summary}",
                rationale=f"Based on finding {f.finding_id}",
                related_finding_ids=[f.finding_id],
                evidence_ids=[],
                confidence=0.5,
                rank=1,
            )
            action = RecommendedAction(
                action_id="action-001",
                summary=f"Investigate {f.summary}",
                details=f"Review logs and reproduce the failure: {f.details}",
                related_cause_ids=[cause.cause_id],
                risk_level=FindingSeverity.LOW,
                confidence=0.5,
                rank=1,
            )
            confidence_score = ConfidenceScore(
                score_id="confidence-001",
                subject_type=ConfidenceSubjectType.CAUSE,
                subject_id=cause.cause_id,
                score=0.5,
                level=ConfidenceLevel.MEDIUM,
                rationale="Low-medium confidence for fallback cause",
                evidence_ids=cause.evidence_ids,
            )

            suspected.append(cause)
            actions.append(action)
            confidences.append(confidence_score)

    state.suspected_causes = suspected
    state.recommended_actions = actions
    state.confidence_scores = confidences

    # Final report
    fallback_category = all_findings[0].category if all_findings else FailureCategory.UNKNOWN
    report = FinalReport(
        incident_id=state.metadata.incident_id,
        failure_classification=(
            FailureCategory.ENVIRONMENT_ISSUE if env_findings else fallback_category
        ),
        executive_summary="Autogenerated remediation plan",
        root_cause_summary=suspected[0].summary if suspected else None,
        recommended_actions=actions,
        evidence_summary=[e.snippet for e in state.evidence[:3]] if state.evidence else [],
        limitations=[
            "Deterministic planner uses heuristic rules and does not modify code."
        ],
    )

    state.final_report = report
    return state


def _parse_remediation_llm_output(text: str) -> RemediationPlannerLLMOutput:
    try:
        return parse_llm_json_output(
            text,
            RemediationPlannerLLMOutput,
            context="Remediation planner",
        )
    except (StructuredLLMOutputError, ValidationError) as exc:
        raise RemediationPlannerOutputParseError(
            f"Remediation planner LLM output parse failed: {exc}"
        ) from exc


def _build_remediation_prompt(state: TriageState) -> str:
    parts: list[str] = []
    meta = state.metadata
    parts.append(f"Incident ID: {meta.incident_id}")
    if meta.title:
        parts.append(f"Title: {meta.title}")

    # Observed failures
    if state.observed_failures:
        parts.append("Observed Failures:")
        for idx, of in enumerate(state.observed_failures):
            parts.append(f"- [{idx+1}] {of.summary}")

    # Findings grouped
    def append_findings(name: str, findings: list):
        if findings:
            parts.append(f"{name} Findings:")
            for f in findings:
                parts.append(f"- {f.finding_id}: {f.summary} | {f.details}")

    append_findings("Build/Test", state.build_test_findings)
    append_findings("Config", state.config_findings)
    append_findings("Dependency", state.dependency_findings)

    # Evidence snippets
    if state.evidence:
        parts.append("Evidence snippets:")
        for e in state.evidence[:5]:
            parts.append(f"- {e.evidence_id}: {e.snippet}")

    # Validated checks
    if state.validated_checks:
        parts.append("Validated Checks:")
        for c in state.validated_checks:
            parts.append(f"- {c.check_id}: {c.summary} (passed={c.passed})")

    parts.append(
        "Do not invent IDs or modify structured evidence."
    )
    parts.append(
        "Avoid suggesting unsupported fixes such as code changes to private repositories."
    )
    parts.append(
        "Return only valid JSON with this exact schema: "
        '{"executive_summary": string, "root_cause_summary": string, '
        '"recommended_action_details": string, "limitations": string[]}.'
    )

    return "\n".join(parts)


def run_remediation_planner(input_data: RemediationPlannerInput) -> TriageState:
    state = input_data.state.model_copy(deep=True)
    td = input_data.trace_dir

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.REMEDIATION_PLANNER,
            event_type="remediation_planner.input",
            message="Remediation planner inputs",
            metadata={
                **slm_state_context(state),
                **summarize_causes(state),
                **summarize_actions(state),
            },
        )

    prompt = _build_remediation_prompt(state)
    cfg = load_ollama_config_from_env()
    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.REMEDIATION_PLANNER,
            event_type="ollama.remediation_planner.request",
            message="SLM request for remediation narrative",
            metadata={
                "model": cfg.model,
                "prompt_character_count": len(prompt),
                "state_context": slm_state_context(state),
            },
        )

    llm_text = generate_with_ollama(prompt)
    llm_output = _parse_remediation_llm_output(llm_text)

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.REMEDIATION_PLANNER,
            event_type="ollama.remediation_planner.response",
            message="SLM response for remediation planner",
            metadata=ollama_response_summary(llm_output, raw_text=llm_text),
        )

    updated = _run_deterministic_planner(state)

    if updated.final_report:
        updated.final_report.executive_summary = llm_output.executive_summary
        updated.final_report.root_cause_summary = llm_output.root_cause_summary
        updated.final_report.limitations = llm_output.limitations

        if updated.recommended_actions:
            updated.recommended_actions[0].details = llm_output.recommended_action_details

    if td is not None:
        classification = (
            updated.final_report.failure_classification.value
            if updated.final_report and updated.final_report.failure_classification
            else None
        )
        record_trace_event(
            state,
            td,
            agent_name=AgentName.REMEDIATION_PLANNER,
            event_type="remediation_planner.output",
            message="Remediation planner produced causes, actions, and report",
            metadata={
                "failure_classification": classification,
                **summarize_causes(updated),
                **summarize_actions(updated),
                **summarize_confidence_scores(updated),
                "has_final_report": updated.final_report is not None,
            },
        )

    return updated


__all__ = [
    "RemediationPlannerInput",
    "RemediationPlannerLLMOutput",
    "RemediationPlannerOutputParseError",
    "run_remediation_planner",
]
