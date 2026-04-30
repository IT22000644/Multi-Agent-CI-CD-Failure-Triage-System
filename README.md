# Local Multi-Agent CI/CD Failure Triage System

A locally hosted multi-agent system for automated CI/CD failure triage in software engineering and DevOps workflows.

## Overview

The system analyzes failed pipeline artifacts using deterministic tools and a multi-node agent workflow to:

- Identify failure root causes
- Collect supporting evidence
- Generate remediation recommendations
- Produce structured incident reports

### Agents

- **Coordinator Agent**: Initializes triage state and uses an LLM to summarize incident context
- **Build/Test Analyzer Agent**: Parses build logs and test output, then uses an LLM to interpret failure symptoms
- **Infra/Config Analyzer Agent**: Validates CI configuration, Dockerfile, and dependencies, then uses an LLM to interpret configuration risk
- **Remediation Planner Agent**: Generates suspected causes and recommended actions using an LLM (via local Ollama)

## Current Implementation

The system combines deterministic artifact analyzers with a local LLM (via Ollama) for incident context summarization, build/test interpretation, infrastructure/configuration interpretation, and remediation planning. It accepts incident packages with artifacts such as:

- `incident.json` — metadata
- `build.log` — build output
- `test-report.txt` — test results
- CI workflow files (e.g., `.github/workflows/ci.yml`)
- `Dockerfile`
- Dependency files (`requirements.txt`, `package.json`, `pyproject.toml`)

SLM-backed agents request structured JSON from Ollama and validate responses with Pydantic before adding interpretations or final report fields. Malformed model responses fail clearly instead of being silently copied into state.

### Supported Failure Categories

- CI build failures
- Unit test failures
- Dependency conflicts
- Missing environment variables
- CI config validation errors
- Dockerfile build issues

## Project Structure

```text
src/
├── main.py              # CLI entry point
├── agents/              # Agent implementations
│   ├── __init__.py
│   ├── coordinator_agent.py
│   ├── build_test_analyzer_agent.py
│   ├── infra_config_analyzer_agent.py
│   └── remediation_planner_agent.py
├── tools/               # Deterministic analyzers
│   ├── artifact_loader.py
│   ├── build_log_parser.py
│   ├── ci_config_validator.py
│   ├── dependency_inspector.py
│   ├── dockerfile_inspector.py
│   ├── triage_runner.py
│   └── __init__.py
├── state/
│   └── triage_state.py  # Pydantic models for shared state
├── graph/
│   └── workflow.py      # LangGraph multi-node workflow
└── tracing/
    └── trace_logger.py  # JSONL trace event logging

fixtures/
└── sample_incidents/
    └── incident_001/    # Sample fixture incident

tests/
├── test_agents/         # Agent tests
└── test_tools/          # Tool, workflow, and CLI tests
    ├── test_cli.py      # CLI tests
    └── ...

traces/                  # Output directory for trace events
docs/
```

## Technical Stack

- **Python 3.12+** — Runtime
- **LangGraph** — Multi-agent workflow orchestration
- **Pydantic v2** — Type-safe shared state and validation
- **Ollama** — Local LLM runtime (required for SLM-backed agent interpretation and planning)
- **langchain-ollama** — LLM client wrapper
- **pytest** — Testing and evaluation
- **ruff** — Linting and code quality
- **Docker & Docker Compose** — Containerized deployment

## Quick Start

### Prerequisites

Ollama is required to run the triage system. Install and start it:

```powershell
# Download Ollama from https://ollama.ai or use a package manager
# Start the Ollama service (runs on http://localhost:11434 by default)
ollama serve

# In a separate terminal, download the model
ollama pull llama3.1
```

### Setup

Create a virtual environment and install the project in development mode:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

### Run Triage

Make sure Ollama is running (`ollama serve` in a separate terminal), then use the CLI to analyze an incident:

```powershell
# Human-readable output
.\.venv\Scripts\python.exe -m src.main fixtures\sample_incidents\incident_001

# JSON output
.\.venv\Scripts\python.exe -m src.main fixtures\sample_incidents\incident_001 --json

# With trace logging
.\.venv\Scripts\python.exe -m src.main fixtures\sample_incidents\incident_001 --trace-dir traces

# With trace logging and exported report artifacts
.\.venv\Scripts\python.exe -m src.main fixtures\sample_incidents\incident_001 --trace-dir traces --report-dir reports
```

**Note**: If Ollama is unavailable, the CLI will fail with an `OllamaGenerationError` instead of silently falling back to deterministic-only analysis.

### Run Real Ollama Smoke Check

Use the smoke script to verify the full local runtime path with a real Ollama server:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_ollama_workflow.py
```

The smoke check validates that Ollama is reachable, the configured model is available, all SLM-backed workflow stages execute, trace output is written, and the final report contains remediation output.

You can pass another incident directory to exercise a different failure class:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_ollama_workflow.py fixtures\sample_incidents\incident_002_dependency_failure --trace-dir traces\smoke_dependency

.\.venv\Scripts\python.exe scripts\smoke_ollama_workflow.py fixtures\sample_incidents\incident_003_ci_config_failure --trace-dir traces\smoke_ci_config
```

### Report Artifacts

When `--report-dir` is provided, the CLI writes:

```text
reports/<incident_id>/summary.json
reports/<incident_id>/report.md
```

The JSON file preserves the structured triage state for evaluation. The Markdown file is a human-readable incident report for demos and review.

### Run Tests

Tests automatically mock the Ollama LLM client and do not require a running Ollama service:

