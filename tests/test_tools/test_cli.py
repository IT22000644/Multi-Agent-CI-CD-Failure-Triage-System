"""Tests for the CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

from src.main import main


def test_human_cli_succeeds(capsys: object) -> None:
    """Test human-readable CLI output."""
    exit_code = main(["fixtures/sample_incidents/incident_001"])
    assert exit_code == 0

    captured = capsys.readouterr()  # type: ignore
    assert "Incident: incident_001" in captured.out
    assert "Recommended Actions:" in captured.out


def test_json_cli_succeeds(capsys: object) -> None:
    """Test JSON CLI output."""
    exit_code = main(["fixtures/sample_incidents/incident_001", "--json"])
    assert exit_code == 0

    captured = capsys.readouterr()  # type: ignore
    payload = json.loads(captured.out)
    assert payload["incident_id"] == "incident_001"
    assert payload["recommended_actions"]


def test_cli_writes_trace_file_when_trace_dir_provided(tmp_path: Path) -> None:
    """Test trace file is created when --trace-dir is provided."""
    exit_code = main(
        [
            "fixtures/sample_incidents/incident_001",
            "--trace-dir",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    assert (tmp_path / "incident_001.jsonl").exists()


def test_cli_writes_report_files_when_report_dir_provided(tmp_path: Path, capsys: object) -> None:
    """Test report artifacts are created when --report-dir is provided."""
    report_dir = tmp_path / "reports"
    exit_code = main(
        [
            "fixtures/sample_incidents/incident_001",
            "--report-dir",
            str(report_dir),
        ]
    )

    assert exit_code == 0
    assert (report_dir / "incident_001" / "summary.json").exists()
    assert (report_dir / "incident_001" / "report.md").exists()

    captured = capsys.readouterr()  # type: ignore
    assert "Report JSON:" in captured.out
    assert "Report Markdown:" in captured.out


def test_json_cli_includes_report_export_when_report_dir_provided(
    tmp_path: Path,
    capsys: object,
) -> None:
    """Test JSON CLI output includes report artifact paths."""
    report_dir = tmp_path / "reports"
    exit_code = main(
        [
            "fixtures/sample_incidents/incident_001",
            "--json",
            "--report-dir",
            str(report_dir),
        ]
    )

    assert exit_code == 0

    captured = capsys.readouterr()  # type: ignore
    payload = json.loads(captured.out)
    assert payload["report_export"]["summary_json"].endswith("summary.json")
    assert payload["report_export"]["markdown_report"].endswith("report.md")


def test_missing_path_returns_non_zero(capsys: object) -> None:
    """Test non-zero exit when incident directory does not exist."""
    exit_code = main(["does-not-exist"])
    assert exit_code != 0

    captured = capsys.readouterr()  # type: ignore
    assert "does not exist" in captured.err.lower()


def test_file_path_instead_of_directory_returns_non_zero(
    tmp_path: Path, capsys: object
) -> None:
    """Test non-zero exit when path is a file, not a directory."""
    file_path = tmp_path / "file.txt"
    file_path.write_text("")

    exit_code = main([str(file_path)])
    assert exit_code != 0

    captured = capsys.readouterr()  # type: ignore
    assert "not a directory" in captured.err.lower()
