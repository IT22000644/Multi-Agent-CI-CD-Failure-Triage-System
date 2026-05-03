"""ASCII-first terminal helpers for the interactive triage CLI (no extra dependencies)."""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from typing import Any

from src.state import EvidenceItem, TriageState


def term_width() -> int:
    try:
        w = shutil.get_terminal_size().columns
    except OSError:
        w = 72
    return max(48, min(w - 2, 92))


def use_color() -> bool:
    return os.environ.get("NO_COLOR") is None


class Ansi:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    RESET = "\033[0m"


def _c(text: str, *codes: str) -> str:
    if not use_color() or not codes:
        return text
    return "".join(codes) + text + Ansi.RESET


def ascii_rule(char: str = "-", width: int | None = None) -> str:
    w = width or term_width()
    return char * w


def ascii_panel(title: str, body_lines: list[str], width: int | None = None) -> str:
    w = width or term_width()
    top = "+" + "-" * (w - 2) + "+"
    title_line = f" {title} ".strip()
    if len(title_line) > w - 4:
        title_line = title_line[: w - 7] + "..."
    pad = max(0, w - 4 - len(title_line))
    mid_title = "| " + _c(title_line, Ansi.BOLD, Ansi.CYAN) + " " * pad + "|"
    lines = [top, mid_title, "|" + " " * (w - 2) + "|"]
    for raw in body_lines:
        for chunk in _wrap_line(raw, w - 4):
            inner = chunk.ljust(w - 4)[: w - 4]
            lines.append("| " + inner + " |")
    lines.append("+" + "-" * (w - 2) + "+")
    return "\n".join(lines)


def _wrap_line(text: str, max_inner: int) -> list[str]:
    if len(text) <= max_inner:
        return [text]
    words = text.split()
    rows: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if len(trial) <= max_inner:
            cur = trial
        else:
            if cur:
                rows.append(cur)
            cur = word[:max_inner]
    if cur:
        rows.append(cur)
    return rows or [""]


def ascii_banner() -> str:
    w = term_width()
    # Clear text identity (avoids ambiguous “blob” letters that read as random chars).
    art = [
        "   MULTI-AGENT CI/CD FAILURE TRIAGE",
        "   =================================",
        "   MACT - local workspace - Ollama + LangGraph + tools",
    ]
    lines_out: list[str] = ["+" + "-" * (w - 2) + "+"]
    for row in art:
        if len(row) > w - 4:
            row = row[: w - 7] + "..."
        lines_out.append("| " + row.center(w - 4) + " |")
    lines_out.append("+" + "-" * (w - 2) + "+")
    return "\n".join(lines_out)


def welcome_screen() -> str:
    body = [
        "Load an incident folder (logs, ci.yml, incident.json), run agents, review causes",
        "and fixes, then export a report. Ollama must be running for run/ask steps.",
        "",
        "Quickstart:  sample          create demo folders under .tmp/sample_input_data",
        "             load <path>     attach an incident package",
        "             run all          after load: build -> infra -> planner",
        "             summary          concise triage view (root cause, fixes, confidence)",
        "             tour             step-by-step orientation",
        "             help             commands with examples",
    ]
    return ascii_banner() + "\n" + ascii_panel("Welcome", body)


def severity_label(sev: str) -> str:
    s = sev.lower()
    if s in ("critical", "high"):
        return _c(sev.upper(), Ansi.RED, Ansi.BOLD)
    if s in ("medium",):
        return _c(sev.upper(), Ansi.YELLOW, Ansi.BOLD)
    if s in ("low", "info"):
        return _c(sev.upper(), Ansi.GREEN)
    return sev


def confidence_label(score: float | None) -> str:
    if score is None:
        return "n/a"
    if score >= 0.75:
        return _c(f"{score:.2f} HIGH", Ansi.GREEN, Ansi.BOLD)
    if score >= 0.45:
        return _c(f"{score:.2f} MED", Ansi.YELLOW)
    return _c(f"{score:.2f} LOW", Ansi.DIM)


