"""Interactive CLI for the Multi-Agent CI/CD Failure Triage System.

Default entrypoint: agent workspace REPL (`triage>` prompt).
Use `--menu` for the legacy numbered menu (full-cycle workflows).
"""

from __future__ import annotations

import argparse
import cmd
import json
import os
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.cli_ui import (  # noqa: E402
    Spinner,
    ascii_panel,
    ascii_rule,
    explain_exception,
    filter_findings_by_text,
    filter_observed_failures,
    find_evidence_by_id,
    format_evidence_ids_for_failure,
    format_root_cause_block,
    format_summary_table,
    format_trace_timeline,
    severity_label,
    tour_steps,
    welcome_screen,
)
from scripts.create_incident import create_incident_package  # noqa: E402
from src.agents.build_test_analyzer_agent import (  # noqa: E402
    BuildTestAnalyzerInput,
    run_build_test_analyzer,
)
from src.agents.coordinator_agent import (  # noqa: E402
    CoordinatorInput,
    initialize_triage_state,
    run_coordinator,
)
from src.agents.infra_config_analyzer_agent import (  # noqa: E402
    InfraConfigAnalyzerInput,
    run_infra_config_analyzer,
)
from src.agents.remediation_planner_agent import (  # noqa: E402
    RemediationPlannerInput,
    run_remediation_planner,
)
from src.graph import run_triage_workflow  # noqa: E402
from src.llm.ollama_client import generate_with_ollama  # noqa: E402
from src.reporting import export_report  # noqa: E402
from src.state import AgentName, TriageState  # noqa: E402
from src.validation.state_consistency import (  # noqa: E402
    apply_state_consistency_validation,
    validate_state_consistency,
)

DEFAULT_INCIDENTS_DIR = Path(".tmp/incidents")
DEFAULT_TRACES_DIR = Path("traces")
DEFAULT_REPORTS_DIR = Path("reports")
DEFAULT_GENERATED_SAMPLES_DIR = Path(".tmp/sample_input_data")


class Color:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    RESET = "\033[0m"


def _use_color() -> bool:
    return os.environ.get("NO_COLOR") is None


def _style(text: str, *styles: str) -> str:
    if not _use_color():
        return text
    return "".join(styles) + text + Color.RESET


def _header(title: str, subtitle: str | None = None) -> str:
    body: list[str] = [subtitle] if subtitle else []
    return ascii_panel(title, body if body else [" "])


def _section(title: str) -> str:
    return "\n" + ascii_rule("=") + "\n" + _style(title, Color.BOLD, Color.CYAN)


def _success(message: str) -> str:
    return f"{_style('[ok]', Color.GREEN)} {message}"


def _warning(message: str) -> str:
    return f"{_style('[!]', Color.YELLOW)} {message}"


def _error(message: str) -> str:
    return f"{_style('[err]', Color.RED, Color.BOLD)} {message}"


def _path_hint(path: Path) -> str:
    return _style(str(path), Color.BLUE)

_AGENT_LABELS = {
    "coordinator": (
        "You are the triage coordinator agent. Answer using only the incident metadata "
        "and artifact inventory provided."
    ),
    "build": (
        "You are the build/test analyzer agent. Answer using only observed failures, "
        "build/test findings, and related evidence provided."
    ),
    "infra": (
        "You are the infra/configuration analyzer agent. Answer using only configuration "
        "findings, dependency findings, validated checks, and infra-related evidence "
        "provided."
    ),
    "planner": (
        "You are the remediation planner agent. Answer using only suspected causes, "
        "recommended actions, confidence scores, and final report fields provided."
    ),
    "all": (
        "You are an assistant summarizing triage workspace state from multiple agents. "
        "Answer using only the consolidated state provided."
    ),
}


def _repo_path(p: Path) -> Path:
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


@dataclass
class InteractiveSession:
    incident_dir: Path | None = None
    state: TriageState | None = None
    trace_dir: Path = field(default_factory=lambda: Path("traces"))
    report_dir: Path = field(default_factory=lambda: Path("reports"))
    verbose: bool = False
    investigate_step: int = 0


def format_state_summary(state: TriageState) -> str:
    lines = [
        f"Incident ID: {state.metadata.incident_id}",
        f"Artifacts: {len(state.artifacts)}",
        f"Observed failures: {len(state.observed_failures)}",
        f"Build/test findings: {len(state.build_test_findings)}",
        f"Config findings: {len(state.config_findings)}",
        f"Dependency findings: {len(state.dependency_findings)}",
        f"Evidence items: {len(state.evidence)}",
        f"Validated checks: {len(state.validated_checks)}",
        f"Suspected causes: {len(state.suspected_causes)}",
        f"Recommended actions: {len(state.recommended_actions)}",
        f"Confidence scores: {len(state.confidence_scores)}",
        f"Final report present: {'yes' if state.final_report else 'no'}",
    ]
    return "\n".join(lines)


def format_findings(state: TriageState) -> str:
    sections: list[str] = []

    def dump(title: str, items: Iterable[Any]) -> None:
        sections.append(f"[{title}]")
        rows = list(items)
        if not rows:
            sections.append("  (none)")
            return
        for f in rows:
            eids = ", ".join(f.evidence_ids) if f.evidence_ids else "(none)"
            sections.append(
                f"  {f.finding_id} | {f.category.value} | {f.severity.value} | "
                f"{f.summary}"
            )
            sections.append(f"    evidence_ids: {eids}")

    dump("build/test", state.build_test_findings)
    dump("config", state.config_findings)
    dump("dependency", state.dependency_findings)
    return "\n".join(sections)


def format_evidence(state: TriageState, *, verbose: bool = False) -> str:
    if not state.evidence:
        return "(no evidence)"
    lines: list[str] = []
    cap = 480 if verbose else 120
    for e in state.evidence:
        snippet = e.snippet.replace("\n", " ")
        if len(snippet) > cap:
            snippet = snippet[: cap - 3] + "..."
        lines.append(
            f"{e.evidence_id} | artifact={e.artifact_name} | agent={e.agent_name.value} | "
            f"supports={e.supports or 'N/A'} | loc={e.location or 'N/A'}"
        )
        lines.append(f"  snippet: {snippet}")
    return "\n".join(lines)


def format_checks(state: TriageState) -> str:
    if not state.validated_checks:
        return "(no checks)"
    lines: list[str] = []
    for c in state.validated_checks:
        agent = c.agent_name.value if c.agent_name else "N/A"
        eids = ", ".join(c.evidence_ids) if c.evidence_ids else "(none)"
        pf = "PASS" if c.passed else "FAIL"
        lines.append(
            f"{c.check_id} | {pf} | agent={agent} | {c.summary}\n    evidence_ids: {eids}"
        )
    return "\n".join(lines)


def format_causes(state: TriageState) -> str:
    if not state.suspected_causes:
        return "(no suspected causes)"
    lines: list[str] = []
    for c in state.suspected_causes:
        rel = ", ".join(c.related_finding_ids) if c.related_finding_ids else "(none)"
        eids = ", ".join(c.evidence_ids) if c.evidence_ids else "(none)"
        lines.append(
            f"{c.cause_id} | rank={c.rank} | confidence={c.confidence:.2f} | "
            f"findings=[{rel}] | evidence=[{eids}]"
        )
        lines.append(f"  summary: {c.summary}")
        lines.append(f"  rationale: {c.rationale}")
    return "\n".join(lines)


def format_actions(state: TriageState) -> str:
    if not state.recommended_actions:
        return "(no recommended actions)"
    lines: list[str] = []
    for a in state.recommended_actions:
        rc = ", ".join(a.related_cause_ids) if a.related_cause_ids else "(none)"
        lines.append(
            f"{a.action_id} | rank={a.rank} | risk={a.risk_level.value} | "
            f"confidence={a.confidence:.2f} | causes=[{rc}]"
        )
        lines.append(f"  summary: {a.summary}")
        if a.details:
            lines.append(f"  details: {a.details}")
    return "\n".join(lines)


