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
			return "LLM: automatic test summary"

		monkeypatch.setattr(build_test_analyzer_agent, "generate_with_ollama", _fake)
		monkeypatch.setattr(coordinator_agent, "generate_with_ollama", _fake)
		monkeypatch.setattr(infra_config_analyzer_agent, "generate_with_ollama", _fake)
		monkeypatch.setattr(remediation_planner_agent, "generate_with_ollama", _fake)
	except Exception:
		# If import fails for some reason, just continue; tests that need LLM will patch explicitly.
		pass
	yield

