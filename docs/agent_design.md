# Agent Design and Prompt Strategy

This section is written for the CTSE Assignment 2 technical report. It explains how the system uses a local multi-agent architecture, grounded tool outputs, structured SLM prompts, and validated state updates to reduce hallucination and preserve context.

## Multi-Agent Design Matrix

| Agent | Persona | Responsibility | Input State | Tools Used | SLM Role | Output State | Failure Handling |
|---|---|---|---|---|---|---|---|
| Coordinator Agent | Incident intake analyst | Load incident artifacts and establish incident context | Incident directory, `incident.json`, artifact records | `load_incident_artifacts`, metadata extraction | Summarize incident context from metadata and artifact inventory | `metadata`, `artifacts`, coordinator SLM evidence | Missing/invalid path raises file errors; malformed SLM JSON raises coordinator parse error |
| Build/Test Analyzer Agent | CI log analyst | Detect build, install, and test failure symptoms | `build.log`, `test-report.txt`, existing evidence | `parse_build_and_test_logs` | Interpret failure symptoms from parsed log evidence | `observed_failures`, `build_test_findings`, build/test SLM evidence | Ollama or structured output errors stop workflow clearly |
| Infra/Config Analyzer Agent | DevOps configuration reviewer | Validate CI workflow, Dockerfile, and dependency manifests | CI YAML, Dockerfile, dependency artifacts, prior state | `validate_ci_config`, `inspect_dockerfile`, `inspect_dependencies` | Interpret configuration/dependency risk from deterministic checks | `config_findings`, `dependency_findings`, `validated_checks`, infra/config SLM evidence | Tool validation records findings/checks; malformed SLM JSON raises infra/config parse error |
| Remediation Planner Agent | Senior incident responder | Synthesize root cause and remediation plan | Full accumulated `TriageState` | Structured state from previous agents | Produce strict JSON final report fields and action details | `suspected_causes`, `recommended_actions`, `confidence_scores`, `final_report` | Ollama failure or invalid JSON prevents invalid report generation |

## Workflow Diagram

```text
Incident Folder
    |
    v
Coordinator Agent
    - loads incident metadata
    - loads artifact records
    - asks Ollama for incident context JSON
    |
    v
Build/Test Analyzer Agent
    - parses build.log and test-report.txt
    - extracts observed failures, findings, evidence
    - asks Ollama for failure interpretation JSON
    |
    v
Infra/Config Analyzer Agent
    - validates ci.yml, Dockerfile, dependency files
    - records checks, findings, evidence
    - asks Ollama for config-risk interpretation JSON
    |
    v
Remediation Planner Agent
    - consumes complete shared state
    - builds suspected causes and actions
    - asks Ollama for structured remediation JSON
    |
    v
Final Report + JSONL Trace Logs + Evaluation Results
```

## Shared Prompt Strategy

The system uses local SLMs through Ollama, but the SLM is not treated as the source of truth. Each agent follows a grounded sequence:

1. Deterministic Python tools inspect local artifacts first.
2. Tool outputs become typed findings, checks, and evidence in `TriageState`.
3. The agent prompt includes only relevant metadata, artifact excerpts, finding IDs, check IDs, and evidence snippets.
4. The SLM must return strict JSON matching an agent-specific schema.
5. Pydantic validates the SLM JSON before state is updated.
6. Invalid SLM output raises an explicit parse error instead of silently entering state.

Common prompt constraints include:

- Return only valid JSON.
- Do not invent artifact names.
- Do not invent finding IDs, check IDs, or evidence IDs.
- Do not modify structured evidence.
- Do not propose unsupported fixes.
- Use only provided artifacts, findings, checks, and evidence.
- Keep interpretations concise and grounded in the incident data.

## Agent-Level Prompt and Reasoning Design

### Coordinator Agent

**Purpose:** Initialize the incident and summarize the available context.

**Prompt strategy:** The Coordinator receives incident metadata and an inventory of loaded artifacts. It asks the SLM to summarize only what is known from `incident.json` and loaded artifact records.

**Structured output schema:**

```json
{
  "incident_context_summary": "string",
  "notable_artifacts": ["string"],
  "limitations": ["string"]
}
```

**Constraints:**

- Do not infer the root cause.
- Do not claim an artifact exists unless it was loaded.
- Do not invent repository, branch, pipeline, or run metadata.

**Reasoning logic:**

1. Load artifacts from the incident directory.
2. Parse incident metadata into `IncidentMetadata`.
3. Ask the SLM to summarize incident context.
4. Validate the JSON response.
5. Store the context summary as evidence with location `ollama.incident_context`.

**State updates:**

- `metadata`
- `artifacts`
- coordinator evidence item

### Build/Test Analyzer Agent

**Purpose:** Identify failure symptoms from build and test logs.

**Prompt strategy:** The agent first runs the deterministic log parser. The SLM then receives log excerpts, observed failure summaries, finding IDs, and evidence snippets. Its job is semantic interpretation, not primary detection.

**Structured output schema:**

```json
{
  "failure_interpretation": "string",
  "likely_failure_mode": "string or null",
  "relevant_evidence_ids": ["string"],
  "limitations": ["string"]
}
```

**Constraints:**

- Do not invent log lines.
- Do not invent evidence IDs.
- Interpret only evidence already extracted by the parser.
- Do not rewrite deterministic findings.

**Reasoning logic:**

1. Parse `build.log` and `test-report.txt`.
2. Classify failure categories such as environment, dependency, test, or infrastructure issue.
3. Attach evidence snippets to findings.
4. Ask the SLM for a concise failure interpretation.
5. Validate the JSON response.
6. Store the SLM interpretation as evidence with location `ollama.semantic_interpretation`.

**State updates:**

- `observed_failures`
- `build_test_findings`
- build/test evidence