def format_confidence(state: TriageState) -> str:
    if not state.confidence_scores:
        return "(no confidence scores)"
    lines: list[str] = []
    for s in state.confidence_scores:
        eids = ", ".join(s.evidence_ids) if s.evidence_ids else "(none)"
        lines.append(
            f"{s.score_id} | subject={s.subject_type.value}:{s.subject_id} | "
            f"score={s.score:.2f} | level={s.level.value} | evidence=[{eids}]"
        )
        if s.rationale:
            lines.append(f"  rationale: {s.rationale}")
    return "\n".join(lines)


def format_report(state: TriageState) -> str:
    if not state.final_report:
        return "(no final report — run planner first)"
    r = state.final_report
    lines = [
        f"classification: {r.failure_classification.value if r.failure_classification else 'N/A'}",
        f"executive_summary: {r.executive_summary or 'N/A'}",
        f"root_cause_summary: {r.root_cause_summary or 'N/A'}",
        "recommended_actions:",
    ]
    if r.recommended_actions:
        for a in r.recommended_actions:
            lines.append(f"  - {a.action_id}: {a.summary}")
    else:
        lines.append("  (none in report)")
    lines.append("evidence_summary:")
    if r.evidence_summary:
        for line in r.evidence_summary[:20]:
            lines.append(f"  - {line[:200]}")
        if len(r.evidence_summary) > 20:
            lines.append(f"  ... ({len(r.evidence_summary) - 20} more)")
    else:
        lines.append("  (none)")
    lines.append("limitations:")
    if r.limitations:
        for lim in r.limitations:
            lines.append(f"  - {lim}")
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def find_latest_trace_file(trace_dir: Path, incident_id: str) -> Path | None:
    candidate = trace_dir / f"{incident_id}.jsonl"
    return candidate if candidate.is_file() else None


def _match(q: str, *blobs: str) -> bool:
    ql = q.lower()
    return any(ql in (b or "").lower() for b in blobs if b is not None)


def _artifact_blob(name: str, rec: Any) -> str:
    parts = [name, rec.artifact_type.value, rec.status.value, rec.error_message or ""]
    return " ".join(parts)


def _build_related_evidence_ids(state: TriageState) -> set[str]:
    ids: set[str] = set()
    for f in state.build_test_findings:
        ids.update(f.evidence_ids)
    for fail in state.observed_failures:
        ids.update(fail.evidence_ids)
    return ids


def search_state(agent: str, query: str, state: TriageState) -> list[str]:
    agent_l = agent.strip().lower()
    q = query.strip()
    out: list[str] = []

    def hit(kind: str, ident: str, text: str) -> None:
        if _match(q, ident, text):
            out.append(f"[{kind}] {ident}: {text[:240]}")

    if agent_l in ("coordinator", "all"):
        hit("meta", "incident_id", state.metadata.incident_id)
        if state.metadata.title:
            hit("meta", "title", state.metadata.title)
        if state.metadata.description:
            hit("meta", "description", state.metadata.description)
        for name, rec in state.artifacts.items():
            hit("artifact", name, _artifact_blob(name, rec))

    if agent_l in ("build", "all"):
        rel_ev = _build_related_evidence_ids(state)
        for i, failure in enumerate(state.observed_failures):
            hit(
                "observed_failure",
                str(i + 1),
                f"{failure.category.value} | {failure.summary} | src={failure.source_artifact}",
            )
        for f in state.build_test_findings:
            blob = f"{f.finding_id} | {f.summary} | {f.details or ''}"
            hit("build_finding", f.finding_id, blob)
        for e in state.evidence:
            if e.agent_name == AgentName.BUILD_TEST_ANALYZER or e.evidence_id in rel_ev:
                hit("evidence", e.evidence_id, f"{e.snippet} | {e.supports or ''}")

    if agent_l in ("infra", "all"):
        for f in state.config_findings + state.dependency_findings:
            blob = f"{f.finding_id} | {f.summary} | {f.details or ''}"
            hit("infra_finding", f.finding_id, blob)
        for c in state.validated_checks:
            blob = f"{c.check_id} | {c.summary} | {c.details or ''}"
            hit("check", c.check_id, blob)
        for e in state.evidence:
            if e.agent_name == AgentName.INFRA_CONFIG_ANALYZER:
                hit("evidence", e.evidence_id, e.snippet)

    if agent_l in ("planner", "all"):
        for c in state.suspected_causes:
            hit("cause", c.cause_id, f"{c.summary} | {c.rationale}")
        for a in state.recommended_actions:
            hit("action", a.action_id, f"{a.summary} | {a.details or ''}")
        for s in state.confidence_scores:
            hit("confidence", s.score_id, f"{s.rationale or ''} | {s.subject_id}")
        if state.final_report:
            fr = state.final_report
            hit("report", "executive", fr.executive_summary or "")
            hit("report", "root_cause", fr.root_cause_summary or "")
            for lim in fr.limitations:
                hit("report", "limitation", lim)

    return out


def _truncate_json(data: Any, max_chars: int = 12000) -> str:
    text = json.dumps(data, indent=2, sort_keys=True, default=str)
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n... [truncated]"
    return text


def compact_state_for_prompt(agent: str, state: TriageState) -> dict[str, Any]:
    agent_l = agent.strip().lower()
    md = state.metadata
    base: dict[str, Any] = {
        "incident_id": md.incident_id,
        "title": md.title,
        "repository": md.repository,
    }

    if agent_l == "coordinator":
        base["artifacts"] = [
            {
                "name": a.name,
                "type": a.artifact_type.value,
                "status": a.status.value,
                "size_bytes": a.size_bytes,
                "error_message": a.error_message,
            }
            for a in state.artifacts.values()
        ]
        return base

    if agent_l == "build":
        base["observed_failures"] = [
            {
                "category": o.category.value,
                "summary": o.summary,
                "source_artifact": o.source_artifact,
                "evidence_ids": o.evidence_ids,
            }
            for o in state.observed_failures
        ]
        base["build_test_findings"] = [
            {
                "finding_id": f.finding_id,
                "category": f.category.value,
                "severity": f.severity.value,
                "summary": f.summary,
                "details": f.details,
                "evidence_ids": f.evidence_ids,
            }
            for f in state.build_test_findings
        ]
        base["evidence_build_related"] = [
            {
                "evidence_id": e.evidence_id,
                "artifact_name": e.artifact_name,
                "snippet": e.snippet[:500],
                "supports": e.supports,
            }
            for e in state.evidence
            if e.agent_name == AgentName.BUILD_TEST_ANALYZER
            or e.evidence_id in _build_related_evidence_ids(state)
        ]
        return base

    if agent_l == "infra":
        base["config_findings"] = [
            {
                "finding_id": f.finding_id,
                "category": f.category.value,
                "severity": f.severity.value,
                "summary": f.summary,
                "details": f.details,
                "evidence_ids": f.evidence_ids,
            }
            for f in state.config_findings
        ]
        base["dependency_findings"] = [
            {
                "finding_id": f.finding_id,
                "category": f.category.value,
                "severity": f.severity.value,
                "summary": f.summary,
                "details": f.details,
                "evidence_ids": f.evidence_ids,
            }
            for f in state.dependency_findings
        ]
        base["validated_checks"] = [
            {
                "check_id": c.check_id,
                "passed": c.passed,
                "summary": c.summary,
                "details": c.details,
                "evidence_ids": c.evidence_ids,
            }
            for c in state.validated_checks
        ]
        base["evidence_infra"] = [
            {
                "evidence_id": e.evidence_id,
                "artifact_name": e.artifact_name,
                "snippet": e.snippet[:500],
                "supports": e.supports,
            }
            for e in state.evidence
            if e.agent_name == AgentName.INFRA_CONFIG_ANALYZER
        ]
        return base

    if agent_l == "planner":
        base["suspected_causes"] = [
            {
                "cause_id": c.cause_id,
                "rank": c.rank,
                "confidence": c.confidence,
                "summary": c.summary,
                "rationale": c.rationale,
                "related_finding_ids": c.related_finding_ids,
                "evidence_ids": c.evidence_ids,
            }
            for c in state.suspected_causes
        ]
        base["recommended_actions"] = [
            {
                "action_id": a.action_id,
                "rank": a.rank,
                "risk_level": a.risk_level.value,
                "confidence": a.confidence,
                "summary": a.summary,
                "details": a.details,
                "related_cause_ids": a.related_cause_ids,
            }
            for a in state.recommended_actions
        ]
        base["confidence_scores"] = [
            {
                "score_id": s.score_id,
                "subject_type": s.subject_type.value,
                "subject_id": s.subject_id,
                "score": s.score,
                "level": s.level.value,
                "rationale": s.rationale,
                "evidence_ids": s.evidence_ids,
            }
            for s in state.confidence_scores
        ]
        if state.final_report:
            fr = state.final_report
            base["final_report"] = {
                "classification": fr.failure_classification.value
                if fr.failure_classification
                else None,
                "executive_summary": fr.executive_summary,
                "root_cause_summary": fr.root_cause_summary,
                "evidence_summary": fr.evidence_summary[:30],
                "limitations": fr.limitations,
                "recommended_action_ids": [a.action_id for a in fr.recommended_actions],
            }
        return base

    merged: dict[str, Any] = {
        "coordinator": compact_state_for_prompt("coordinator", state),
        "build": compact_state_for_prompt("build", state),
        "infra": compact_state_for_prompt("infra", state),
        "planner": compact_state_for_prompt("planner", state),
    }
    return merged


