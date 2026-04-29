from __future__ import annotations

import json
import re
from pathlib import Path

from src.state import TraceEvent

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


__all__ = ["write_trace_event", "write_trace_events"]
