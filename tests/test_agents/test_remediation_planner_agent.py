from __future__ import annotations

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
from src.state import ConfidenceLevel


def test_remediation_planner_creates_remediation_plan() -> None:
    coord = CoordinatorInput(incident_dir="fixtures/sample_incidents/incident_001")
    state = initialize_triage_state(coord)

    state = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))
    state = run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))
    state = run_remediation_planner(RemediationPlannerInput(state=state))

    assert state.suspected_causes
    assert state.recommended_actions
    assert state.confidence_scores
    assert state.final_report is not None

    # At least one cause or report should mention environment vars (DATABASE_URL)
    text = (
        " ".join([c.summary for c in state.suspected_causes])
        + " "
        + (state.final_report.root_cause_summary or "")
    )
    assert "DATABASE_URL" in text.upper() or "ENV" in text.upper()

    for action in state.recommended_actions:
        assert action.risk_level is not None
        assert 0.0 <= action.confidence <= 1.0

    for score in state.confidence_scores:
        assert score.score_id
        assert isinstance(score.level, ConfidenceLevel)
        assert score.subject_id