def build_agent_question_prompt(agent: str, question: str, state: TriageState) -> str:
    agent_l = agent.strip().lower()
    if agent_l not in _AGENT_LABELS:
        raise ValueError(f"unknown agent for ask: {agent!r}")

    persona = _AGENT_LABELS[agent_l]
    payload = compact_state_for_prompt(agent_l, state)
    constraints = (
        "Constraints:\n"
        "- Answer ONLY from the provided state summary.\n"
        "- Cite finding/evidence/cause/action/confidence IDs where possible.\n"
        "- Do NOT invent findings, evidence, or IDs not present in the state.\n"
        "- If the state is insufficient to answer the question, say so explicitly.\n"
        "- Keep the answer concise.\n"
    )
    summary = _truncate_json(payload)
    return (
        f"{persona}\n\n"
        f"Current question:\n{question.strip()}\n\n"
        f"State summary (JSON):\n{summary}\n\n"
        f"{constraints}"
    )


def answer_agent_question(agent: str, question: str, state: TriageState) -> str:
    prompt = build_agent_question_prompt(agent, question, state)
    return generate_with_ollama(prompt)


def _trace_events_from_jsonl(path: Path, limit: int = 40) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return events[-limit:]


def _find_latest_report() -> Path | None:
    reports_dir = REPO_ROOT / DEFAULT_REPORTS_DIR
    if not reports_dir.exists():
        return None
    latest: Path | None = None
    latest_mtime = 0.0
    for report_file in reports_dir.glob("**/report.md"):
        mtime = report_file.stat().st_mtime
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest = report_file
    return latest


