from __future__ import annotations

import pytest

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


def _analyzed_state():
    coord = CoordinatorInput(incident_dir="fixtures/sample_incidents/incident_001")
    state = initialize_triage_state(coord)

    state = run_build_test_analyzer(BuildTestAnalyzerInput(state=state))
    return run_infra_config_analyzer(InfraConfigAnalyzerInput(state=state))


def test_remediation_planner_creates_remediation_plan() -> None:
    state = _analyzed_state()

    # LLM call is mocked by conftest.py autouse fixture
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


def test_remediation_planner_uses_structured_llm_fields(monkeypatch) -> None:
    from src.agents import remediation_planner_agent

    def fake_generate(prompt, config=None):
        return """
        {
          "executive_summary": "Configure CI environment variables.",
          "root_cause_summary": "DATABASE_URL is not available to pytest.",
          "recommended_action_details": "Add DATABASE_URL to repository secrets.",
          "limitations": ["Only provided artifacts were inspected."]
        }
        """

    monkeypatch.setattr(remediation_planner_agent, "generate_with_ollama", fake_generate)

    state = run_remediation_planner(RemediationPlannerInput(state=_analyzed_state()))

    assert state.final_report is not None
    assert state.final_report.executive_summary == "Configure CI environment variables."
    assert state.final_report.root_cause_summary == "DATABASE_URL is not available to pytest."
    assert state.final_report.limitations == ["Only provided artifacts were inspected."]
    assert state.recommended_actions[0].details == "Add DATABASE_URL to repository secrets."


def test_remediation_planner_accepts_fenced_json_response(monkeypatch) -> None:
    from src.agents import remediation_planner_agent

    def fake_generate(prompt, config=None):
        return """```json
        {
          "executive_summary": "Executive text.",
          "root_cause_summary": "Root cause text.",
          "recommended_action_details": "Action detail text.",
          "limitations": []
        }
        ```"""

    monkeypatch.setattr(remediation_planner_agent, "generate_with_ollama", fake_generate)

    state = run_remediation_planner(RemediationPlannerInput(state=_analyzed_state()))

    assert state.final_report is not None
    assert state.final_report.executive_summary == "Executive text."
    assert state.final_report.root_cause_summary == "Root cause text."


def test_remediation_planner_malformed_json_raises(monkeypatch) -> None:
    from src.agents import remediation_planner_agent

    def bad_generate(prompt, config=None):
        return "This is not JSON."

    monkeypatch.setattr(remediation_planner_agent, "generate_with_ollama", bad_generate)

    with pytest.raises(remediation_planner_agent.RemediationPlannerOutputParseError):
        run_remediation_planner(RemediationPlannerInput(state=_analyzed_state()))


def test_remediation_planner_missing_json_fields_raises(monkeypatch) -> None:
    from src.agents import remediation_planner_agent

    def bad_generate(prompt, config=None):
        return '{"executive_summary": "Only one field."}'

    monkeypatch.setattr(remediation_planner_agent, "generate_with_ollama", bad_generate)

    with pytest.raises(remediation_planner_agent.RemediationPlannerOutputParseError):
        run_remediation_planner(RemediationPlannerInput(state=_analyzed_state()))



def test_remediation_planner_ollama_failure_raises(monkeypatch):
    from src.llm.ollama_client import OllamaGenerationError

    def bad_generate(prompt, config=None):
        raise OllamaGenerationError("no connection")

    from src.agents import remediation_planner_agent
    remediation_planner_agent.generate_with_ollama = bad_generate

    with pytest.raises(OllamaGenerationError):
        run_remediation_planner(RemediationPlannerInput(state=_analyzed_state()))
