"""Observability and tracing support for the triage system.

This module will provide utilities for capturing, storing, and querying
trace events during workflow execution.
"""

from src.tracing.trace_logger import write_trace_event, write_trace_events

__all__ = ["write_trace_event", "write_trace_events"]