### Infra/Config Analyzer Agent

**Purpose:** Validate CI/CD configuration and dependency manifests.

**Prompt strategy:** The agent runs deterministic validators for CI YAML, Dockerfile, and dependency files. The SLM receives config excerpts, findings, and validated checks, then summarizes the configuration risk.

**Structured output schema:**

```json
{
  "config_interpretation": "string",
  "risk_summary": "string or null",
  "relevant_check_ids": ["string"],
  "limitations": ["string"]
}
```

**Constraints:**

- Do not invent secrets or environment variables.
- Do not invent CI jobs, steps, or dependency versions.
- Do not propose unsupported configuration changes.
- Use only deterministic findings and validated checks.

**Reasoning logic:**

1. Validate `ci.yml` structure and required environment variables.
2. Inspect Dockerfile safety/build assumptions.
3. Inspect dependency manifests.
4. Record findings and validated checks.
5. Ask the SLM to summarize configuration risk.
6. Validate the JSON response.
7. Store SLM output as evidence with location `ollama.infra_config_interpretation`.

**State updates:**

- `config_findings`
- `dependency_findings`
- `validated_checks`
- infra/config evidence

### Remediation Planner Agent

**Purpose:** Convert accumulated evidence into a final triage report.

**Prompt strategy:** The planner receives the full accumulated state: failures, findings, evidence, checks, and incident metadata. It must return structured remediation JSON that can be safely inserted into the final report.

**Structured output schema:**

```json
{
  "executive_summary": "string",
  "root_cause_summary": "string",
  "recommended_action_details": "string",
  "limitations": ["string"]
}
```

**Constraints:**

- Do not invent IDs.
- Do not modify structured evidence.
- Avoid unsupported fixes such as code changes not grounded in artifacts.
- Return only valid JSON.

**Reasoning logic:**

1. Read all prior findings and evidence.
2. Build deterministic suspected causes and recommended action shells.
3. Ask the SLM for structured report fields.
4. Validate JSON with Pydantic.
5. Populate `FinalReport` and recommended action details.
6. Preserve confidence scores and source evidence references.

**State updates:**

- `suspected_causes`
- `recommended_actions`
- `confidence_scores`
- `final_report`

## Hallucination Control

The project reduces hallucination risk through four controls:

1. **Tool-first architecture:** deterministic tools extract facts before SLM reasoning.
2. **Grounded prompts:** prompts include local artifacts, evidence IDs, finding IDs, and check IDs.
3. **Strict JSON contracts:** every SLM-backed agent must return a schema-valid JSON object.
4. **Pydantic validation:** malformed or incomplete SLM output raises an error and does not update state.

This design makes the SLM useful for interpretation and synthesis while keeping factual detection grounded in local, inspectable artifacts.

## State Management

All agents communicate through the shared `TriageState` model. The workflow passes a typed state object from one LangGraph node to the next, so each agent sees the accumulated context from previous agents.

Key state fields include:

- `metadata`
- `artifacts`
- `observed_failures`
- `build_test_findings`
- `config_findings`
- `dependency_findings`
- `evidence`
- `validated_checks`
- `suspected_causes`
- `recommended_actions`
- `confidence_scores`
- `final_report`
- `trace_events`

The Pydantic model uses strict validation and forbids unexpected fields, which prevents loosely structured state from entering the workflow.

## Observability and AgentOps

The workflow writes JSONL trace events for each stage:

```text
coordinator.incident_loaded
build_test_analyzer.completed
infra_config_analyzer.completed
remediation_planner.completed
workflow.complete
```

Each trace event records the agent, event type, message, timestamp, and metadata such as finding counts, SLM evidence counts, action counts, and final classification. This makes the MAS auditable during demos and evaluation.

## Evaluation Strategy

The project uses three fixture incidents:

| Fixture | Expected Classification |
|---|---|
| `incident_001` | `environment_issue` |
| `incident_002_dependency_failure` | `dependency_issue` |
| `incident_003_ci_config_failure` | `ci_config_issue` |

The evaluator script checks:

- expected vs actual final classification
- final report exists
- recommended actions exist
- SLM-backed evidence exists for each interpretation agent
- trace files are written

Command:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_fixtures.py
```

Expected result:

```text
incident_001                             PASS environment_issue
incident_002_dependency_failure          PASS dependency_issue
incident_003_ci_config_failure           PASS ci_config_issue

3 passed, 0 failed
```

## Assignment Criteria Mapping

| Assignment Criterion | Project Evidence |
|---|---|
| Multi-agent orchestration | Four LangGraph nodes execute as a sequential MAS pipeline |
| Tool usage | Custom Python tools read files, parse logs, validate CI YAML, inspect Dockerfile and dependencies |
| State management | `TriageState` carries global state across agents |
| Observability | JSONL traces capture agent-stage execution |
| Local SLM usage | Ollama-backed structured prompts; no paid cloud APIs |
| Testing/evaluation | Unit tests, smoke script, and fixture evaluator |
| Concrete solution | JSON/Markdown incident report with classification, root cause, evidence, and actions |

## Suggested Individual Contribution Mapping

For a four-student team, the system can be divided as follows:

| Student | Agent Contribution | Tool Contribution | Evaluation Contribution |
|---|---|---|---|
| Student 1 | Coordinator Agent | Artifact loader / metadata extraction | Incident loading and state initialization tests |
| Student 2 | Build/Test Analyzer Agent | Build log parser | Log classification and evidence-linking tests |
| Student 3 | Infra/Config Analyzer Agent | CI config validator, Dockerfile/dependency inspectors | Config/dependency fixture assertions |
| Student 4 | Remediation Planner Agent | Report exporter / evaluator | Final report, structured JSON, and evaluation harness tests |