def _read_trace_events(incident_id: str) -> list[dict[str, Any]]:
    trace_file = REPO_ROOT / DEFAULT_TRACES_DIR / f"{incident_id}.jsonl"
    events: list[dict[str, Any]] = []
    if not trace_file.exists():
        return events
    try:
        with open(trace_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError as e:
        print(f"Error reading trace file: {e}")
    return events


def _format_trace_event(event: dict[str, Any]) -> str:
    lines = [
        f"  Event ID: {event.get('event_id', 'N/A')}",
        f"  Type: {event.get('event_type', 'N/A')}",
    ]
    if agent_name := event.get("agent_name"):
        lines.append(f"  Agent: {agent_name}")
    if message := event.get("message"):
        lines.append(f"  Message: {message}")
    if metadata := event.get("metadata"):
        lines.append("  Metadata:")
        for key, value in metadata.items():
            lines.append(f"    {key}: {value}")
    return "\n".join(lines)


def _get_user_input(prompt: str, default: str | None = None) -> str:
    display_prompt = f"{prompt} [{default}]: " if default else f"{prompt}: "
    try:
        user_input = input(display_prompt).strip()
        return user_input if user_input else (default or "")
    except (EOFError, KeyboardInterrupt):
        return ""


def _get_yes_no(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    response = _get_user_input(f"{prompt} ({default_str})", "").lower()
    if response in ("y", "yes"):
        return True
    if response in ("n", "no"):
        return False
    return default


def guide_text() -> str:
    return "\n".join(
        [
            _header(
                "CI/CD Failure Triage Guide",
                "Package artifacts, run agents, export evidence-backed reports",
            ),
            _section("Regular User Flow"),
            "  1. Generate sample input data or create an incident package from your repo.",
            "  2. Run triage to classify the failure and collect supporting evidence.",
            "  3. Review suspected causes, recommended actions, reports, and trace events.",
            "  4. Export the Markdown/JSON report for assignment submission or demo review.",
            _section("Expected Incident Folder"),
            "  incident.json      Metadata: incident_id, title, repository, branch, run_id",
            "  build.log          CI build output or command capture",
            "  test-report.txt    Unit/integration test output",
            "  ci.yml             GitHub Actions/GitLab CI style workflow file",
            "  Dockerfile         Optional container build context",
            "  requirements.txt   Optional Python dependency input",
            _section("Assignment Alignment"),
            "  • Multi-agent workflow: coordinator, build/test, infra/config, planner.",
            "  • Deterministic tools inspect logs, CI config, Dockerfile, and dependencies.",
            "  • Local Ollama-backed agents produce structured interpretations.",
            "  • Reports include classification, evidence, causes, confidence, and actions.",
            _section("Useful Commands"),
            f"  {_style('Guided menu (--menu):', Color.BOLD)} {sys.argv[0]} --menu",
            "  "
            f"{_style('Direct triage:', Color.BOLD)} "
            ".\\.venv\\Scripts\\python.exe -m src.main "
            "fixtures\\sample_incidents\\incident_001 --trace-dir traces --report-dir reports",
            f"  {_style('Workspace REPL:', Color.BOLD)} "
            "guide | sample | load … | run all | export",
        ]
    )


def create_sample_input_data(
    output_root: Path,
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Create sample incident input folders for demos and assignment evaluation."""
    scenarios: dict[str, dict[str, str]] = {
        "sample_test_failure": {
            "incident.json": json.dumps(
                {
                    "incident_id": "sample_test_failure",
                    "title": "Pytest failure after database test rollout",
                    "description": (
                        "CI failed during unit tests because DATABASE_URL is missing "
                        "from the test environment."
                    ),
                    "repository": "demo-payments-api",
                    "branch": "feature/db-tests",
                    "commit_sha": "abc1234",
                    "pipeline_name": "pull-request",
                    "run_id": "sample-001",
                },
                indent=2,
            ),
            "build.log": "\n".join(
                [
                    "$ python -m pytest",
                    "==================== test session starts ====================",
                    "tests/test_checkout.py::test_checkout_creates_order FAILED",
                    "E   RuntimeError: DATABASE_URL environment variable is not set",
                    "FAILED tests/test_checkout.py::test_checkout_creates_order",
                    "exit_code=1",
                ]
            )
            + "\n",
            "test-report.txt": "\n".join(
                [
                    "1 failed, 22 passed in 4.18s",
                    "Failure: test_checkout_creates_order",
                    "Root symptom: DATABASE_URL environment variable is not set",
                ]
            )
            + "\n",
            "ci.yml": "\n".join(
                [
                    "name: pull-request",
                    "on: [pull_request]",
                    "jobs:",
                    "  test:",
                    "    runs-on: ubuntu-latest",
                    "    steps:",
                    "      - uses: actions/checkout@v4",
                    "      - uses: actions/setup-python@v5",
                    "        with:",
                    "          python-version: '3.12'",
                    "      - run: pip install -r requirements.txt",
                    "      - run: python -m pytest",
                ]
            )
            + "\n",
            "Dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\n",
            "requirements.txt": "pytest==8.3.2\npydantic==2.8.2\n",
        },
        "sample_dependency_failure": {
            "incident.json": json.dumps(
                {
                    "incident_id": "sample_dependency_failure",
                    "title": "Dependency install failure in CI",
                    "description": (
                        "Pipeline failed before tests because the dependency lock "
                        "requests incompatible package versions."
                    ),
                    "repository": "demo-inventory-service",
                    "branch": "renovate/fastapi",
                    "commit_sha": "def5678",
                    "pipeline_name": "main",
                    "run_id": "sample-002",
                },
                indent=2,
            ),
            "build.log": "\n".join(
                [
                    "$ python -m pip install -r requirements.txt",
                    "ERROR: Cannot install fastapi==0.115.0 and pydantic==1.10.15",
                    "because these package versions have conflicting dependencies.",
                    "ResolutionImpossible",
                    "exit_code=1",
                ]
            )
            + "\n",
            "test-report.txt": "Tests did not run because dependency installation failed.\n",
            "ci.yml": "\n".join(
                [
                    "name: main",
                    "on: [push]",
                    "jobs:",
                    "  build:",
                    "    runs-on: ubuntu-latest",
                    "    steps:",
                    "      - uses: actions/checkout@v4",
                    "      - run: python -m pip install -r requirements.txt",
                    "      - run: python -m pytest",
                ]
            )
            + "\n",
            "Dockerfile": (
                "FROM python:3.12-slim\n"
                "COPY requirements.txt .\n"
                "RUN pip install -r requirements.txt\n"
            ),
            "requirements.txt": "fastapi==0.115.0\npydantic==1.10.15\npytest==8.3.2\n",
        },
        "sample_ci_config_failure": {
            "incident.json": json.dumps(
                {
                    "incident_id": "sample_ci_config_failure",
                    "title": "CI workflow references missing setup step",
                    "description": (
                        "Build failed because the workflow runs Python commands before "
                        "setting up the expected Python runtime."
                    ),
                    "repository": "demo-worker",
                    "branch": "ci/update",
                    "commit_sha": "fed9012",
                    "pipeline_name": "ci",
                    "run_id": "sample-003",
                },
                indent=2,
            ),
            "build.log": "\n".join(
                [
                    "$ python -m pytest",
                    "python: command not found",
                    "Process completed with exit code 127.",
                ]
            )
            + "\n",
            "test-report.txt": "Tests did not run because Python was unavailable on the runner.\n",
            "ci.yml": "\n".join(
                [
                    "name: ci",
                    "on: [push]",
                    "jobs:",
                    "  test:",
                    "    runs-on: ubuntu-latest",
                    "    steps:",
                    "      - uses: actions/checkout@v4",
                    "      - run: python -m pytest",
                ]
            )
            + "\n",
            "Dockerfile": "FROM python:3.12-slim\nWORKDIR /app\n",
            "requirements.txt": "pytest==8.3.2\n",
        },
    }

    output_root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for scenario_name, files in scenarios.items():
        scenario_dir = output_root / scenario_name
        if scenario_dir.exists() and any(scenario_dir.iterdir()) and not overwrite:
            continue
        scenario_dir.mkdir(parents=True, exist_ok=True)
        for file_name, content in files.items():
            (scenario_dir / file_name).write_text(content, encoding="utf-8")
        created.append(scenario_dir)
    return created


def _resolve_incident_arg(raw: str) -> Path:
    text = raw.strip().strip('"').strip("'")
    p = Path(text).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    else:
        p = p.resolve()
    return p


def session_perform_load(session: InteractiveSession, incident_raw: str) -> tuple[bool, str]:
    """Load incident directory and initialize coordinator state."""
    path = _resolve_incident_arg(incident_raw)
    if not path.is_dir():
        return False, f"Not a directory or missing: {path}"
    trace_abs = _repo_path(session.trace_dir)
    trace_abs.mkdir(parents=True, exist_ok=True)
    try:
        session.incident_dir = path
        inp = CoordinatorInput(incident_dir=path, trace_dir=trace_abs)
        with Spinner("load: coordinator + artifacts (Ollama)"):
            session.state = initialize_triage_state(inp)
    except Exception as exc:
        session.state = None
        title, hints = explain_exception(exc)
        hint_lines = "\n".join(f"  -> {h}" for h in hints)
        return False, f"{title}\n({type(exc).__name__}: {exc})\n{hint_lines}"

    acount = len(session.state.artifacts)
    title = session.state.metadata.title or "(no title)"
    msg = (
        f"Loaded incident {session.state.metadata.incident_id}\n"
        f"Title: {title}\nArtifacts: {acount}"
    )
    return True, msg


def session_run_coordinator(session: InteractiveSession) -> tuple[bool, str]:
    if session.incident_dir is None:
        return False, "No incident directory. Use load <incident_dir> first."
    trace_abs = _repo_path(session.trace_dir)
    trace_abs.mkdir(parents=True, exist_ok=True)
    try:
        inp = CoordinatorInput(incident_dir=session.incident_dir, trace_dir=trace_abs)
        with Spinner("coordinator: loading artifacts + incident context (Ollama)"):
            session.state = run_coordinator(inp)
    except Exception as exc:
        title, hints = explain_exception(exc)
        hint_lines = "\n".join(f"  -> {h}" for h in hints)
        return False, f"{title}\n({type(exc).__name__}: {exc})\n{hint_lines}"
    sid = session.state.metadata.incident_id
    n_art = len(session.state.artifacts)
    return True, (
        "Coordinator finished — state reset from deterministic load + coordinator LLM.\n"
        f"Incident: {sid} | artifacts: {n_art}"
    )


class AgentWorkspaceShell(cmd.Cmd):
    intro = ""
    prompt = _style("triage", Color.BOLD, Color.CYAN) + _style("> ", Color.DIM)
    repeat_empty = False

    def __init__(self, session: InteractiveSession | None = None) -> None:
        super().__init__()
        self.session = session or InteractiveSession()

    def onecmd(self, line: str) -> bool:
        try:
            return super().onecmd(line)
        except KeyboardInterrupt:
            print("^C")
            return False
        except Exception as exc:
            title, hints = explain_exception(exc)
            print(_error(title))
            print(f"({type(exc).__name__}: {exc})")
            for h in hints:
                print(f"  -> {h}")
            return False

    def default(self, line: str) -> None:
        print(f"Unknown command: {line!r}. Try:  help  |  tour  |  load  |  summary")

    def emptyline(self) -> bool:
        return False

    def do_help(self, arg: str) -> None:
        if arg:
            super().do_help(arg)
            return
        lines = [
            "Core:",
            "  load <incident_dir>        attach package (aliases: l)",
            "  run coordinator|build|infra|planner|validator|all   (alias: r)",
            "  summary                    concise triage + root cause + fixes",
            "  investigate [next|back|reset]   step through failures -> remediation",
            "  timeline [N]              last N trace events (default ~40)",
            "  find failures [text]      filter observed failures",
            "  find findings [text]      filter findings",
            "  show evidence <id>        one evidence item (longer snippet if verbose on)",
            "",
            "State views:",
            "  state | artifacts | failures | findings | evidence [-v] | checks",
            "  causes | actions | confidence | report | trace | export",
            "",
            "LLM / search:",
            "  inspect <agent> <query>   substring search (no Ollama)",
            "  ask <agent> <question>    Ollama Q&A — agents: coordinator|build|infra|planner|all",
            "",
            "Session:",
            "  set verbose on|off        longer evidence snippets in evidence / investigate",
            "  set traces <path>         JSONL trace output directory",
            "  set reports <path>        export directory for reports",
            "  welcome | tour | menu | guide | sample",
            "",
            "Examples:",
            "  load fixtures/sample_incidents/incident_001",
            "  run all",
            "  summary",
            "  find failures environment",
            "  ask build What is the primary symptom?",
            "",
            "  exit | quit",
            f"  Full menu:  {sys.argv[0]} --menu",
        ]
        print(ascii_panel("triage> help", lines))

    def do_l(self, arg: str) -> None:
        self.do_load(arg)

    def do_r(self, arg: str) -> None:
        self.do_run(arg)

    def do_EOF(self, arg: str) -> bool:
        print()
        return True

    def do_exit(self, arg: str) -> bool:
        return True

    def do_quit(self, arg: str) -> bool:
        return True

    def do_load(self, arg: str) -> None:
        if not arg.strip():
            print("usage: load <incident_dir>")
            return
        ok, msg = session_perform_load(self.session, arg)
        if ok:
            first, *rest = msg.split("\n")
            print(_success(first))
            for line in rest:
                print(f"     {line}")
        else:
            print(_error(msg))

    def do_guide(self, arg: str) -> None:
        print(guide_text())

    def do_welcome(self, arg: str) -> None:
        print(welcome_screen())

    def do_tour(self, arg: str) -> None:
        for title, bullets in tour_steps():
            print(ascii_panel(title, bullets))

    def do_menu(self, arg: str) -> None:
        lines = [
            "A) sample  ->  load <path>  ->  run all  ->  summary  ->  export",
            "B) inspect <agent> <keyword>  — search loaded state (no LLM)",
            "C) ask planner <question>     — Ollama Q&A on planner slice",
            "D) timeline                   — trace of agent/tool steps",
            "E) investigate next           — walk through triage layers",
            "",
            f"Full-screen menu:  {sys.argv[0]} --menu",
        ]
        print(ascii_panel("Common workflows", lines))

    def do_summary(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        s = self.session.state
        print(format_summary_table(s))
        print()
        print(format_root_cause_block(s))
        print()
        print(f"Failure-linked evidence: {format_evidence_ids_for_failure(s)}")

    def do_timeline(self, arg: str) -> None:
        limit = 40
        if arg.strip().isdigit():
            limit = max(5, min(200, int(arg.strip())))
        events: list[dict[str, Any]] = []
        trace_abs = _repo_path(self.session.trace_dir)
        iid = self.session.state.metadata.incident_id if self.session.state else None
        if iid:
            tf = find_latest_trace_file(trace_abs, iid)
            if tf:
                events = _trace_events_from_jsonl(tf, limit=max(120, limit * 3))
        if not events and self.session.state and self.session.state.trace_events:
            events = [e.model_dump(mode="json") for e in self.session.state.trace_events]
        if not events:
            print(
                "No timeline data. Load an incident, run agents, or check trace_dir "
                f"({self.session.trace_dir})."
            )
            return
        print(format_trace_timeline(events, limit=limit))

    def do_investigate(self, arg: str) -> None:
        parts = arg.strip().split()
        if self.session.state is None:
            print("No state loaded.")
            return
        sub = parts[0].lower() if parts else ""
        if sub == "next":
            self.session.investigate_step = min(4, self.session.investigate_step + 1)
        elif sub == "back":
            self.session.investigate_step = max(0, self.session.investigate_step - 1)
        elif sub == "reset":
            self.session.investigate_step = 0
        elif sub in ("help", "?"):
            print("usage: investigate [next | back | reset]")
            return
        elif sub:
            print("usage: investigate [next | back | reset]")
            return
        self._print_investigate_step()

    def _print_investigate_step(self) -> None:
        s = self.session.state
        if s is None:
            return
        step = self.session.investigate_step
        labels = ["Overview", "Observed failures", "Findings", "Evidence headlines", "Remediation"]
        title = f"Step {step + 1}/5 — {labels[step]}"
        lines: list[str] = []
        if step == 0:
            lines.extend(format_summary_table(s).split("\n"))
            lines.append("")
            lines.extend(format_root_cause_block(s).split("\n"))
            lines.append("")
            lines.append(f"Failure-linked evidence ids: {format_evidence_ids_for_failure(s)}")
        elif step == 1:
            if not s.observed_failures:
                lines.append("(no observed failures — run build)")
            for i, fail in enumerate(s.observed_failures, 1):
                eids = ", ".join(fail.evidence_ids) if fail.evidence_ids else "(none)"
                lines.append(f"{i}. [{fail.category.value}] {fail.summary}")
                lines.append(f"   source={fail.source_artifact or 'n/a'}  evidence={eids}")
        elif step == 2:
            all_f = s.build_test_findings + s.config_findings + s.dependency_findings
            if not all_f:
                lines.append("(no findings — run build / infra)")
            for f in all_f[:15]:
                lines.append(
                    f"{f.finding_id} | {f.category.value} | "
                    f"{severity_label(f.severity.value)} | {f.summary[:72]}"
                )
            if len(all_f) > 15:
                lines.append(f"... ({len(all_f) - 15} more — use findings)")
        elif step == 3:
            cap = 12
            lines.append(
                f"Up to {cap} items (set verbose on + evidence -v for longer snippets)."
            )
            for e in s.evidence[:cap]:
                sn = e.snippet.replace("\n", " ")
                if len(sn) > 72:
                    sn = sn[:69] + "..."
                lines.append(f"{e.evidence_id} | {e.agent_name.value} | {sn}")
        else:
            lines.extend(format_root_cause_block(s).split("\n"))
            lines.append("")
            if s.final_report and s.final_report.executive_summary:
                lines.append("Executive summary:")
                es = s.final_report.executive_summary
                lines.append(es[:400] + ("..." if len(es) > 400 else ""))
        print(ascii_panel(title, lines))
        print(
            _style(
                "Commands: investigate next | investigate back | investigate reset",
                Color.DIM,
            )
        )

    def do_find(self, arg: str) -> None:
        parts = arg.strip().split(maxsplit=1)
        if len(parts) < 1 or parts[0].lower() not in ("failures", "findings"):
            print("usage: find failures [substring]  |  find findings [substring]")
            return
        if self.session.state is None:
            print("No state loaded.")
            return
        kind = parts[0].lower()
        needle = parts[1] if len(parts) > 1 else ""
        if kind == "failures":
            rows = filter_observed_failures(self.session.state, needle)
            if not rows:
                print("(no matches)")
                return
            for i, fail in enumerate(rows, 1):
                print(
                    f"{i}. [{fail.category.value}] {fail.summary}\n"
                    f"   evidence: {', '.join(fail.evidence_ids) or '(none)'}"
                )
        else:
            rows = filter_findings_by_text(self.session.state, needle)
            if not rows:
                print("(no matches)")
                return
            for i, f in enumerate(rows, 1):
                print(
                    f"{i}. {f.finding_id} | {f.category.value} | "
                    f"{severity_label(f.severity.value)} | {f.summary}"
                )

    def do_show(self, arg: str) -> None:
        # Cmd passes only text after the command name (e.g. "evidence ev-001").
        parts = arg.strip().split()
        if len(parts) < 2 or parts[0].lower() != "evidence":
            print("usage: show evidence <evidence_id>")
            return
        if self.session.state is None:
            print("No state loaded.")
            return
        eid = parts[1].strip()
        item = find_evidence_by_id(self.session.state, eid)
        if item is None:
            print(_error(f"No evidence with id {eid!r}. Try:  evidence"))
            return
        cap = 2000 if self.session.verbose else 600
        sn = item.snippet.replace("\n", " ")
        if len(sn) > cap:
            sn = sn[: cap - 3] + "..."
        body = [
            f"id={item.evidence_id}  artifact={item.artifact_name}  agent={item.agent_name.value}",
            f"supports={item.supports or 'N/A'}  location={item.location or 'N/A'}",
            "",
            sn,
        ]
        print(ascii_panel(f"Evidence {item.evidence_id}", body))

    def do_set(self, arg: str) -> None:
        t = arg.strip()
        if not t:
            print("usage: set verbose on|off  |  set traces <path>  |  set reports <path>")
            return
        low = t.lower()
        if low.startswith("verbose"):
            rest = t[7:].strip().lower()
            if not rest:
                print(f"verbose = {self.session.verbose}")
                return
            self.session.verbose = rest in ("on", "true", "1", "yes")
            print(_success(f"verbose = {self.session.verbose}"))
            return
        if low.startswith("traces "):
            self.session.trace_dir = Path(t[7:].strip())
            print(_success(f"trace_dir = {self.session.trace_dir}"))
            return
        if low.startswith("reports "):
            self.session.report_dir = Path(t[8:].strip())
            print(_success(f"report_dir = {self.session.report_dir}"))
            return
        print("usage: set verbose on|off  |  set traces <path>  |  set reports <path>")

    def do_sample(self, arg: str) -> None:
        output_root = _repo_path(DEFAULT_GENERATED_SAMPLES_DIR)
        overwrite = arg.strip().lower() in {"--overwrite", "overwrite", "-f"}
        created = create_sample_input_data(output_root, overwrite=overwrite)
        if created:
            print(_success(f"Generated {len(created)} sample incident folders."))
            for path in created:
                print(f"  - {_path_hint(path)}")
        else:
            print(_warning(f"Sample folders already exist at {_path_hint(output_root)}."))
            print("Run sample --overwrite to refresh them.")

    def do_run(self, arg: str) -> None:
        parts = arg.strip().split(maxsplit=1)
        if not parts:
            print("usage: run coordinator|build|infra|planner|validator|all|pipeline")
            return
        sub = parts[0].lower()
        if sub in ("pipeline", "full"):
            sub = "all"
        handlers = {
            "coordinator": self._run_coordinator_step,
            "build": self._run_build_step,
            "infra": self._run_infra_step,
            "planner": self._run_planner_step,
            "validator": self._run_validator_step,
            "all": self._run_all_steps,
        }
        fn = handlers.get(sub)
        if not fn:
            print(f"Unknown run target: {sub!r}")
            return
        fn()

    def _run_coordinator_step(self) -> None:
        print(
            "WARNING: Re-running coordinator replaces current analysis state "
            "with a fresh deterministic load + coordinator LLM pass."
        )
        ok, msg = session_run_coordinator(self.session)
        print(msg)

    def _run_build_step(self) -> None:
        if self.session.state is None:
            print("No state. Use load <incident_dir> first.")
            return
        try:
            with Spinner("build/test analyzer (parse logs + Ollama)"):
                self.session.state = run_build_test_analyzer(
                    BuildTestAnalyzerInput(state=self.session.state)
                )
            s = self.session.state
            print(
                f"Build/test analyzer done.\n"
                f"Observed failures: {len(s.observed_failures)}\n"
                f"Build/test findings: {len(s.build_test_findings)}\n"
                f"Evidence items (total): {len(s.evidence)}"
            )
        except Exception as exc:
            title, hints = explain_exception(exc)
            print(_error(f"Build/test analyzer: {title}"))
            for h in hints:
                print(f"  -> {h}")

    def _run_infra_step(self) -> None:
        if self.session.state is None:
            print("No state. Use load <incident_dir> first.")
            return
        try:
            with Spinner("infra/config analyzer (CI + Dockerfile + deps + Ollama)"):
                self.session.state = run_infra_config_analyzer(
                    InfraConfigAnalyzerInput(state=self.session.state)
                )
            s = self.session.state
            print(
                f"Infra/config analyzer done.\n"
                f"Config findings: {len(s.config_findings)}\n"
                f"Dependency findings: {len(s.dependency_findings)}\n"
                f"Validated checks (total): {len(s.validated_checks)}"
            )
        except Exception as exc:
            title, hints = explain_exception(exc)
            print(_error(f"Infra analyzer: {title}"))
            for h in hints:
                print(f"  -> {h}")

    def _run_planner_step(self) -> None:
        if self.session.state is None:
            print("No state. Use load <incident_dir> first.")
            return
        try:
            with Spinner("remediation planner (Ollama + deterministic plan)"):
                self.session.state = run_remediation_planner(
                    RemediationPlannerInput(state=self.session.state)
                )
            s = self.session.state
            print(
                f"Remediation planner done.\n"
                f"Suspected causes: {len(s.suspected_causes)}\n"
                f"Recommended actions: {len(s.recommended_actions)}\n"
                f"Confidence scores: {len(s.confidence_scores)}"
            )
        except Exception as exc:
            title, hints = explain_exception(exc)
            print(_error(f"Planner: {title}"))
            for h in hints:
                print(f"  -> {h}")

    def _run_validator_step(self) -> None:
        if self.session.state is None:
            print("No state. Use load <incident_dir> first.")
            return
        try:
            self.session.state = apply_state_consistency_validation(self.session.state)
            result = validate_state_consistency(self.session.state)
            status = "PASSED" if result.passed else "FAILED"
            print(
                f"State consistency: {status}\n"
                f"errors: {len(result.errors)} | warnings: {len(result.warnings)}"
            )
        except Exception as exc:
            title, hints = explain_exception(exc)
            print(_error(f"Validator: {title}"))
            for h in hints:
                print(f"  -> {h}")

    def _run_all_steps(self) -> None:
        if self.session.state is None:
            if self.session.incident_dir is None:
                print("Load an incident first: load <incident_dir>")
                return
            print("Initializing coordinator (init-only) before pipeline...")
            trace_abs = _repo_path(self.session.trace_dir)
            trace_abs.mkdir(parents=True, exist_ok=True)
            try:
                inp = CoordinatorInput(
                    incident_dir=self.session.incident_dir,
                    trace_dir=trace_abs,
                )
                with Spinner("coordinator: initialize triage state (Ollama)"):
                    self.session.state = initialize_triage_state(inp)
            except Exception as exc:
                title, hints = explain_exception(exc)
                print(_error(title))
                for h in hints:
                    print(f"  -> {h}")
                return

        for label, fn in (
            ("build", self._run_build_step),
            ("infra", self._run_infra_step),
            ("planner", self._run_planner_step),
            ("validator", self._run_validator_step),
        ):
            print(f"--- run {label} ---")
            fn()
            if self.session.state is None:
                print(f"Stopped after {label} due to missing state.")
                return

        if self.session.state:
            print(format_state_summary(self.session.state))

    def do_state(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        print(format_state_summary(self.session.state))

    def do_artifacts(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        for name, rec in self.session.state.artifacts.items():
            err = rec.error_message or ""
            size = rec.size_bytes if rec.size_bytes is not None else "?"
            print(
                f"{name} | type={rec.artifact_type.value} | status={rec.status.value} | "
                f"size={size} | error={err or 'none'}"
            )

    def do_failures(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        if not self.session.state.observed_failures:
            print("(no observed failures)")
            return
        for fail in self.session.state.observed_failures:
            eids = ", ".join(fail.evidence_ids) if fail.evidence_ids else "(none)"
            print(
                f"{fail.category.value} | {fail.summary}\n"
                f"  source={fail.source_artifact or 'N/A'} | evidence_ids={eids}"
            )

    def do_findings(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        print(format_findings(self.session.state))

    def do_evidence(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        parts = arg.strip().split()
        verbose = self.session.verbose
        if "-v" in parts or "--verbose" in parts:
            verbose = True
        print(format_evidence(self.session.state, verbose=verbose))

    def do_checks(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        print(format_checks(self.session.state))

    def do_causes(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        print(format_causes(self.session.state))

    def do_actions(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        print(format_actions(self.session.state))

    def do_confidence(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        print(format_confidence(self.session.state))

    def do_report(self, arg: str) -> None:
        if self.session.state is None:
            print("No state loaded.")
            return
        print(format_report(self.session.state))

    def do_trace(self, arg: str) -> None:
        trace_abs = _repo_path(self.session.trace_dir)
        lines: list[str] = []
        if self.session.state and self.session.state.trace_events:
            lines.append(
                f"In-memory trace_events: {len(self.session.state.trace_events)} "
                "(latest few omitted if file exists)"
            )
        else:
            lines.append("In-memory trace_events: none")

        iid = (
            self.session.state.metadata.incident_id
            if self.session.state
            else None
        )
        if iid:
            tf = find_latest_trace_file(trace_abs, iid)
            if tf:
                tail = _trace_events_from_jsonl(tf, limit=25)
                lines.append(f"Trace file {tf} (showing last {len(tail)} JSON objects):")
                for ev in tail:
                    et = ev.get("event_type", "?")
                    mid = ev.get("event_id", "?")
                    msg = str(ev.get("message", ""))[:120]
                    lines.append(f"  {mid} | {et} | {msg}")
            else:
                lines.append(f"No trace file at {trace_abs / (iid + '.jsonl')}")
        print("\n".join(lines))

    def do_export(self, arg: str) -> None:
        if self.session.state is None:
            print("No state to export.")
            return
        report_abs = _repo_path(self.session.report_dir)
        trace_abs = _repo_path(self.session.trace_dir)
        report_abs.mkdir(parents=True, exist_ok=True)
        iid = self.session.state.metadata.incident_id
        trace_file = trace_abs / f"{iid}.jsonl"
        tf_arg = trace_file if trace_file.exists() else None
        try:
            result = export_report(self.session.state, report_abs, trace_file=tf_arg)
            print(f"Summary JSON: {result.summary_json_path}")
            print(f"Markdown report: {result.markdown_report_path}")
        except Exception as exc:
            print(f"Export failed: {exc}")

    def do_inspect(self, arg: str) -> None:
        parts = arg.strip().split(maxsplit=1)
        if len(parts) < 2:
            print("usage: inspect <agent> <query>")
            print("Agents: coordinator | build | infra | planner | all")
            return
        agent_key, query = parts[0].lower(), parts[1]
        if agent_key not in _AGENT_LABELS:
            print(f"Unknown agent: {agent_key!r}")
            return
        if self.session.state is None:
            print("No state loaded.")
            return
        hits = search_state(agent_key, query, self.session.state)
        if not hits:
            print("(no matches)")
            return
        for line in hits[:80]:
            print(line)
        if len(hits) > 80:
            print(f"... ({len(hits) - 80} more matches)")

    def do_ask(self, arg: str) -> None:
        parts = arg.strip().split(maxsplit=1)
        if len(parts) < 2:
            print("usage: ask <agent> <question>")
            print("Agents: coordinator | build | infra | planner | all")
            return
        agent_key, question = parts[0].lower(), parts[1]
        if agent_key not in _AGENT_LABELS:
            print(f"Unknown agent: {agent_key!r}")
            return
        if self.session.state is None:
            print("No state loaded.")
            return
        try:
            with Spinner("Ollama / ask"):
                reply = answer_agent_question(agent_key, question, self.session.state)
            print(reply)
        except Exception as exc:
            title, hints = explain_exception(exc)
            print(_error(f"ask: {title}"))
            for h in hints:
                print(f"  -> {h}")


def action_run_triage_existing() -> None:
    print(_header("Analyze Existing Incident", "Run the full multi-agent triage workflow"))
    incident_dir = _get_user_input("Incident directory path")
    if not incident_dir:
        print(_error("Incident directory path is required."))
        return

    incident_path = Path(incident_dir)
    if not incident_path.exists():
        print(_error(f"Incident directory does not exist: {incident_dir}"))
        return

    write_traces = _get_yes_no("Write trace events", default=True)
    write_reports = _get_yes_no("Export reports", default=True)

    trace_dir = None
    if write_traces:
        trace_dir = REPO_ROOT / DEFAULT_TRACES_DIR
        trace_dir.mkdir(parents=True, exist_ok=True)

    try:
        print(_section("Running Agents"))
        print("Coordinator -> build/test analyzer -> infra/config analyzer -> planner")
        state = run_triage_workflow(incident_path, trace_dir=trace_dir)
        print(_success(f"Triage completed for incident: {state.metadata.incident_id}"))

        classification = None
        if state.final_report and state.final_report.failure_classification:
            classification = state.final_report.failure_classification.value
        if classification:
            print(f"  Classification: {_style(classification, Color.BOLD)}")

        if state.suspected_causes:
            print(_section("Suspected Causes"))
            for i, cause in enumerate(state.suspected_causes, 1):
                print(f"    {i}. {cause.summary} (confidence: {cause.confidence:.2f})")

        if state.recommended_actions:
            print(_section("Recommended Actions"))
            for i, action in enumerate(state.recommended_actions, 1):
                print(f"    {i}. {action.summary}")

        trace_file = None
        if write_traces and trace_dir:
            trace_file = trace_dir / f"{state.metadata.incident_id}.jsonl"

        if write_reports:
            reports_output_dir = REPO_ROOT / DEFAULT_REPORTS_DIR
            result = export_report(state, reports_output_dir, trace_file=trace_file)
            print(_section("Artifacts"))
            print(f"  Report JSON: {_path_hint(result.summary_json_path)}")
            print(f"  Report Markdown: {_path_hint(result.markdown_report_path)}")

        if trace_file and trace_file.exists():
            print(f"  Trace File: {_path_hint(trace_file)}")

    except Exception as exc:
        print(_error(f"running triage workflow: {exc}"))


def action_create_incident() -> None:
    print(_header("Create Incident Package", "Capture local repo artifacts and command output"))
    incident_id = _get_user_input("Incident ID")
    if not incident_id:
        print(_error("Incident ID is required."))
        return

    repo_dir = _get_user_input("Repository path", str(REPO_ROOT))
    repo_path = Path(repo_dir)
    if not repo_path.exists():
        print(_error(f"Repository path does not exist: {repo_dir}"))
        return

    build_command = _get_user_input("Build command (optional)")
    test_command = _get_user_input("Test command (optional)")
    overwrite = _get_yes_no("Overwrite existing package", default=False)

    try:
        print(_section("Creating Package"))
        output_root = REPO_ROOT / DEFAULT_INCIDENTS_DIR
        output_root.mkdir(parents=True, exist_ok=True)

        result = create_incident_package(
            incident_id=incident_id,
            output_root=output_root,
            repo_dir=repo_path,
            title=f"Incident: {incident_id}",
            description="Incident package created via interactive CLI.",
            repository=repo_path.name,
            build_command=build_command if build_command else None,
            test_command=test_command if test_command else None,
            overwrite=overwrite,
        )

        print(_success(f"Incident package created: {_path_hint(result.incident_dir)}"))
        print(f"  Copied files: {len(result.copied_files)}")
        for copied in result.copied_files:
            print(f"    - {copied.name}")
        if result.command_captures:
            print(f"  Captured commands: {len(result.command_captures)}")
            for capture in result.command_captures:
                print(f"    - {capture.output_name} (exit_code={capture.exit_code})")

    except FileExistsError as exc:
        print(_error(str(exc)))
    except Exception as exc:
        print(_error(f"creating incident package: {exc}"))


def action_create_and_run_triage() -> None:
    print(_header("Create And Analyze", "Package local evidence, then run triage"))
    incident_id = _get_user_input("Incident ID")
    if not incident_id:
        print(_error("Incident ID is required."))
        return

    repo_dir = _get_user_input("Repository path", str(REPO_ROOT))
    repo_path = Path(repo_dir)
    if not repo_path.exists():
        print(_error(f"Repository path does not exist: {repo_dir}"))
        return

    build_command = _get_user_input("Build command (optional)")
    test_command = _get_user_input("Test command (optional)")
    overwrite = _get_yes_no("Overwrite existing package", default=False)

    try:
        print(_section("Creating Package"))
        output_root = REPO_ROOT / DEFAULT_INCIDENTS_DIR
        output_root.mkdir(parents=True, exist_ok=True)

        result = create_incident_package(
            incident_id=incident_id,
            output_root=output_root,
            repo_dir=repo_path,
            title=f"Incident: {incident_id}",
            description="Incident package created via interactive CLI.",
            repository=repo_path.name,
            build_command=build_command if build_command else None,
            test_command=test_command if test_command else None,
            overwrite=overwrite,
        )

        print(_success(f"Incident package created: {_path_hint(result.incident_dir)}"))
        print(_section("Running Agents"))
        trace_dir = REPO_ROOT / DEFAULT_TRACES_DIR
        trace_dir.mkdir(parents=True, exist_ok=True)

        state = run_triage_workflow(result.incident_dir, trace_dir=trace_dir)
        print(_success(f"Triage completed for incident: {state.metadata.incident_id}"))

        classification = None
        if state.final_report and state.final_report.failure_classification:
            classification = state.final_report.failure_classification.value
        if classification:
            print(f"  Classification: {_style(classification, Color.BOLD)}")

        if state.suspected_causes:
            print(_section("Suspected Causes"))
            for i, cause in enumerate(state.suspected_causes, 1):
                print(f"    {i}. {cause.summary} (confidence: {cause.confidence:.2f})")

        if state.recommended_actions:
            print(_section("Recommended Actions"))
            for i, action in enumerate(state.recommended_actions, 1):
                print(f"    {i}. {action.summary}")

        trace_file = trace_dir / f"{state.metadata.incident_id}.jsonl"
        reports_output_dir = REPO_ROOT / DEFAULT_REPORTS_DIR
        result_report = export_report(state, reports_output_dir, trace_file=trace_file)
        print(_section("Artifacts"))
        print(f"  Report JSON: {_path_hint(result_report.summary_json_path)}")
        print(f"  Report Markdown: {_path_hint(result_report.markdown_report_path)}")
        print(f"  Trace File: {_path_hint(trace_file)}")

    except FileExistsError as exc:
        print(_error(str(exc)))
    except Exception as exc:
        print(_error(str(exc)))


def action_view_latest_report() -> None:
    print(_header("Latest Report", "Review the most recent Markdown triage output"))
    latest = _find_latest_report()
    if not latest:
        print(_warning("No reports found in reports directory."))
        return

    print(f"Latest report: {_path_hint(latest)}")
    print(_section("Content"))
    try:
        print(latest.read_text(encoding="utf-8"))
    except OSError as exc:
        print(_error(f"reading report: {exc}"))


def action_view_trace_events() -> None:
    print(_header("Trace Events", "Inspect the execution trail for an incident"))
    incident_id = _get_user_input("Incident ID")
    if not incident_id:
        print(_error("Incident ID is required."))
        return

    events = _read_trace_events(incident_id)
    if not events:
        print(_warning(f"No trace events found for incident: {incident_id}"))
        return

    print(_section(f"Trace events for {incident_id}: {len(events)} events"))
    for i, event in enumerate(events, 1):
        print(_style(f"\nEvent {i}", Color.BOLD))
        print(_format_trace_event(event))


def action_evaluate_fixtures() -> None:
    print(_header("Evaluate Sample Fixtures", "Run the built-in fixture evaluation script"))
    print("Running fixture evaluation (this may take a while)...")
    script_path = REPO_ROOT / "scripts" / "evaluate_fixtures.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=REPO_ROOT,
            capture_output=False,
            text=True,
        )
        if result.returncode == 0:
            print(_success("Fixture evaluation completed successfully."))
        else:
            print(_error(f"Fixture evaluation failed with exit code {result.returncode}."))
    except Exception as exc:
        print(_error(f"running fixture evaluation: {exc}"))


def action_show_guide() -> None:
    print(guide_text())


def action_generate_sample_input_data() -> None:
    print(_header("Generate Sample Input Data", "Create ready-to-triage incident folders"))
    output_root_raw = _get_user_input(
        "Output folder",
        str(REPO_ROOT / DEFAULT_GENERATED_SAMPLES_DIR),
    )
    output_root = Path(output_root_raw)
    overwrite = _get_yes_no("Overwrite existing generated samples", default=False)
    try:
        created = create_sample_input_data(output_root, overwrite=overwrite)
    except OSError as exc:
        print(_error(f"generating sample input data: {exc}"))
        return

    if created:
        print(_success(f"Generated {len(created)} sample incident folders."))
        for path in created:
            print(f"  - {_path_hint(path)}")
        print(_section("Next Step"))
        print(f"Run triage on one folder, for example: {_path_hint(created[0])}")
    else:
        print(_warning(f"Sample folders already exist at {_path_hint(output_root)}."))
        print("Choose overwrite next time to refresh the generated files.")


def show_menu() -> str:
    print(
        _header(
            "Multi-Agent CI/CD Failure Triage",
            "Guided workflow for demos, assignments, and local incident review",
        )
    )
    print(f"  {_style('1', Color.BOLD)}  Analyze an existing incident folder")
    print(f"  {_style('2', Color.BOLD)}  Create an incident package from a local repo")
    print(f"  {_style('3', Color.BOLD)}  Create a package and run triage")
    print(f"  {_style('4', Color.BOLD)}  Generate sample input data files")
    print(f"  {_style('5', Color.BOLD)}  View guide and expected input format")
    print(f"  {_style('6', Color.BOLD)}  View latest report")
    print(f"  {_style('7', Color.BOLD)}  View trace events for an incident")
    print(f"  {_style('8', Color.BOLD)}  Evaluate built-in sample fixtures")
    print(f"  {_style('9', Color.BOLD)}  Exit")
    return _get_user_input("Select an option")


def legacy_menu_main() -> int:
    actions = {
        "1": action_run_triage_existing,
        "2": action_create_incident,
        "3": action_create_and_run_triage,
        "4": action_generate_sample_input_data,
        "5": action_show_guide,
        "6": action_view_latest_report,
        "7": action_view_trace_events,
        "8": action_evaluate_fixtures,
        "9": lambda: None,
    }

    print(welcome_screen())
    print(_warning("Ensure Ollama is running before using options 1, 3, and 8."))

    while True:
        choice = show_menu()

        if choice == "9":
            print(_success("Exiting. Goodbye."))
            return 0

        if choice not in actions:
            print(_error(f"Invalid option: {choice}. Please select 1-9."))
            continue

        try:
            actions[choice]()
        except KeyboardInterrupt:
            print(_warning("Operation cancelled."))
        except Exception as exc:
            print(_error(f"Unexpected error: {exc}"))

    return 0


def workspace_main(*, show_welcome: bool = True) -> int:
    shell = AgentWorkspaceShell()
    if show_welcome:
        shell.intro = (
            welcome_screen()
            + "\n"
            + _warning("Ollama must be running for run / ask.")
            + "\nType  tour  for a walkthrough,  help  for commands.\n"
        )
    shell.cmdloop()
    print(_success("Goodbye."))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive triage CLI.")
    parser.add_argument(
        "--menu",
        action="store_true",
        help="Guided numbered menu (full-cycle workflows, guide, sample data).",
    )
    parser.add_argument(
        "--no-welcome",
        action="store_true",
        help="Skip the ASCII welcome banner when starting the REPL (automation-friendly).",
    )
    args = parser.parse_args()
    if args.menu:
        return legacy_menu_main()
    return workspace_main(show_welcome=not args.no_welcome)


if __name__ == "__main__":
    raise SystemExit(main())
