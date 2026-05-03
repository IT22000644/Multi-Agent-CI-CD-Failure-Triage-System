"""Tests for the interactive CLI."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts.interactive_cli import (
    _find_latest_report,
    _format_trace_event,
    _get_user_input,
    _get_yes_no,
    _read_trace_events,
    action_create_and_run_triage,
    action_create_incident,
    action_evaluate_fixtures,
    action_run_triage_existing,
    action_view_latest_report,
    action_view_trace_events,
)


class TestFindLatestReport:
    """Tests for _find_latest_report function."""

    def test_finds_latest_report_when_multiple_exist(self, tmp_path):
        """Test that the function finds the most recently modified report."""
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            reports_dir = tmp_path / "reports"
            report1_dir = reports_dir / "incident_001"
            report2_dir = reports_dir / "incident_002"
            report1_dir.mkdir(parents=True)
            report2_dir.mkdir(parents=True)

            report1 = report1_dir / "report.md"
            report2 = report2_dir / "report.md"

            report1.write_text("Old report")
            report2.write_text("New report")

            # Make report2 newer
            import os
            import time

            os.utime(report1, (time.time() - 100, time.time() - 100))
            os.utime(report2, (time.time(), time.time()))

            result = _find_latest_report()
            assert result == report2

    def test_returns_none_when_no_reports_exist(self, tmp_path):
        """Test that the function returns None when no reports exist."""
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            result = _find_latest_report()
            assert result is None

    def test_returns_none_when_reports_dir_missing(self, tmp_path):
        """Test that the function returns None when reports directory doesn't exist."""
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            result = _find_latest_report()
            assert result is None


class TestReadTraceEvents:
    """Tests for _read_trace_events function."""

    def test_reads_trace_events_from_jsonl_file(self, tmp_path):
        """Test reading trace events from a JSONL file."""
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            traces_dir = tmp_path / "traces"
            traces_dir.mkdir()

            trace_file = traces_dir / "incident_001.jsonl"
            events = [
                {
                    "event_id": "trace-001",
                    "event_type": "test.event",
                    "agent_name": "test_agent",
                    "message": "Test message",
                    "metadata": {"key": "value"},
                },
                {
                    "event_id": "trace-002",
                    "event_type": "test.event2",
                    "agent_name": "test_agent2",
                    "message": "Test message 2",
                    "metadata": {},
                },
            ]
            # Write all events to file
            content = ""
            for event in events:
                content += json.dumps(event) + "\n"
            trace_file.write_text(content, encoding="utf-8")

            result = _read_trace_events("incident_001")
            assert len(result) == 2
            assert result[0]["event_id"] == "trace-001"
            assert result[1]["event_id"] == "trace-002"

    def test_returns_empty_list_when_file_missing(self, tmp_path):
        """Test that empty list is returned when trace file doesn't exist."""
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            result = _read_trace_events("nonexistent_incident")
            assert result == []

    def test_handles_malformed_json_in_trace_file(self, tmp_path):
        """Test that malformed JSON lines are skipped gracefully."""
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            traces_dir = tmp_path / "traces"
            traces_dir.mkdir()

            trace_file = traces_dir / "incident_001.jsonl"
            trace_file.write_text(
                '{"event_id": "trace-001", "event_type": "test"}\n'
                'invalid json line\n'
                '{"event_id": "trace-002", "event_type": "test2"}\n'
            )

            result = _read_trace_events("incident_001")
            assert len(result) == 2
            assert result[0]["event_id"] == "trace-001"
            assert result[1]["event_id"] == "trace-002"


