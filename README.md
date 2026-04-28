# Local Multi-Agent CI/CD Failure Triage System

This project is a locally hosted multi-agent system for automated CI/CD failure triage in software engineering and DevOps workflows.

The system is planned to use a local language model served through Ollama and coordinate four specialized agents:

- Coordinator Agent
- Build/Test Analyzer Agent
- Infra/Config Analyzer Agent
- Remediation Planner Agent

The goal is to inspect failed pipeline artifacts, identify likely root causes, collect supporting evidence, and produce a structured incident report with safe remediation steps.

## Planned Scope

The system accepts a local incident package containing artifacts such as:

- `incident.json`
- `build.log`
- `test-report.txt`
- CI workflow configuration, such as `.github/workflows/ci.yml`
- `Dockerfile`
- Dependency files, such as `requirements.txt` or `package.json`
- Optional diff or commit metadata

It is intended to support:

- CI build failures
- Unit test failures
- Dependency conflicts
- Invalid workflow steps
- Docker build problems
- Missing environment variables
- Invalid deployment configuration

## Project Structure

```text
src/
├── agents/
├── tools/
├── state/
├── graph/
└── tracing/

fixtures/
└── sample_incidents/
    └── incident_001/

tests/
├── test_tools/
└── test_agents/

traces/
docs/
```

## Technical Stack

- Python 3.12
- LangGraph for agent orchestration
- Ollama for local model serving
- Pydantic for typed shared state and tool responses
- pytest for evaluation and testing
- Docker for containerized execution

## Local Setup

Create a virtual environment and install the project in editable mode:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

## Ollama Setup

For Windows development, the recommended setup is to run Ollama natively on the host machine and run the triage system in Docker.

The Docker Compose configuration uses:

```text
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

You can override the model with:

```bash
set OLLAMA_MODEL=llama3.1
```

## Docker Usage

Build the application container:

```bash
docker compose build
```

Run the application:

```bash
docker compose up
```

The application entry point is planned as:

```bash
python -m src.main
```

This entry point will be implemented when the agent workflow is added.

## Evaluation Plan

The project will use fixture-based failure cases to evaluate:

- Correct failure classification
- Evidence quality and artifact grounding
- Relevance and safety of recommended actions
- Avoidance of unsupported or hallucinated fixes

## Deliverables

- Source code repository
- Four implemented agents
- Custom deterministic Python tools
- Evaluation scripts and fixture cases
- JSONL trace output
- Technical report and demo materials
