PYTHON ?= python
INCIDENT ?= fixtures/sample_incidents/incident_001
TRACE_DIR ?= traces
REPORT_DIR ?= reports

.PHONY: help lint test test-agents test-tools run-sample smoke smoke-dependency smoke-ci evaluate

help:
	@echo "Available targets:"
	@echo "  lint              Run ruff over source, tests, and scripts"
	@echo "  test              Run all agent/tool tests"
	@echo "  test-agents       Run agent tests"
	@echo "  test-tools        Run tool/workflow/CLI tests"
	@echo "  run-sample        Run CLI on INCIDENT with trace/report output"
	@echo "  smoke             Run real Ollama smoke check on INCIDENT"
	@echo "  smoke-dependency  Run real Ollama smoke check on dependency fixture"
	@echo "  smoke-ci          Run real Ollama smoke check on CI config fixture"
	@echo "  evaluate          Run real Ollama evaluation across all fixtures"

lint:
	$(PYTHON) -m ruff check src tests scripts

test:
	$(PYTHON) -m pytest tests/test_agents tests/test_tools

test-agents:
	$(PYTHON) -m pytest tests/test_agents

test-tools:
	$(PYTHON) -m pytest tests/test_tools

run-sample:
	$(PYTHON) -m src.main $(INCIDENT) --trace-dir $(TRACE_DIR) --report-dir $(REPORT_DIR)

smoke:
	$(PYTHON) scripts/smoke_ollama_workflow.py $(INCIDENT)

smoke-dependency:
	$(PYTHON) scripts/smoke_ollama_workflow.py fixtures/sample_incidents/incident_002_dependency_failure --trace-dir traces/smoke_dependency

smoke-ci:
	$(PYTHON) scripts/smoke_ollama_workflow.py fixtures/sample_incidents/incident_003_ci_config_failure --trace-dir traces/smoke_ci_config

evaluate:
	$(PYTHON) scripts/evaluate_fixtures.py
