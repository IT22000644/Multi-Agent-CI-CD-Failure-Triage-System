"""Pytest configuration and fixtures for the triage system tests."""

import pytest


@pytest.fixture(autouse=True)
def _patch_ollama_for_tests(monkeypatch):
	"""Patch agent LLM calls so tests don't require a real Ollama.

	Individual tests can override this by monkeypatching the planner's generator.
	"""
	try:
		from src.agents import (
			build_test_analyzer_agent,
			coordinator_agent,
			infra_config_analyzer_agent,
			remediation_planner_agent,
		)

		def _fake(prompt, config=None):
			if "incident_context_summary" in prompt:
				return (
					'{"incident_context_summary": "Loaded incident metadata and artifacts.", '
					'"notable_artifacts": ["incident.json", "build.log"], '
					'"limitations": ["Mocked LLM response for tests."]}'
				)
			if "failure_interpretation" in prompt:
				return (
					'{"failure_interpretation": "DATABASE_URL is missing during pytest.", '
					'"likely_failure_mode": "environment_issue", '
					'"relevant_evidence_ids": [], '
					'"limitations": ["Mocked LLM response for tests."]}'
				)
			if "config_interpretation" in prompt:
				return (
					'{"config_interpretation": "DATABASE_URL is absent from CI config.", '
					'"risk_summary": "Tests depending on database configuration will fail.", '
					'"relevant_check_ids": [], '
					'"limitations": ["Mocked LLM response for tests."]}'
				)
			if "recommended_action_details" in prompt:
				return (
					'{"executive_summary": "DATABASE_URL is missing in CI.", '
					'"root_cause_summary": "The CI workflow does not provide DATABASE_URL.", '
					'"recommended_action_details": '
					'"Add DATABASE_URL as a CI secret or environment variable.", '
					'"limitations": ["Mocked LLM response for tests."]}'
				)
			return "LLM: automatic test summary"

		monkeypatch.setattr(build_test_analyzer_agent, "generate_with_ollama", _fake)
		monkeypatch.setattr(coordinator_agent, "generate_with_ollama", _fake)
		monkeypatch.setattr(infra_config_analyzer_agent, "generate_with_ollama", _fake)
		monkeypatch.setattr(remediation_planner_agent, "generate_with_ollama", _fake)
	except Exception:
		# If import fails for some reason, just continue; tests that need LLM will patch explicitly.
		pass
	yield

