from __future__ import annotations

import json
from pathlib import Path

from src.state import AgentName, IncidentMetadata, TraceEvent, TriageState
from src.tracing import record_trace_event, write_trace_event, write_trace_events
from src.tracing.trace_metadata import sanitize_trace_metadata


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


def test_record_trace_event_appends_state_and_writes_disk(tmp_path: Path) -> None:
    state = TriageState(metadata=IncidentMetadata(incident_id="incident_z"))

    record_trace_event(
        state,
        tmp_path,
        agent_name=AgentName.COORDINATOR,
        event_type="coordinator.output",
        message="done",
        metadata={"artifact_count": 2},
    )

    assert len(state.trace_events) == 1
    lines = _read_lines(tmp_path / "incident_z.jsonl")
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event_type"] == "coordinator.output"
    assert payload["metadata"]["artifact_count"] == 2


def test_sanitize_trace_metadata_redacts_sensitive_strings() -> None:
    meta = sanitize_trace_metadata(
        {
            "note": "MY_SECRET_TOKEN_HERE",
            "url": "postgres://user:pass123@db.example.com:5432/app",
            "safe": "environment_issue",
        }
    )

    assert meta["note"] == "[REDACTED]"
    assert meta["url"] == "[REDACTED_URL]"
    assert meta["safe"] == "environment_issue"


def test_sanitize_trace_metadata_truncates_long_strings() -> None:
    long_text = "x" * 400
    meta = sanitize_trace_metadata({"blob": long_text}, limit=50)

    assert isinstance(meta["blob"], str)
    assert len(meta["blob"]) <= 50
    assert meta["blob"].endswith("...")
