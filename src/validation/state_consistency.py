from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.state import (
    AgentName,
    ConfidenceSubjectType,
    FinalReport,
    TriageState,
    ValidatedCheck,
)

IssueSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class StateConsistencyIssue:
    """A cross-agent state consistency issue found after triage."""

    severity: IssueSeverity
    code: str
    message: str


@dataclass(frozen=True)
class StateConsistencyResult:
    """Summary of cross-agent consistency validation."""

    passed: bool
    errors: list[StateConsistencyIssue]
    warnings: list[StateConsistencyIssue]

    @property
    def issue_count(self) -> int:
        return len(self.errors) + len(self.warnings)


def _issue(severity: IssueSeverity, code: str, message: str) -> StateConsistencyIssue:
    return StateConsistencyIssue(severity=severity, code=code, message=message)


def _all_findings(state: TriageState):
    return state.build_test_findings + state.config_findings + state.dependency_findings


def _duplicate_ids(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _check_duplicate_ids(state: TriageState, issues: list[StateConsistencyIssue]) -> None:
    id_groups = {
        "evidence": [item.evidence_id for item in state.evidence],
        "finding": [item.finding_id for item in _all_findings(state)],
        "cause": [item.cause_id for item in state.suspected_causes],
        "action": [item.action_id for item in state.recommended_actions],
        "confidence": [item.score_id for item in state.confidence_scores],
        "check": [item.check_id for item in state.validated_checks],
    }
    for group_name, values in id_groups.items():
        for duplicate in sorted(_duplicate_ids(values)):
            issues.append(
                _issue(
                    "error",
                    "duplicate_id",
                    f"Duplicate {group_name} ID found: {duplicate}",
                )
            )


def _check_evidence_references(
    state: TriageState,
    issues: list[StateConsistencyIssue],
) -> None:
    evidence_ids = {item.evidence_id for item in state.evidence}
    findings = _all_findings(state)

    evidence_reference_groups = [
        ("finding", item.finding_id, item.evidence_ids) for item in findings
    ]
    evidence_reference_groups.extend(
        ("observed_failure", str(index + 1), item.evidence_ids)
        for index, item in enumerate(state.observed_failures)
    )
    evidence_reference_groups.extend(
        ("cause", item.cause_id, item.evidence_ids) for item in state.suspected_causes
    )
    evidence_reference_groups.extend(
        ("confidence", item.score_id, item.evidence_ids)
        for item in state.confidence_scores
    )
    evidence_reference_groups.extend(
        ("check", item.check_id, item.evidence_ids) for item in state.validated_checks
    )

    for owner_type, owner_id, referenced_ids in evidence_reference_groups:
        for evidence_id in referenced_ids:
            if evidence_id not in evidence_ids:
                issues.append(
                    _issue(
                        "error",
                        "missing_evidence_reference",
                        (
                            f"{owner_type} {owner_id} references missing evidence "
                            f"ID {evidence_id}"
                        ),
                    )
                )

    for finding in findings:
        if not finding.evidence_ids:
            issues.append(
                _issue(
                    "warning",
                    "finding_without_evidence",
                    f"Finding {finding.finding_id} has no supporting evidence IDs",
                )
            )


def _check_evidence_support_targets(
    state: TriageState,
    issues: list[StateConsistencyIssue],
) -> None:
    finding_ids = {item.finding_id for item in _all_findings(state)}
    cause_ids = {item.cause_id for item in state.suspected_causes}
    action_ids = {item.action_id for item in state.recommended_actions}
    check_ids = {item.check_id for item in state.validated_checks}
    report_ids = _report_subject_ids(state.final_report, state.metadata.incident_id)
    known_targets = finding_ids | cause_ids | action_ids | check_ids | report_ids

    for evidence in state.evidence:
        if evidence.supports and evidence.supports not in known_targets:
            issues.append(
                _issue(
                    "error",
                    "missing_evidence_support_target",
                    (
                        f"Evidence {evidence.evidence_id} supports missing target "
                        f"{evidence.supports}"
                    ),
                )
            )


def _check_cause_and_action_references(
    state: TriageState,
    issues: list[StateConsistencyIssue],
) -> None:
    finding_ids = {item.finding_id for item in _all_findings(state)}
    cause_ids = {item.cause_id for item in state.suspected_causes}

    for cause in state.suspected_causes:
        if not cause.related_finding_ids:
            issues.append(
                _issue(
                    "warning",
                    "cause_without_findings",
                    f"Suspected cause {cause.cause_id} is not linked to any findings",
                )
            )
        for finding_id in cause.related_finding_ids:
            if finding_id not in finding_ids:
                issues.append(
                    _issue(
                        "error",
                        "missing_cause_finding_reference",
                        (
                            f"Suspected cause {cause.cause_id} references missing "
                            f"finding ID {finding_id}"
                        ),
                    )
                )

    for action in state.recommended_actions:
        if not action.related_cause_ids:
            issues.append(
                _issue(
                    "warning",
                    "action_without_cause",
                    f"Recommended action {action.action_id} is not linked to any causes",
                )
            )
        for cause_id in action.related_cause_ids:
            if cause_id not in cause_ids:
                issues.append(
                    _issue(
                        "error",
                        "missing_action_cause_reference",
                        (
                            f"Recommended action {action.action_id} references missing "
                            f"cause ID {cause_id}"
                        ),
                    )
                )


def _report_subject_ids(report: FinalReport | None, incident_id: str) -> set[str]:
    if report is None:
        return {"final_report", incident_id}
    return {"final_report", report.incident_id, incident_id}


def _check_confidence_subjects(
    state: TriageState,
    issues: list[StateConsistencyIssue],
) -> None:
    subject_ids = {
        ConfidenceSubjectType.FINDING: {item.finding_id for item in _all_findings(state)},
        ConfidenceSubjectType.CAUSE: {item.cause_id for item in state.suspected_causes},
        ConfidenceSubjectType.ACTION: {item.action_id for item in state.recommended_actions},
        ConfidenceSubjectType.REPORT: _report_subject_ids(
            state.final_report,
            state.metadata.incident_id,
        ),
    }

    for score in state.confidence_scores:
        if score.subject_id not in subject_ids[score.subject_type]:
            issues.append(
                _issue(
                    "error",
                    "missing_confidence_subject",
                    (
                        f"Confidence score {score.score_id} references missing "
                        f"{score.subject_type.value} ID {score.subject_id}"
                    ),
                )
            )


def _check_final_report(state: TriageState, issues: list[StateConsistencyIssue]) -> None:
    report = state.final_report
    if report is None:
        issues.append(
            _issue("error", "missing_final_report", "Final report was not generated")
        )
        return

    if report.incident_id != state.metadata.incident_id:
        issues.append(
            _issue(
                "error",
                "final_report_incident_mismatch",
                (
                    f"Final report incident ID {report.incident_id} does not match "
                    f"metadata incident ID {state.metadata.incident_id}"
                ),
            )
        )

    if not report.executive_summary:
        issues.append(
            _issue(
                "warning",
                "empty_executive_summary",
                "Final report has no executive summary",
            )
        )
    if not report.root_cause_summary:
        issues.append(
            _issue(
                "warning",
                "empty_root_cause_summary",
                "Final report has no root cause summary",
            )
        )
    if not report.recommended_actions:
        issues.append(
            _issue(
                "warning",
                "empty_report_actions",
                "Final report contains no recommended actions",
            )
        )
    else:
        action_ids = {action.action_id for action in state.recommended_actions}
        for action in report.recommended_actions:
            if action.action_id not in action_ids:
                issues.append(
                    _issue(
                        "error",
                        "missing_report_action_reference",
                        (
                            f"Final report references missing recommended action "
                            f"ID {action.action_id}"
                        ),
                    )
                )


def validate_state_consistency(state: TriageState) -> StateConsistencyResult:
    """Validate that cross-agent references in the triage state are coherent."""

    issues: list[StateConsistencyIssue] = []
    _check_duplicate_ids(state, issues)
    _check_evidence_references(state, issues)
    _check_evidence_support_targets(state, issues)
    _check_cause_and_action_references(state, issues)
    _check_confidence_subjects(state, issues)
    _check_final_report(state, issues)

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    return StateConsistencyResult(
        passed=not errors,
        errors=errors,
        warnings=warnings,
    )


def _next_validation_check_id(state: TriageState) -> str:
    existing = {item.check_id for item in state.validated_checks}
    sequence = 1
    while True:
        candidate = f"check-state-consistency-{sequence:03d}"
        if candidate not in existing:
            return candidate
        sequence += 1


def apply_state_consistency_validation(state: TriageState) -> TriageState:
    """Append a validated check summarizing cross-agent state consistency."""

    updated = state.model_copy(deep=True)
    result = validate_state_consistency(updated)
    details = "; ".join(
        f"{issue.severity.upper()} {issue.code}: {issue.message}"
        for issue in [*result.errors, *result.warnings]
    )
    if not details:
        details = "All cross-agent references are internally consistent."

    check = ValidatedCheck(
        check_id=_next_validation_check_id(updated),
        summary="Cross-agent state consistency validation",
        passed=result.passed,
        details=details,
        agent_name=AgentName.REMEDIATION_PLANNER,
        evidence_ids=[],
    )
    updated.validated_checks = [*updated.validated_checks, check]
    return updated


__all__ = [
    "StateConsistencyIssue",
    "StateConsistencyResult",
    "apply_state_consistency_validation",
    "validate_state_consistency",
]
