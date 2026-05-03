"""Tests for ASCII/UX helpers used by the interactive CLI."""

from __future__ import annotations

from scripts.cli_ui import (
    ascii_banner,
    explain_exception,
    filter_findings_by_text,
    filter_observed_failures,
    format_summary_table,
    format_trace_timeline,
    tour_steps,
    welcome_screen,
)
from src.llm.ollama_client import OllamaGenerationError
from src.state import FailureCategory, ObservedFailure
from tests.test_tools.test_interactive_cli import _minimal_state


def test_welcome_screen_has_banner_and_quickstart() -> None:
    text = welcome_screen()
    assert "multi-agent" in text.lower() or "triage" in text.lower()
    assert "Quickstart" in text
    assert "load" in text.lower()


def test_ascii_banner_uses_box_drawing() -> None:
    b = ascii_banner()
    assert b.startswith("+")
    assert "|" in b


def test_format_summary_table_includes_incident_id() -> None:
    state = _minimal_state()
    tbl = format_summary_table(state)
    assert "inc-test" in tbl
    assert "Triage snapshot" in tbl


def test_format_trace_timeline_respects_limit() -> None:
    events = [{"event_id": f"e{i}", "event_type": f"t{i}"} for i in range(50)]
    out = format_trace_timeline(events, limit=5)
    assert "Triage timeline (last 5 events)" in out
    assert "t49" in out or "t48" in out


def test_filter_observed_failures_substring() -> None:
    state = _minimal_state()
    state.observed_failures = [
        ObservedFailure(
            category=FailureCategory.TEST_FAILURE,
            summary="database connection refused",
            evidence_ids=[],
        )
    ]
    assert len(filter_observed_failures(state, "database")) == 1
    assert len(filter_observed_failures(state, "nomatch")) == 0


def test_filter_findings_by_text() -> None:
    state = _minimal_state()
    found = filter_findings_by_text(state, "DATABASE")
    assert found


def test_tour_steps_has_five_entries() -> None:
    assert len(tour_steps()) == 5


def test_explain_exception_ollama_generation() -> None:
    title, hints = explain_exception(OllamaGenerationError("nope"))
    assert "LLM" in title or "Ollama" in title
    assert any("ollama" in h.lower() for h in hints)
