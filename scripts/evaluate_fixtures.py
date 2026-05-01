"""Evaluate all sample incident fixtures against expected triage outcomes."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.graph import run_triage_workflow  # noqa: E402
from src.reporting import export_report  # noqa: E402
from src.state import TriageState  # noqa: E402

SLM_EVIDENCE_LOCATIONS = {
    "coordinator": "ollama.incident_context",
    "build_test_analyzer": "ollama.semantic_interpretation",
    "infra_config_analyzer": "ollama.infra_config_interpretation",
}


@dataclass
class FixtureEvaluation:
    incident_id: str
    fixture_dir: Path
    expected_category: str
    actual_category: str | None = None
    passed: bool = False
    errors: list[str] = field(default_factory=list)
    trace_file: Path | None = None
    summary_json: Path | None = None
    markdown_report: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "fixture_dir": str(self.fixture_dir),
            "expected_category": self.expected_category,
            "actual_category": self.actual_category,
            "passed": self.passed,
            "errors": self.errors,
            "trace_file": str(self.trace_file) if self.trace_file else None,
            "summary_json": str(self.summary_json) if self.summary_json else None,
            "markdown_report": str(self.markdown_report) if self.markdown_report else None,
        }


def _load_incident_metadata(fixture_dir: Path) -> dict[str, Any]:
    incident_path = fixture_dir / "incident.json"
    data = json.loads(incident_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{incident_path} must contain a JSON object")
    return data


def _classification(state: TriageState) -> str | None:
    if state.final_report and state.final_report.failure_classification:
        return state.final_report.failure_classification.value
    return None


def _validate_state(
    state: TriageState,
    expected_category: str,
    trace_file: Path,
) -> list[str]:
    errors: list[str] = []
    actual_category = _classification(state)

    if actual_category != expected_category:
        errors.append(
            f"classification mismatch: expected {expected_category}, got {actual_category}"
        )

    if state.final_report is None:
        errors.append("final report was not produced")

    if not state.recommended_actions:
        errors.append("recommended actions were not produced")

    for agent_name, location in SLM_EVIDENCE_LOCATIONS.items():
        if not any(item.location == location for item in state.evidence):
            errors.append(f"{agent_name} SLM evidence was not recorded")

    if not trace_file.exists():
        errors.append(f"trace file was not written: {trace_file}")
    elif trace_file.stat().st_size == 0:
        errors.append(f"trace file is empty: {trace_file}")

    return errors


def _fixture_dirs(fixtures_root: Path) -> list[Path]:
    return sorted(
        path
        for path in fixtures_root.iterdir()
        if path.is_dir() and (path / "incident.json").exists()
    )


def evaluate_fixture(
    fixture_dir: Path,
    *,
    trace_root: Path,
    report_root: Path,
) -> FixtureEvaluation:
    metadata = _load_incident_metadata(fixture_dir)
    incident_id = str(metadata["incident_id"])
    expected_category = str(metadata["expected_failure_category"])
    result = FixtureEvaluation(
        incident_id=incident_id,
        fixture_dir=fixture_dir,
        expected_category=expected_category,
    )

    trace_dir = trace_root / incident_id
    trace_file = trace_dir / f"{incident_id}.jsonl"
    result.trace_file = trace_file

    try:
        state = run_triage_workflow(fixture_dir, trace_dir=trace_dir)
        result.actual_category = _classification(state)
        report_export = export_report(state, report_root, trace_file=trace_file)
        result.summary_json = report_export.summary_json_path
        result.markdown_report = report_export.markdown_report_path
        result.errors = _validate_state(state, expected_category, trace_file)
        result.passed = not result.errors
    except Exception as exc:
        result.errors = [f"evaluation raised {type(exc).__name__}: {exc}"]
        result.passed = False

    return result


def _print_table(results: list[FixtureEvaluation]) -> None:
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        actual = result.actual_category or "n/a"
        print(f"{result.incident_id:<40} {status:<4} {actual}")
        for error in result.errors:
            print(f"  - {error}")

    passed = sum(1 for result in results if result.passed)
    failed = len(results) - passed
    print()
    print(f"{passed} passed, {failed} failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate sample incident fixtures against expected categories."
    )
    parser.add_argument(
        "--fixtures-root",
        default=str(REPO_ROOT / "fixtures" / "sample_incidents"),
        help="Directory containing incident fixture directories.",
    )
    parser.add_argument(
        "--trace-root",
        default=str(REPO_ROOT / "traces" / "evaluation"),
        help="Directory where evaluation traces are written.",
    )
    parser.add_argument(
        "--report-root",
        default=str(REPO_ROOT / "reports" / "evaluation"),
        help="Directory where evaluation reports are written.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a text table.",
    )

    args = parser.parse_args(argv)
    fixtures_root = Path(args.fixtures_root)
    trace_root = Path(args.trace_root)
    report_root = Path(args.report_root)

    if not fixtures_root.is_dir():
        print(f"Fixtures root does not exist: {fixtures_root}", file=sys.stderr)
        return 2

    results = [
        evaluate_fixture(fixture_dir, trace_root=trace_root, report_root=report_root)
        for fixture_dir in _fixture_dirs(fixtures_root)
    ]

    if args.json:
        print(json.dumps([result.as_dict() for result in results], indent=2))
    else:
        _print_table(results)

    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
