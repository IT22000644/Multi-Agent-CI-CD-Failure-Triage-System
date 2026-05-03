from __future__ import annotations

from src.state import (
    AgentName,
    ArtifactType,
    ConfidenceLevel,
    ConfidenceScore,
    ConfidenceSubjectType,
    EvidenceItem,
    FailureCategory,
    FinalReport,
    Finding,
    FindingSeverity,
    IncidentMetadata,
    RecommendedAction,
    SuspectedCause,
    TriageState,
)
from src.validation import apply_state_consistency_validation, validate_state_consistency


def _valid_state() -> TriageState:
    evidence = EvidenceItem(
        evidence_id="evidence-001",
        artifact_name="build.log",
        artifact_type=ArtifactType.LOG,
        location="line 10",
        snippet="DATABASE_URL is not set",
        agent_name=AgentName.BUILD_TEST_ANALYZER,
        supports="finding-001",
    )
    finding = Finding(
        finding_id="finding-001",
        agent_name=AgentName.BUILD_TEST_ANALYZER,
        category=FailureCategory.ENVIRONMENT_ISSUE,
        severity=FindingSeverity.HIGH,
        summary="Missing DATABASE_URL",
        evidence_ids=[evidence.evidence_id],
    )
    cause = SuspectedCause(
        cause_id="cause-001",
        summary="CI environment is missing DATABASE_URL",
        rationale="Build log and workflow evidence indicate the variable is absent.",
        related_finding_ids=[finding.finding_id],
        evidence_ids=[evidence.evidence_id],
        confidence=0.9,
    )
    action = RecommendedAction(
        action_id="action-001",
        summary="Add DATABASE_URL to CI secrets",
        related_cause_ids=[cause.cause_id],
        risk_level=FindingSeverity.LOW,
        confidence=0.9,
    )
    confidence = ConfidenceScore(
        score_id="confidence-001",
        subject_type=ConfidenceSubjectType.CAUSE,
        subject_id=cause.cause_id,
        score=0.9,
        level=ConfidenceLevel.HIGH,
        evidence_ids=[evidence.evidence_id],
    )
    return TriageState(
        metadata=IncidentMetadata(incident_id="incident-001"),
        build_test_findings=[finding],
        evidence=[evidence],
        suspected_causes=[cause],
        recommended_actions=[action],
        confidence_scores=[confidence],
        final_report=FinalReport(
            incident_id="incident-001",
            failure_classification=FailureCategory.ENVIRONMENT_ISSUE,
            executive_summary="CI environment variable is missing.",
            root_cause_summary="DATABASE_URL is absent from CI.",
            recommended_actions=[action],
        ),
    )


def test_validate_state_consistency_passes_for_linked_state() -> None:
    result = validate_state_consistency(_valid_state())

    assert result.passed is True
    assert result.errors == []


def test_validate_state_consistency_reports_missing_evidence_reference() -> None:
    state = _valid_state()
    state.build_test_findings[0].evidence_ids = ["missing-evidence"]

    result = validate_state_consistency(state)

    assert result.passed is False
    assert any(issue.code == "missing_evidence_reference" for issue in result.errors)


def test_validate_state_consistency_reports_missing_action_cause_reference() -> None:
    state = _valid_state()
    state.recommended_actions[0].related_cause_ids = ["missing-cause"]

    result = validate_state_consistency(state)

    assert result.passed is False
    assert any(issue.code == "missing_action_cause_reference" for issue in result.errors)


def test_validate_state_consistency_reports_missing_confidence_subject() -> None:
    state = _valid_state()
    state.confidence_scores[0].subject_id = "missing-cause"

    result = validate_state_consistency(state)

    assert result.passed is False
    assert any(issue.code == "missing_confidence_subject" for issue in result.errors)


def test_validate_state_consistency_reports_report_action_drift() -> None:
    state = _valid_state()
    state.recommended_actions = []

    result = validate_state_consistency(state)

    assert result.passed is False
    assert any(issue.code == "missing_report_action_reference" for issue in result.errors)


def test_apply_state_consistency_validation_appends_check() -> None:
    updated = apply_state_consistency_validation(_valid_state())

    check = updated.validated_checks[-1]
    assert check.check_id == "check-state-consistency-001"
    assert check.summary == "Cross-agent state consistency validation"
    assert check.passed is True


def test_validate_state_consistency_reports_duplicate_evidence_ids() -> None:
    state = _valid_state()
    dup = state.evidence[0].model_copy()
    state.evidence = [state.evidence[0], dup]

    result = validate_state_consistency(state)

    assert result.passed is False
    assert any(issue.code == "duplicate_id" for issue in result.errors)


def test_validate_state_consistency_reports_duplicate_finding_ids() -> None:
    state = _valid_state()
    dup_finding = state.build_test_findings[0].model_copy()
    state.build_test_findings = [state.build_test_findings[0], dup_finding]

    result = validate_state_consistency(state)

    assert result.passed is False
    assert any(issue.code == "duplicate_id" for issue in result.errors)


def test_validate_state_consistency_reports_missing_evidence_support_target() -> None:
    state = _valid_state()
    ghost = state.evidence[0].model_copy(
        update={
            "evidence_id": "evidence-ghost-support",
            "supports": "ghost-target",
        }
    )
    state.evidence.append(ghost)

    result = validate_state_consistency(state)

    assert result.passed is False
    assert any(issue.code == "missing_evidence_support_target" for issue in result.errors)


def test_validate_state_consistency_reports_missing_cause_finding_reference() -> None:
    state = _valid_state()
    state.suspected_causes[0].related_finding_ids = ["missing-finding"]

    result = validate_state_consistency(state)

    assert result.passed is False
    assert any(issue.code == "missing_cause_finding_reference" for issue in result.errors)


def test_validate_state_consistency_reports_final_report_missing_shared_action() -> None:
    state = _valid_state()
    lone_action = RecommendedAction(
        action_id="action-ghost",
        summary="Not linked in shared state",
        related_cause_ids=[state.suspected_causes[0].cause_id],
        risk_level=FindingSeverity.LOW,
        confidence=0.5,
    )
    assert state.final_report is not None
    state.final_report = state.final_report.model_copy(
        update={"recommended_actions": [lone_action]}
    )

    result = validate_state_consistency(state)

    assert result.passed is False
    assert any(issue.code == "missing_report_action_reference" for issue in result.errors)