def format_summary_table(state: TriageState) -> str:
    """Concise counts and headline fields (no raw log dump)."""

    cls = (
        state.final_report.failure_classification.value
        if state.final_report and state.final_report.failure_classification
        else "(not classified — run planner)"
    )
    n_find = len(
        state.build_test_findings + state.config_findings + state.dependency_findings
    )
    rows = [
        f"{'Incident':<14} {state.metadata.incident_id}",
        f"{'Classification':<14} {cls}",
        f"{'Observed fail.':<14} {len(state.observed_failures)}",
        f"{'Findings':<14} {n_find}",
        f"{'Evidence':<14} {len(state.evidence)}",
        f"{'Causes':<14} {len(state.suspected_causes)}",
        f"{'Actions':<14} {len(state.recommended_actions)}",
    ]
    w = term_width()
    sep = "+" + "-" * (w - 2) + "+"
    snap = "Triage snapshot"
    out = [
        sep,
        "| "
        + _c(snap, Ansi.BOLD, Ansi.CYAN)
        + " " * max(0, w - 4 - len(snap))
        + " |",
        sep,
    ]
    for r in rows:
        out.append("| " + r.ljust(w - 4)[: w - 4] + " |")
    out.append(sep)
    return "\n".join(out)


def format_root_cause_block(state: TriageState) -> str:
    lines: list[str] = []
    if state.final_report and state.final_report.root_cause_summary:
        lines.append(
            _c("Root cause: ", Ansi.BOLD)
            + (state.final_report.root_cause_summary.strip()[:500])
        )
    elif state.suspected_causes:
        top = state.suspected_causes[0]
        lines.append(
            _c("Root cause (top suspected): ", Ansi.BOLD)
            + top.summary
            + f"  [{confidence_label(top.confidence)}]"
        )
    else:
        lines.append(_c("Root cause: ", Ansi.BOLD) + "(none yet — run planner)")

    if state.recommended_actions:
        a = state.recommended_actions[0]
        risk = severity_label(a.risk_level.value)
        conf = confidence_label(a.confidence)
        lines.append(_c("Suggested fix: ", Ansi.BOLD) + a.summary + f"  (risk {risk}, conf {conf})")
    else:
        lines.append(_c("Suggested fix: ", Ansi.BOLD) + "(none yet — run planner)")

    if state.confidence_scores:
        s = state.confidence_scores[0]
        ev = ", ".join(s.evidence_ids[:5]) if s.evidence_ids else "(no evidence ids)"
        lines.append(
            _c("Confidence: ", Ansi.BOLD)
            + f"{s.score_id} -> {s.subject_type.value}:{s.subject_id} "
            f"score {confidence_label(s.score)}  evidence: {ev}"
        )
    return "\n".join(lines)


def format_evidence_ids_for_failure(state: TriageState, max_ids: int = 8) -> str:
    ids: list[str] = []
    for o in state.observed_failures:
        ids.extend(o.evidence_ids)
    uniq = []
    for i in ids:
        if i not in uniq:
            uniq.append(i)
    return ", ".join(uniq[:max_ids]) or "(none linked)"


def format_trace_timeline(events: list[dict[str, Any]], limit: int = 35) -> str:
    tail = events[-limit:]
    w = term_width()
    sep = "+" + "-" * (w - 2) + "+"
    head_plain = f"Triage timeline (last {len(tail)} events)"
    lines = [
        sep,
        "| "
        + _c(head_plain, Ansi.BOLD, Ansi.CYAN)
        + " " * max(0, w - 4 - len(head_plain))
        + " |",
        sep,
    ]
    for ev in tail:
        et = str(ev.get("event_type", "?"))[:44]
        mid = str(ev.get("event_id", ""))[:16]
        inner = f"{mid}  {et}"[: w - 4]
        lines.append("| " + inner.ljust(w - 4) + " |")
    lines.append(sep)
    return "\n".join(lines)


def filter_observed_failures(state: TriageState, needle: str) -> list[Any]:
    if not needle:
        return list(state.observed_failures)
    n = needle.lower()
    out = []
    for o in state.observed_failures:
        if n in o.category.value.lower() or n in (o.summary or "").lower():
            out.append(o)
    return out