class TestFormatTraceEvent:
    """Tests for _format_trace_event function."""

    def test_formats_trace_event_with_all_fields(self):
        """Test formatting a trace event with all fields."""
        event = {
            "event_id": "trace-001",
            "event_type": "coordinator.incident_loaded",
            "agent_name": "COORDINATOR",
            "message": "Incident artifacts loaded",
            "metadata": {"artifact_count": 5, "evidence_count": 3},
        }

        result = _format_trace_event(event)

        assert "trace-001" in result
        assert "coordinator.incident_loaded" in result
        assert "COORDINATOR" in result
        assert "Incident artifacts loaded" in result
        assert "artifact_count" in result
        assert "5" in result

    def test_formats_trace_event_without_optional_fields(self):
        """Test formatting a trace event without optional fields."""
        event = {
            "event_id": "trace-001",
            "event_type": "workflow.start",
        }

        result = _format_trace_event(event)

        assert "trace-001" in result
        assert "workflow.start" in result


class TestGetUserInput:
    """Tests for _get_user_input function."""

    @patch("builtins.input", return_value="user_input")
    def test_gets_user_input(self, mock_input):
        """Test getting user input."""
        result = _get_user_input("Enter value")
        assert result == "user_input"
        mock_input.assert_called_once()

    @patch("builtins.input", return_value="")
    def test_returns_default_when_empty(self, mock_input):
        """Test returning default when user input is empty."""
        result = _get_user_input("Enter value", default="default_value")
        assert result == "default_value"

    @patch("builtins.input", return_value="")
    def test_returns_empty_string_when_no_default(self, mock_input):
        """Test returning empty string when no default provided."""
        result = _get_user_input("Enter value")
        assert result == ""

    @patch("builtins.input", side_effect=EOFError)
    def test_handles_eof_error(self, mock_input):
        """Test handling EOF error (e.g., from piped input)."""
        result = _get_user_input("Enter value")
        assert result == ""

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_handles_keyboard_interrupt(self, mock_input):
        """Test handling keyboard interrupt."""
        result = _get_user_input("Enter value")
        assert result == ""


class TestGetYesNo:
    """Tests for _get_yes_no function."""

    @patch("scripts.interactive_cli._get_user_input", return_value="y")
    def test_returns_true_for_yes(self, mock_input):
        """Test returning True for 'y' response."""
        result = _get_yes_no("Continue?")
        assert result is True

    @patch("scripts.interactive_cli._get_user_input", return_value="yes")
    def test_returns_true_for_yes_full(self, mock_input):
        """Test returning True for 'yes' response."""
        result = _get_yes_no("Continue?")
        assert result is True

    @patch("scripts.interactive_cli._get_user_input", return_value="n")
    def test_returns_false_for_no(self, mock_input):
        """Test returning False for 'n' response."""
        result = _get_yes_no("Continue?")
        assert result is False

    @patch("scripts.interactive_cli._get_user_input", return_value="no")
    def test_returns_false_for_no_full(self, mock_input):
        """Test returning False for 'no' response."""
        result = _get_yes_no("Continue?")
        assert result is False

    @patch("scripts.interactive_cli._get_user_input", return_value="")
    def test_returns_default_for_empty_input(self, mock_input):
        """Test returning default when input is empty."""
        result = _get_yes_no("Continue?", default=True)
        assert result is True

        result = _get_yes_no("Continue?", default=False)
        assert result is False

    @patch("scripts.interactive_cli._get_user_input", return_value="invalid")
    def test_returns_default_for_invalid_input(self, mock_input):
        """Test returning default for invalid input."""
        result = _get_yes_no("Continue?", default=True)
        assert result is True


