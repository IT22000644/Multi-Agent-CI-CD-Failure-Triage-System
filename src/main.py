"""CLI entry point for the Multi-Agent CI/CD Failure Triage System."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.graph import run_triage_workflow
from src.state import TriageState


def _classification_value(state: TriageState) -> str | None:
    """Extract classification as a string value."""
    if state.final_report and state.final_report.failure_classification:
        return state.final_report.failure_classification.value
    return None


def _build_summary_payload(state: TriageState) -> dict[str, object]:
    """Build a machine-readable summary as a dictionary."""
    return {
        "incident_id": state.metadata.incident_id,
        "title": state.metadata.title,
        "failure_classification": _classification_value(state),
        "suspected_causes": [
            {
                "cause_id": c.cause_id,
                "summary": c.summary,
                "confidence": c.confidence,
                "rank": c.rank,
            }
            for c in state.suspected_causes
        ],
        "recommended_actions": [
            {
                "action_id": a.action_id,
                "summary": a.summary,
                "confidence": a.confidence,
                "rank": a.rank,
            }
            for a in state.recommended_actions
        ],
        "executive_summary": (
            state.final_report.executive_summary if state.final_report else None
        ),
        "trace_event_count": len(state.trace_events),
    }


def _print_human_summary(
    state: TriageState, trace_file: Path | None = None
) -> None:
    """Print a human-readable summary to stdout."""
    print(f"Incident: {state.metadata.incident_id}")

    if state.metadata.title:
        print(f"Title: {state.metadata.title}")

    classification = _classification_value(state)
    if classification:
        print(f"Classification: {classification}")

    if state.suspected_causes:
        print("\nSuspected Causes:")
        for i, cause in enumerate(state.suspected_causes, 1):
            print(f"{i}. {cause.summary}")

    if state.recommended_actions:
        print("\nRecommended Actions:")
        for i, action in enumerate(state.recommended_actions, 1):
            print(f"{i}. {action.summary}")

    if state.final_report and state.final_report.executive_summary:
        print(f"\nSummary:\n{state.final_report.executive_summary}")

    if state.trace_events:
        print(f"\nTrace Events: {len(state.trace_events)}")

    if trace_file:
        print(f"Trace File: {trace_file}")


def main(argv: list[str] | None = None) -> int:
    """Execute the triage workflow from the command line.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:] if not provided).

    Returns:
        0 on success; non-zero on error.
    """
    parser = argparse.ArgumentParser(
        description="Multi-Agent CI/CD Failure Triage System"
    )
    parser.add_argument(
        "incident_dir",
        help="Path to the incident directory containing artifacts",
    )
    parser.add_argument(
        "--trace-dir",
        help="Optional directory to write trace events (JSONL format)",
        default=None,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable format",
    )

    args = parser.parse_args(argv)

    incident_path = Path(args.incident_dir)

    # Validate incident directory exists
    if not incident_path.exists():
        print(
            f"Error: incident directory '{args.incident_dir}' does not exist",
            file=sys.stderr,
        )
        return 1

    # Validate incident path is a directory
    if not incident_path.is_dir():
        print(
            f"Error: incident path '{args.incident_dir}' is not a directory",
            file=sys.stderr,
        )
        return 1

    try:
        # Run the triage workflow
        state = run_triage_workflow(incident_path, trace_dir=args.trace_dir)

        # Determine trace file path if trace_dir was provided
        trace_file = None
        if args.trace_dir:
            trace_file = Path(args.trace_dir) / f"{state.metadata.incident_id}.jsonl"

        # Output results
        if args.json:
            payload = _build_summary_payload(state)
            print(json.dumps(payload, indent=2))
        else:
            _print_human_summary(state, trace_file)

        return 0
    except Exception as e:
        print(f"Error running triage workflow: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
