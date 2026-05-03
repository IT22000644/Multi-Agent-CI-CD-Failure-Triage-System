from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.state import AgentName, TraceEvent, TriageState
from src.tracing.trace_metadata import sanitize_trace_metadata

_SAFE_INCIDENT_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_trace_filename(incident_id: str) -> str:
    sanitized = _SAFE_INCIDENT_CHARS.sub("_", incident_id)
    sanitized = sanitized.strip("._-")
    if not sanitized:
        sanitized = "unknown"
    return f"{sanitized}.jsonl"


def _target_path(trace_dir: str | Path, incident_id: str) -> Path:
    trace_path = Path(trace_dir)
    trace_path.mkdir(parents=True, exist_ok=True)
    return trace_path / _safe_trace_filename(incident_id)


def write_trace_event(
    trace_dir: str | Path,
    incident_id: str,
    event: TraceEvent,
) -> Path:
    file_path = _target_path(trace_dir, incident_id)
    payload = event.model_dump(mode="json")
    line = json.dumps(payload, sort_keys=True)

    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")

    return file_path


def write_trace_events(
    trace_dir: str | Path,
    incident_id: str,
    events: list[TraceEvent],
) -> Path:
    file_path = _target_path(trace_dir, incident_id)
    if not events:
        return file_path

    with file_path.open("a", encoding="utf-8") as handle:
        for event in events:
            payload = event.model_dump(mode="json")
            line = json.dumps(payload, sort_keys=True)
            handle.write(f"{line}\n")

    return file_path


def record_trace_event(
    state: TriageState,
    trace_dir: str | Path | None,
    *,
    agent_name: AgentName | None,
    event_type: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append a trace event to disk and to ``state.trace_events`` (sanitized metadata)."""

    if trace_dir is None:
        return

    sequence = len(state.trace_events) + 1
    incident_id = state.metadata.incident_id or "unknown"
    raw_meta = dict(metadata or {})
    safe_meta = sanitize_trace_metadata(raw_meta)
    event = TraceEvent(
        event_id=f"trace-{incident_id}-{sequence:03d}",
        agent_name=agent_name,
        event_type=event_type,
        message=message,
        metadata=safe_meta,
    )
    write_trace_event(trace_dir, incident_id, event)
    state.trace_events = [*state.trace_events, event]


__all__ = ["record_trace_event", "write_trace_event", "write_trace_events"]