class TestActionRunTriageExisting:
    """Tests for action_run_triage_existing function."""

    @patch("scripts.interactive_cli._get_yes_no")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("scripts.interactive_cli.run_triage_workflow")
    @patch("scripts.interactive_cli.export_report")
    @patch("builtins.print")
    def test_runs_triage_with_traces_and_reports(
        self, mock_print, mock_export, mock_workflow, mock_input, mock_yes_no, tmp_path
    ):
        """Test running triage with traces and reports enabled."""
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            mock_input.return_value = str(tmp_path / "incident_001")
            mock_yes_no.side_effect = [True, True]  # write_traces, write_reports

            mock_state = MagicMock()
            mock_state.metadata.incident_id = "incident_001"
            mock_state.final_report.failure_classification.value = "BUILD_FAILURE"
            mock_state.suspected_causes = []
            mock_state.recommended_actions = []
            mock_workflow.return_value = mock_state

            mock_export_result = MagicMock()
            mock_export_result.summary_json_path = "reports/incident_001/summary.json"
            mock_export_result.markdown_report_path = "reports/incident_001/report.md"
            mock_export.return_value = mock_export_result

            # Create fake incident directory
            incident_dir = tmp_path / "incident_001"
            incident_dir.mkdir()

            action_run_triage_existing()

            mock_workflow.assert_called_once()
            mock_export.assert_called_once()

    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_missing_incident_directory(self, mock_print, mock_input):
        """Test handling when incident directory doesn't exist."""
        mock_input.return_value = "/nonexistent/path"

        action_run_triage_existing()

        # Should print an error
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("does not exist" in str(call) for call in calls)

    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_empty_incident_directory_input(self, mock_print, mock_input):
        """Test handling when user doesn't provide incident directory."""
        mock_input.return_value = ""

        action_run_triage_existing()

        # Should print an error
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("required" in str(call).lower() for call in calls)


class TestActionCreateIncident:
    """Tests for action_create_incident function."""

    @patch("scripts.interactive_cli._get_yes_no")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("scripts.interactive_cli.create_incident_package")
    @patch("builtins.print")
    def test_creates_incident_package(
        self, mock_print, mock_create, mock_input, mock_yes_no, tmp_path
    ):
        """Test creating an incident package."""
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            mock_input.side_effect = [
                "test_incident",  # incident_id
                str(tmp_path),  # repo_dir
                "pytest",  # build_command
                "python -m pytest",  # test_command
            ]
            mock_yes_no.return_value = False  # overwrite

            mock_result = MagicMock()
            mock_result.incident_dir = tmp_path / "test_incident"
            mock_result.copied_files = [
                tmp_path / "test_incident" / "incident.json",
                tmp_path / "test_incident" / "Dockerfile",
            ]
            mock_result.command_captures = []
            mock_create.return_value = mock_result

            action_create_incident()

            mock_create.assert_called_once()

    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_empty_incident_id(self, mock_print, mock_input):
        """Test handling when incident ID is empty."""
        mock_input.return_value = ""

        action_create_incident()

        # Should print an error
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("required" in str(call).lower() for call in calls)

    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_nonexistent_repo_directory(self, mock_print, mock_input):
        """Test handling when repo directory doesn't exist."""
        mock_input.side_effect = ["test_incident", "/nonexistent/repo"]

        action_create_incident()

        # Should print an error
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("does not exist" in str(call) for call in calls)


class TestActionEvaluateFixtures:
    """Tests for action_evaluate_fixtures function."""

    @patch("scripts.interactive_cli.subprocess.run")
    @patch("builtins.print")
    def test_runs_evaluate_fixtures_script(self, mock_print, mock_run):
        """Test running the evaluate fixtures script."""
        mock_run.return_value = MagicMock(returncode=0)

        action_evaluate_fixtures()

        mock_run.assert_called_once()

    @patch("scripts.interactive_cli.subprocess.run")
    @patch("builtins.print")
    def test_handles_script_failure(self, mock_print, mock_run):
        """Test handling when script fails."""
        mock_run.return_value = MagicMock(returncode=1)

        action_evaluate_fixtures()

        # Should indicate failure
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("failed" in str(call).lower() for call in calls)