def filter_findings_by_text(state: TriageState, needle: str) -> list[Any]:
    n = needle.lower()
    all_f = state.build_test_findings + state.config_findings + state.dependency_findings
    if not needle:
        return list(all_f)
    return [
        f
        for f in all_f
        if n in f.summary.lower()
        or n in (f.details or "").lower()
        or n in f.category.value.lower()
        or n in f.finding_id.lower()
    ]


def find_evidence_by_id(state: TriageState, eid: str) -> EvidenceItem | None:
    for e in state.evidence:
        if e.evidence_id == eid:
            return e
    return None


class Spinner:
    """Simple indeterminate spinner for long-running work (stderr-safe)."""

    def __init__(self, message: str) -> None:
        self.message = message
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Spinner:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        sys.stdout.write("\r" + " " * min(120, len(self.message) + 8) + "\r")
        sys.stdout.flush()

    def _run(self) -> None:
        frames = "|/-\\"
        i = 0
        while not self._stop.is_set():
            sys.stdout.write(f"\r{frames[i % 4]} {self.message}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)


def explain_exception(exc: BaseException) -> tuple[str, list[str]]:
    """Plain-language title and recovery hints."""

    name = type(exc).__name__
    msg = str(exc).strip() or name
    hints: list[str] = []

    if "Ollama" in name or "ollama" in msg.lower():
        hints.extend(
            [
                "Start Ollama:  ollama serve",
                "Check OLLAMA_BASE_URL and OLLAMA_MODEL in .env",
                "Retry:  run <step>   or   ask planner <question>",
            ]
        )
        return ("Cannot reach the local LLM (Ollama).", hints)

    if isinstance(exc, FileNotFoundError):
        hints.append("Check the path exists and incident.json is inside the folder.")
        hints.append("Try:  sample   then   load .tmp/sample_input_data/sample_test_failure")
        return ("File or folder not found.", hints)

    if isinstance(exc, KeyboardInterrupt):
        return ("Interrupted.", ["Continue with your last command, or type  exit"])

    low = msg.lower()
    if "connection" in low or "refused" in low:
        hints.extend(
            [
                "Verify Ollama is listening on the configured host/port.",
                "run:  ollama list",
            ]
        )
        return ("Network connection problem.", hints)

    hints.append("Run with  guide  for layout help, or  help  for commands.")
    return (f"{name}: {msg}", hints)


def tour_steps() -> list[tuple[str, list[str]]]:
    return [
        (
            "1/5  What you have",
            [
                "Incidents are folders with incident.json, build.log, ci.yml, and related files.",
                "Command:  sample   (writes demos under .tmp/sample_input_data)",
            ],
        ),
        (
            "2/5  Attach an incident",
            [
                "Command:  load path/to/incident_folder",
                "This runs the coordinator and loads artifacts into the workspace.",
            ],
        ),
        (
            "3/5  Run analyzers",
            [
                "Command:  run all",
                "Runs build/test -> infra/config -> remediation planner -> validator.",
            ],
        ),
        (
            "4/5  Review results",
            [
                "Commands:  summary   failures   findings   causes   actions",
                "timeline   shows recent trace events;  investigate   walks steps.",
            ],
        ),
        (
            "5/5  Export and dig deeper",
            [
                "Command:  export   (writes JSON + Markdown under reports/)",
                "inspect <agent> <text>  searches state;  ask planner <question>  uses Ollama.",
            ],
        ),
    ]


__all__ = [
    "Spinner",
    "ascii_banner",
    "ascii_panel",
    "ascii_rule",
    "confidence_label",
    "explain_exception",
    "filter_findings_by_text",
    "filter_observed_failures",
    "find_evidence_by_id",
    "format_root_cause_block",
    "format_summary_table",
    "format_trace_timeline",
    "format_evidence_ids_for_failure",
    "severity_label",
    "term_width",
    "tour_steps",
    "use_color",
    "welcome_screen",
]