```powershell
# Run all tests
.\.venv\Scripts\python.exe -m pytest

# Windows PowerShell examples used in this repository
.\.venv\Scripts\python.exe -m pytest tests\test_agents tests\test_tools

# Run specific test suite
.\.venv\Scripts\python.exe -m pytest tests\test_agents
.\.venv\Scripts\python.exe -m pytest tests\test_tools

# Run with coverage
.\.venv\Scripts\python.exe -m pytest --cov=src
```

### Code Quality

```powershell
# Lint the codebase
.\.venv\Scripts\python.exe -m ruff check src tests

# Auto-fix formatting issues
.\.venv\Scripts\python.exe -m ruff check src tests --fix
```

### Ollama Configuration

Customize Ollama behavior using environment variables:

```powershell
# Set custom Ollama server (default: http://localhost:11434)
$env:OLLAMA_BASE_URL="http://example.com:11434"

# Set model name (default: llama3.1)
$env:OLLAMA_MODEL="llama2"

# Set LLM timeout in seconds (default: 30.0)
$env:OLLAMA_TIMEOUT_SECONDS="60"

# Then run triage
.\.venv\Scripts\python.exe -m src.main fixtures\sample_incidents\incident_001
```

## CLI Reference

```
usage: python -m src.main [-h] [--trace-dir PATH] [--json] incident_dir

Positional Arguments:
  incident_dir      Path to the incident directory containing artifacts

Optional Arguments:
  --trace-dir PATH  Directory to write trace events (JSONL format)
  --json            Output results as JSON instead of human-readable format
  -h, --help        Show this help message and exit
```

### Output Examples

**Human-readable format:**
```
Incident: incident_001
Title: Pytest failure due to missing DATABASE_URL
Classification: environment_issue

Suspected Causes:
1. Missing required environment variables in CI

Recommended Actions:
1. Configure required environment variables in CI

Summary:
Autogenerated remediation plan
```

**JSON format:**
```json
{
  "incident_id": "incident_001",
  "title": "Pytest failure due to missing DATABASE_URL",
  "failure_classification": "environment_issue",
  "suspected_causes": [
    {
      "cause_id": "cause-001",
      "summary": "Missing required environment variables in CI",
      "confidence": 0.9,
      "rank": 1
    }
  ],
  "recommended_actions": [
    {
      "action_id": "action-001",
      "summary": "Configure required environment variables in CI",
      "confidence": 0.9,
      "rank": 1
    }
  ],
  "executive_summary": "Autogenerated remediation plan",
  "trace_event_count": 1
}
```

## Docker Deployment

Build and run the application using Docker Compose:

```powershell
docker compose build
docker compose up
```

Docker support is included as a project scaffold. The primary current usage path is the local CLI.

To run a real triage inside Docker, ensure Ollama is available (either installed on the host or linked via Docker network), then pass an incident directory argument or update the Compose command accordingly. The current `docker compose up` command does not pass an incident directory by itself.

## Workflow Architecture

The system uses a multi-node LangGraph workflow:

```
Coordinator
    ↓
Build/Test Analyzer
    ↓
Infra/Config Analyzer
    ↓
Remediation Planner
```

Each node processes the shared `TriageState`, progressively adding:
- Observed failures
- Build/test findings
- Configuration findings
- Dependency findings
- Validated checks
- Suspected causes
- Recommended actions
- Final report

## State Model

The `TriageState` (Pydantic BaseModel) includes:

- **metadata**: Incident ID, title, repository, branch, etc.
- **artifacts**: Collection of loaded artifact records
- **observed_failures**: High-level failure observations
- **build_test_findings**: Structured findings from build/test analysis
- **config_findings**: CI/Docker/config validation findings
- **dependency_findings**: Dependency conflict findings
- **evidence**: Concrete evidence snippets from artifacts
- **suspected_causes**: Root cause hypotheses with confidence
- **recommended_actions**: Remediation steps with risk/confidence
- **confidence_scores**: Confidence measurements for findings/causes/actions
- **validated_checks**: Validation checks performed
- **final_report**: Final incident summary with classification
- **trace_events**: Event log of workflow execution (JSONL)

## Testing

The project includes comprehensive test coverage:

```powershell
# Unit tests for tools
.\.venv\Scripts\python.exe -m pytest tests\test_tools

# Agent tests
.\.venv\Scripts\python.exe -m pytest tests\test_agents

# CLI tests
.\.venv\Scripts\python.exe -m pytest tests\test_tools\test_cli.py

# All tests
.\.venv\Scripts\python.exe -m pytest
```

Tests use the `fixtures/sample_incidents/incident_001` fixture to validate:

- Artifact loading and parsing
- Finding generation and evidence grounding
- State immutability (no mutations of input state)
- Output JSON schema compliance
- CLI error handling

## Deliverables

✅ **Implemented:**
- Four agent wrappers (Coordinator, Build/Test, Infra/Config, Remediation Planner)
- Custom deterministic artifact analysis tools
- Multi-node LangGraph workflow
- Pydantic-based shared state model
- JSONL trace logging
- CLI with human and JSON output
- Local LLM integration (Ollama + langchain-ollama)
- Comprehensive unit tests with LLM mocking (80+ passing)
- Code quality checks (ruff passing)
- Docker Compose deployment configuration

⏭️ **Future Enhancements:**
- Additional artifact types (e.g., logs, stack traces)
- Machine learning-based cause classification
- Historical incident correlation
- Interactive remediation guidance