class TestActionViewLatestReport:
    """Tests for action_view_latest_report function."""

    @patch("scripts.interactive_cli._find_latest_report")
    @patch("builtins.print")
    @patch("builtins.open", create=True)
    def test_displays_latest_report(self, mock_open, mock_print, mock_find, tmp_path):
        """Test displaying the latest report."""
        report_file = tmp_path / "reports" / "incident_001" / "report.md"
        mock_find.return_value = report_file

        mock_file = MagicMock()
        mock_file.read.return_value = "# Report\n\nThis is a test report."
        mock_file.__enter__.return_value = mock_file
        mock_open.return_value = mock_file

        action_view_latest_report()

        mock_find.assert_called_once()

    @patch("scripts.interactive_cli._find_latest_report")
    @patch("builtins.print")
    def test_handles_no_reports(self, mock_print, mock_find):
        """Test handling when no reports exist."""
        mock_find.return_value = None

        action_view_latest_report()

        # Should indicate no reports found
        calls = [str(call) for call in mock_print.call_args_list]
        assert any(
            "not found" in str(call).lower() or "no reports" in str(call).lower()
            for call in calls
        )


class TestActionViewTraceEvents:
    """Tests for action_view_trace_events function."""

    @patch("scripts.interactive_cli._read_trace_events")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_displays_trace_events(self, mock_print, mock_input, mock_read):
        """Test displaying trace events."""
        mock_input.return_value = "incident_001"
        mock_read.return_value = [
            {
                "event_id": "trace-001",
                "event_type": "test.event",
                "agent_name": "test_agent",
                "message": "Test event",
                "metadata": {},
            }
        ]

        action_view_trace_events()

        mock_read.assert_called_once_with("incident_001")

    @patch("scripts.interactive_cli._read_trace_events")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_empty_incident_id(self, mock_print, mock_input, mock_read):
        """Test handling when incident ID is empty."""
        mock_input.return_value = ""

        action_view_trace_events()

        # Should print an error
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("required" in str(call).lower() for call in calls)

    @patch("scripts.interactive_cli._read_trace_events")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_no_trace_events(self, mock_print, mock_input, mock_read):
        """Test handling when no trace events exist."""
        mock_input.return_value = "incident_001"
        mock_read.return_value = []

        action_view_trace_events()

        # Should indicate no events found
        calls = [str(call) for call in mock_print.call_args_list]
        assert any("no trace events found" in str(call).lower() for call in calls)


class TestActionCreateAndRunTriage:
    """Tests for action_create_and_run_triage function."""

    @patch("scripts.interactive_cli._get_yes_no")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("scripts.interactive_cli.create_incident_package")
    @patch("scripts.interactive_cli.run_triage_workflow")
    @patch("scripts.interactive_cli.export_report")
    @patch("builtins.print")
    def test_creates_and_runs_triage(
        self,
        mock_print,
        mock_export,
        mock_workflow,
        mock_create,
        mock_input,
        mock_yes_no,
        tmp_path,
    ):
        """Test creating incident and running triage in one action."""
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            mock_input.side_effect = [
                "test_incident",  # incident_id
                str(tmp_path),  # repo_dir
                "",  # build_command (empty)
                "",  # test_command (empty)
            ]
            mock_yes_no.return_value = False  # overwrite

            mock_create_result = MagicMock()
            mock_create_result.incident_dir = tmp_path / "test_incident"
            mock_create_result.copied_files = []
            mock_create_result.command_captures = []
            mock_create.return_value = mock_create_result

            mock_state = MagicMock()
            mock_state.metadata.incident_id = "test_incident"
            mock_state.final_report.failure_classification.value = "BUILD_FAILURE"
            mock_state.suspected_causes = []
            mock_state.recommended_actions = []
            mock_workflow.return_value = mock_state

            mock_export_result = MagicMock()
            mock_export_result.summary_json_path = "reports/test_incident/summary.json"
            mock_export_result.markdown_report_path = "reports/test_incident/report.md"
            mock_export.return_value = mock_export_result

            action_create_and_run_triage()

            mock_create.assert_called_once()
            mock_workflow.assert_called_once()
            mock_export.assert_called_once()
