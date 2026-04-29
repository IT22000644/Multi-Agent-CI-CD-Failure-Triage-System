from __future__ import annotations

import json
from pathlib import Path

from src.state import TraceEvent
from src.tracing import write_trace_event, write_trace_events


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_single_event_writes_jsonl(tmp_path: Path) -> None:
    event = TraceEvent(
        event_id="event-001",
        event_type="tool_call",
        message="Loaded artifacts",
    )

    file_path = write_trace_event(tmp_path, "incident_001", event)

    assert file_path.exists()
    assert file_path.name == "incident_001.jsonl"

    lines = _read_lines(file_path)
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["event_id"] == "event-001"
    assert payload["event_type"] == "tool_call"
    assert payload["message"] == "Loaded artifacts"
    assert isinstance(payload["timestamp"], str)


def test_multiple_events_append_jsonl(tmp_path: Path) -> None:
    events = [
        TraceEvent(event_id="event-001", event_type="tool_call", message="Loaded"),
        TraceEvent(event_id="event-002", event_type="tool_result", message="Parsed"),
    ]

    file_path = write_trace_events(tmp_path, "incident_001", events)

    lines = _read_lines(file_path)
    assert len(lines) == 2
    assert json.loads(lines[0])["event_id"] == "event-001"
    assert json.loads(lines[1])["event_id"] == "event-002"


def test_appending_preserves_existing_content(tmp_path: Path) -> None:
    write_trace_event(
        tmp_path,
        "incident_001",
        TraceEvent(event_id="event-001", event_type="tool_call", message="First"),
    )
    file_path = write_trace_event(
        tmp_path,
        "incident_001",
        TraceEvent(event_id="event-002", event_type="tool_call", message="Second"),
    )

    lines = _read_lines(file_path)
    assert len(lines) == 2
    assert json.loads(lines[0])["event_id"] == "event-001"
    assert json.loads(lines[1])["event_id"] == "event-002"


def test_empty_events_creates_directory_and_returns_path(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    file_path = write_trace_events(nested, "incident_001", [])

    assert nested.exists()
    assert nested.is_dir()
    assert file_path.name == "incident_001.jsonl"
    assert not file_path.exists()


def test_incident_id_is_sanitized(tmp_path: Path) -> None:
    event = TraceEvent(event_id="event-001", event_type="tool_call", message="Loaded")

    file_path = write_trace_event(tmp_path, "repo/run:123", event)

    assert file_path.name == "repo_run_123.jsonl"


def test_invalid_incident_id_falls_back_to_unknown(tmp_path: Path) -> None:
    event = TraceEvent(event_id="event-001", event_type="tool_call", message="Loaded")

    file_path = write_trace_event(tmp_path, "///", event)

    assert file_path.name == "unknown.jsonl"


def test_empty_incident_id_falls_back_to_unknown(tmp_path: Path) -> None:
    event = TraceEvent(event_id="event-001", event_type="tool_call", message="Loaded")

    file_path = write_trace_event(tmp_path, "", event)

    assert file_path.name == "unknown.jsonl"
