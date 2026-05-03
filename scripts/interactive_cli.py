"""Interactive terminal menu for the Multi-Agent CI/CD Failure Triage System."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.create_incident import create_incident_package  # noqa: E402
from src.graph import run_triage_workflow  # noqa: E402
from src.reporting import export_report  # noqa: E402

# Default paths
DEFAULT_INCIDENTS_DIR = Path(".tmp/incidents")
DEFAULT_TRACES_DIR = Path("traces")
DEFAULT_REPORTS_DIR = Path("reports")
DEFAULT_FIXTURES_DIR = Path("fixtures/sample_incidents")


def _find_latest_report() -> Path | None:
    """Find the most recently modified report.md under reports/**/report.md."""
    reports_dir = REPO_ROOT / DEFAULT_REPORTS_DIR
    if not reports_dir.exists():
        return None

    latest = None
    latest_mtime = 0

    for report_file in reports_dir.glob("**/report.md"):
        mtime = report_file.stat().st_mtime
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest = report_file

    return latest


def _read_trace_events(incident_id: str) -> list[dict[str, Any]]:
    """Read trace events from traces/<incident_id>.jsonl file."""
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
                        event = json.loads(line)
                        events.append(event)
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        print(f"Error reading trace file: {e}")

    return events


def _format_trace_event(event: dict[str, Any]) -> str:
    """Format a trace event for display."""
    lines = []
    lines.append(f"  Event ID: {event.get('event_id', 'N/A')}")
    lines.append(f"  Type: {event.get('event_type', 'N/A')}")

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
    """Get user input with optional default."""
    if default:
        display_prompt = f"{prompt} [{default}]: "
    else:
        display_prompt = f"{prompt}: "

    try:
        user_input = input(display_prompt).strip()
        return user_input if user_input else (default or "")
    except (EOFError, KeyboardInterrupt):
        return ""


def _get_yes_no(prompt: str, default: bool = True) -> bool:
    """Get yes/no user input."""
    default_str = "Y/n" if default else "y/N"
    response = _get_user_input(f"{prompt} ({default_str})", "").lower()

    if response in ("y", "yes"):
        return True
    elif response in ("n", "no"):
        return False
    else:
        return default


def action_run_triage_existing() -> None:
    """Option 1: Run triage on an existing incident folder."""
    print("\n--- Run Triage on Existing Incident ---")

    incident_dir = _get_user_input("Incident directory path")
    if not incident_dir:
        print("Error: Incident directory path is required.")
        return

    incident_path = Path(incident_dir)
    if not incident_path.exists():
        print(f"Error: Incident directory does not exist: {incident_dir}")
        return

    write_traces = _get_yes_no("Write trace events", default=True)
    write_reports = _get_yes_no("Export reports", default=True)

    trace_dir = None
    if write_traces:
        trace_dir = REPO_ROOT / DEFAULT_TRACES_DIR
        trace_dir.mkdir(parents=True, exist_ok=True)

    try:
        print("Running triage workflow...")
        state = run_triage_workflow(incident_path, trace_dir=trace_dir)

        print(f"\n✓ Triage completed for incident: {state.metadata.incident_id}")

        if classification := (
            state.final_report.failure_classification.value
            if state.final_report and state.final_report.failure_classification
            else None
        ):
            print(f"  Classification: {classification}")

        if state.suspected_causes:
            print("  Suspected Causes:")
            for i, cause in enumerate(state.suspected_causes, 1):
                print(f"    {i}. {cause.summary} (confidence: {cause.confidence:.2f})")

        if state.recommended_actions:
            print("  Recommended Actions:")
            for i, action in enumerate(state.recommended_actions, 1):
                print(f"    {i}. {action.summary}")

        trace_file = None
        if write_traces and trace_dir:
            trace_file = trace_dir / f"{state.metadata.incident_id}.jsonl"

        if write_reports:
            reports_output_dir = REPO_ROOT / DEFAULT_REPORTS_DIR
            result = export_report(state, reports_output_dir, trace_file=trace_file)
            print(f"  Report JSON: {result.summary_json_path}")
            print(f"  Report Markdown: {result.markdown_report_path}")

        if trace_file and trace_file.exists():
            print(f"  Trace File: {trace_file}")

    except Exception as exc:
        print(f"Error running triage workflow: {exc}")


def action_create_incident() -> None:
    """Option 2: Create an incident package from local repo."""
    print("\n--- Create Incident Package from Local Repo ---")

    incident_id = _get_user_input("Incident ID")
    if not incident_id:
        print("Error: Incident ID is required.")
        return

    repo_dir = _get_user_input("Repository path", str(REPO_ROOT))
    repo_path = Path(repo_dir)
    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_dir}")
        return

    build_command = _get_user_input("Build command (optional)")
    test_command = _get_user_input("Test command (optional)")
    overwrite = _get_yes_no("Overwrite existing package", default=False)

    try:
        print("Creating incident package...")
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

        print(f"✓ Incident package created: {result.incident_dir}")
        print(f"  Copied files: {len(result.copied_files)}")
        for copied in result.copied_files:
            print(f"    - {copied.name}")
        if result.command_captures:
            print(f"  Captured commands: {len(result.command_captures)}")
            for capture in result.command_captures:
                print(f"    - {capture.output_name} (exit_code={capture.exit_code})")

    except FileExistsError as exc:
        print(f"Error: {exc}")
    except Exception as exc:
        print(f"Error creating incident package: {exc}")


def action_create_and_run_triage() -> None:
    """Option 3: Create incident package and run triage immediately."""
    print("\n--- Create Incident and Run Triage ---")

    incident_id = _get_user_input("Incident ID")
    if not incident_id:
        print("Error: Incident ID is required.")
        return

    repo_dir = _get_user_input("Repository path", str(REPO_ROOT))
    repo_path = Path(repo_dir)
    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_dir}")
        return

    build_command = _get_user_input("Build command (optional)")
    test_command = _get_user_input("Test command (optional)")
    overwrite = _get_yes_no("Overwrite existing package", default=False)

    try:
        # Step 1: Create incident package
        print("Creating incident package...")
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

        print(f"✓ Incident package created: {result.incident_dir}")

        # Step 2: Run triage with traces and reports enabled
        print("\nRunning triage workflow...")
        trace_dir = REPO_ROOT / DEFAULT_TRACES_DIR
        trace_dir.mkdir(parents=True, exist_ok=True)

        state = run_triage_workflow(result.incident_dir, trace_dir=trace_dir)

        print(f"✓ Triage completed for incident: {state.metadata.incident_id}")

        if classification := (
            state.final_report.failure_classification.value
            if state.final_report and state.final_report.failure_classification
            else None
        ):
            print(f"  Classification: {classification}")

        if state.suspected_causes:
            print("  Suspected Causes:")
            for i, cause in enumerate(state.suspected_causes, 1):
                print(f"    {i}. {cause.summary} (confidence: {cause.confidence:.2f})")

        if state.recommended_actions:
            print("  Recommended Actions:")
            for i, action in enumerate(state.recommended_actions, 1):
                print(f"    {i}. {action.summary}")

        trace_file = trace_dir / f"{state.metadata.incident_id}.jsonl"
        reports_output_dir = REPO_ROOT / DEFAULT_REPORTS_DIR
        result_report = export_report(state, reports_output_dir, trace_file=trace_file)
        print(f"  Report JSON: {result_report.summary_json_path}")
        print(f"  Report Markdown: {result_report.markdown_report_path}")
        print(f"  Trace File: {trace_file}")

    except FileExistsError as exc:
        print(f"Error: {exc}")
    except Exception as exc:
        print(f"Error: {exc}")


def action_view_latest_report() -> None:
    """Option 4: View the latest report."""
    print("\n--- View Latest Report ---")

    latest = _find_latest_report()
    if not latest:
        print("No reports found in reports directory.")
        return

    print(f"Latest report: {latest}")
    print("\nContent:")
    print("-" * 80)
    try:
        with open(latest, encoding="utf-8") as f:
            print(f.read())
    except Exception as exc:
        print(f"Error reading report: {exc}")
    print("-" * 80)


def action_view_trace_events() -> None:
    """Option 5: View trace events for an incident."""
    print("\n--- View Trace Events ---")

    incident_id = _get_user_input("Incident ID")
    if not incident_id:
        print("Error: Incident ID is required.")
        return

    events = _read_trace_events(incident_id)
    if not events:
        print(f"No trace events found for incident: {incident_id}")
        return

    print(f"\nTrace events for {incident_id}: {len(events)} events")
    print("-" * 80)
    for i, event in enumerate(events, 1):
        print(f"\nEvent {i}:")
        print(_format_trace_event(event))
    print("-" * 80)


def action_evaluate_fixtures() -> None:
    """Option 6: Evaluate sample fixtures."""
    print("\n--- Evaluate Sample Fixtures ---")
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
            print("\n✓ Fixture evaluation completed successfully.")
        else:
            print(f"\n✗ Fixture evaluation failed with exit code {result.returncode}.")
    except Exception as exc:
        print(f"Error running fixture evaluation: {exc}")


def show_menu() -> str:
    """Display the menu and get user choice."""
    print("\n" + "=" * 60)
    print("Multi-Agent CI/CD Failure Triage System - Interactive Menu")
    print("=" * 60)
    print("1. Run triage on an existing incident folder")
    print("2. Create an incident package from local repo")
    print("3. Create incident package and run triage")
    print("4. View latest report")
    print("5. View trace events for an incident")
    print("6. Evaluate sample fixtures")
    print("7. Exit")
    print("=" * 60)

    choice = _get_user_input("Select an option")
    return choice


def main() -> int:
    """Main CLI loop."""
    actions = {
        "1": action_run_triage_existing,
        "2": action_create_incident,
        "3": action_create_and_run_triage,
        "4": action_view_latest_report,
        "5": action_view_trace_events,
        "6": action_evaluate_fixtures,
        "7": lambda: None,  # Exit is handled in the loop
    }

    print("\nWelcome to the Multi-Agent CI/CD Failure Triage System!")
    print("Note: Ensure Ollama is running before using options 1, 3, and 6.")

    while True:
        choice = show_menu()

        if choice == "7":
            print("\nExiting. Goodbye!")
            return 0

        if choice not in actions:
            print(f"Invalid option: {choice}. Please select 1-7.")
            continue

        try:
            actions[choice]()
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
        except Exception as exc:
            print(f"Unexpected error: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
