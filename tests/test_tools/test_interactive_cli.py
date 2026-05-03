"""Tests for the interactive CLI (workspace helpers + legacy menu)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.interactive_cli import (
    REPO_ROOT,
    AgentWorkspaceShell,
    InteractiveSession,
    _find_latest_report,
    _format_trace_event,
    _get_user_input,
    _get_yes_no,
    _read_trace_events,
    action_create_and_run_triage,
    action_create_incident,
    action_evaluate_fixtures,
    action_generate_sample_input_data,
    action_run_triage_existing,
    action_show_guide,
    action_view_latest_report,
    action_view_trace_events,
    answer_agent_question,
    build_agent_question_prompt,
    create_sample_input_data,
    find_latest_trace_file,
    format_evidence,
    format_findings,
    format_state_summary,
    guide_text,
    search_state,
    session_perform_load,
)
from src.agents.build_test_analyzer_agent import (
    BuildTestAnalyzerInput,  # noqa: E402
    run_build_test_analyzer,  # noqa: E402
)
from src.state import (  # noqa: E402
    AgentName,
    ArtifactRecord,
    ArtifactStatus,
    ArtifactType,
    EvidenceItem,
    FailureCategory,
    Finding,
    FindingSeverity,
    IncidentMetadata,
    RecommendedAction,
    SuspectedCause,
    TriageState,
)


def _fake_llm_coordinator() -> str:
    return json.dumps(
        {
            "incident_context_summary": "stub context",
            "notable_artifacts": [],
            "limitations": [],
        }
    )


def _fake_llm_build() -> str:
    return json.dumps(
        {
            "failure_interpretation": "stub interpretation",
            "likely_failure_mode": None,
            "relevant_evidence_ids": [],
            "limitations": [],
        }
    )


def _minimal_state() -> TriageState:
    meta = IncidentMetadata(incident_id="inc-test", title="T")
    art = ArtifactRecord(
        name="build.log",
        artifact_type=ArtifactType.LOG,
        status=ArtifactStatus.LOADED,
        size_bytes=10,
    )
    finding = Finding(
        finding_id="find-001",
        agent_name=AgentName.BUILD_TEST_ANALYZER,
        category=FailureCategory.TEST_FAILURE,
        severity=FindingSeverity.HIGH,
        summary="tests failed on DATABASE_URL",
        details="missing env",
        evidence_ids=["ev-001"],
    )
    evidence = EvidenceItem(
        evidence_id="ev-001",
        artifact_name="build.log",
        snippet="OperationalError DATABASE_URL",
        agent_name=AgentName.BUILD_TEST_ANALYZER,
        supports="find-001",
    )
    return TriageState(
        metadata=meta,
        artifacts={"build.log": art},
        build_test_findings=[finding],
        evidence=[evidence],
    )


class TestFormatHelpers:
    def test_format_state_summary_counts(self):
        state = _minimal_state()
        text = format_state_summary(state)
        assert "inc-test" in text
        assert "Artifacts: 1" in text
        assert "Build/test findings: 1" in text
        assert "Final report present: no" in text

    def test_format_findings_groups(self):
        state = _minimal_state()
        text = format_findings(state)
        assert "build/test" in text
        assert "find-001" in text
        assert "ev-001" in text

    def test_format_evidence_truncates_snippet(self):
        state = _minimal_state()
        state.evidence[0].snippet = "x" * 200
        text = format_evidence(state)
        assert "..." in text

    def test_format_evidence_verbose_allows_longer_snippet(self):
        state = _minimal_state()
        state.evidence[0].snippet = "y" * 300
        brief = format_evidence(state, verbose=False)
        verbose = format_evidence(state, verbose=True)
        assert brief.count("y") < verbose.count("y")


class TestGuideAndSampleData:
    def test_guide_mentions_expected_files_and_assignment_alignment(self):
        text = guide_text()
        assert "Expected Incident Folder" in text
        assert "incident.json" in text
        assert "Assignment Alignment" in text
        assert "Multi-agent workflow" in text

    def test_create_sample_input_data_writes_required_files(self, tmp_path):
        created = create_sample_input_data(tmp_path)

        assert len(created) == 3
        for incident_dir in created:
            assert (incident_dir / "incident.json").exists()
            assert (incident_dir / "build.log").exists()
            assert (incident_dir / "test-report.txt").exists()
            assert (incident_dir / "ci.yml").exists()
            assert (incident_dir / "Dockerfile").exists()
            assert (incident_dir / "requirements.txt").exists()

        metadata = json.loads((created[0] / "incident.json").read_text(encoding="utf-8"))
        assert metadata["incident_id"] == created[0].name

    def test_create_sample_input_data_skips_existing_without_overwrite(self, tmp_path):
        create_sample_input_data(tmp_path)
        created = create_sample_input_data(tmp_path)

        assert created == []

    @patch("scripts.interactive_cli._get_yes_no", return_value=False)
    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_action_generate_sample_input_data(
        self, mock_print, mock_input, mock_yes_no, tmp_path
    ):
        mock_input.return_value = str(tmp_path / "samples")

        action_generate_sample_input_data()

        assert (tmp_path / "samples" / "sample_test_failure" / "incident.json").exists()

    @patch("builtins.print")
    def test_action_show_guide(self, mock_print):
        action_show_guide()

        calls = [str(call) for call in mock_print.call_args_list]
        assert any("CI/CD Failure Triage Guide" in call for call in calls)


class TestSearchState:
    def test_search_finds_finding_summary(self):
        state = _minimal_state()
        hits = search_state("build", "DATABASE_URL", state)
        assert any("find-001" in h for h in hits)

    def test_search_coordinator_artifact(self):
        state = _minimal_state()
        hits = search_state("coordinator", "build.log", state)
        assert any("artifact" in h for h in hits)

    def test_search_planner_actions(self):
        state = _minimal_state()
        cause = SuspectedCause(
            cause_id="cause-001",
            summary="missing env",
            rationale="logs show DB error",
            related_finding_ids=["find-001"],
            evidence_ids=[],
            confidence=0.8,
            rank=1,
        )
        action = RecommendedAction(
            action_id="action-001",
            summary="Set DATABASE_URL",
            details="configure CI secrets",
            related_cause_ids=["cause-001"],
            risk_level=FindingSeverity.LOW,
            confidence=0.8,
            rank=1,
        )
        state.suspected_causes.append(cause)
        state.recommended_actions.append(action)
        hits = search_state("planner", "DATABASE_URL", state)
        assert hits


class TestAskPromptAndAnswer:
    def test_build_agent_question_prompt_includes_constraints_and_ids(self):
        state = _minimal_state()
        prompt = build_agent_question_prompt("build", "Why fail?", state)
        assert "Constraints:" in prompt
        assert "Answer ONLY from the provided state summary" in prompt
        assert "find-001" in prompt
        assert "ev-001" in prompt

    def test_answer_agent_question_calls_ollama(self, monkeypatch):
        state = _minimal_state()
        calls: list[str] = []

        def fake_gen(p: str) -> str:
            calls.append(p)
            return "synthetic answer"

        monkeypatch.setattr(
            "scripts.interactive_cli.generate_with_ollama",
            fake_gen,
        )
        out = answer_agent_question("build", "What happened?", state)
        assert out == "synthetic answer"
        assert calls and "find-001" in calls[0]


class TestFindLatestTraceFile:
    def test_returns_path_when_present(self, tmp_path):
        p = tmp_path / "inc.jsonl"
        p.write_text("{}", encoding="utf-8")
        assert find_latest_trace_file(tmp_path, "inc") == p

    def test_returns_none_when_missing(self, tmp_path):
        assert find_latest_trace_file(tmp_path, "nope") is None


@pytest.fixture
def fixture_incident_001() -> Path:
    p = Path(REPO_ROOT) / "fixtures" / "sample_incidents" / "incident_001"
    if not p.is_dir():
        pytest.skip("fixture incident_001 missing")
    return p


class TestLoadAndRunBuild:
    def test_session_load_initializes_state(self, monkeypatch, fixture_incident_001):
        monkeypatch.setattr(
            "src.agents.coordinator_agent.generate_with_ollama",
            lambda _p: _fake_llm_coordinator(),
        )
        session = InteractiveSession()
        ok, msg = session_perform_load(session, str(fixture_incident_001))
        assert ok, msg
        assert session.state is not None
        assert session.state.metadata.incident_id
        assert "Artifacts:" in msg

    def test_run_build_updates_state_after_load(self, monkeypatch, fixture_incident_001):
        monkeypatch.setattr(
            "src.agents.coordinator_agent.generate_with_ollama",
            lambda _p: _fake_llm_coordinator(),
        )
        monkeypatch.setattr(
            "src.agents.build_test_analyzer_agent.generate_with_ollama",
            lambda _p: _fake_llm_build(),
        )
        session = InteractiveSession()
        ok, _msg = session_perform_load(session, str(fixture_incident_001))
        assert ok
        before_findings = len(session.state.build_test_findings)
        session.state = run_build_test_analyzer(
            BuildTestAnalyzerInput(state=session.state)
        )
        assert session.state is not None
        assert len(session.state.build_test_findings) >= before_findings


class TestWorkspaceShellRobustness:
    def test_unknown_command_does_not_raise(self, capsys):
        shell = AgentWorkspaceShell()
        shell.onecmd("not-a-real-command xyz")
        captured = capsys.readouterr()
        assert "Unknown command" in captured.out

    def test_inspect_requires_two_args(self, capsys):
        shell = AgentWorkspaceShell()
        shell.session.state = _minimal_state()
        shell.onecmd("inspect build")
        assert "usage:" in capsys.readouterr().out.lower()

    def test_help_lists_summary_and_timeline(self, capsys):
        shell = AgentWorkspaceShell()
        shell.onecmd("help")
        out = capsys.readouterr().out
        assert "summary" in out
        assert "timeline" in out
        assert "investigate" in out

    def test_summary_prints_snapshot(self, capsys):
        shell = AgentWorkspaceShell()
        shell.session.state = _minimal_state()
        shell.onecmd("summary")
        out = capsys.readouterr().out
        assert "Triage snapshot" in out
        assert "inc-test" in out

    def test_find_findings_filters(self, capsys):
        shell = AgentWorkspaceShell()
        shell.session.state = _minimal_state()
        shell.onecmd("find findings DATABASE")
        out = capsys.readouterr().out
        assert "find-001" in out

    def test_show_evidence_unknown_id(self, capsys):
        shell = AgentWorkspaceShell()
        shell.session.state = _minimal_state()
        shell.onecmd("show evidence does-not-exist")
        out = capsys.readouterr().out
        assert "No evidence" in out or "[err]" in out

    def test_load_alias_invokes_load(self, monkeypatch, capsys, fixture_incident_001):
        monkeypatch.setattr(
            "src.agents.coordinator_agent.generate_with_ollama",
            lambda _p: _fake_llm_coordinator(),
        )
        shell = AgentWorkspaceShell()
        shell.onecmd(f"l {fixture_incident_001}")
        assert shell.session.state is not None


class TestFindLatestReport:
    def test_finds_latest_report_when_multiple_exist(self, tmp_path):
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

            import os
            import time

            os.utime(report1, (time.time() - 100, time.time() - 100))
            os.utime(report2, (time.time(), time.time()))

            result = _find_latest_report()
            assert result == report2

    def test_returns_none_when_no_reports_exist(self, tmp_path):
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            result = _find_latest_report()
            assert result is None

    def test_returns_none_when_reports_dir_missing(self, tmp_path):
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            result = _find_latest_report()
            assert result is None


class TestReadTraceEvents:
    def test_reads_trace_events_from_jsonl_file(self, tmp_path):
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
            trace_file.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )

            result = _read_trace_events("incident_001")
            assert len(result) == 2
            assert result[0]["event_id"] == "trace-001"
            assert result[1]["event_id"] == "trace-002"

    def test_returns_empty_list_when_file_missing(self, tmp_path):
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            result = _read_trace_events("nonexistent_incident")
            assert result == []

    def test_handles_malformed_json_in_trace_file(self, tmp_path):
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            traces_dir = tmp_path / "traces"
            traces_dir.mkdir()

            trace_file = traces_dir / "incident_001.jsonl"
            trace_file.write_text(
                '{"event_id": "trace-001", "event_type": "test"}\n'
                "invalid json line\n"
                '{"event_id": "trace-002", "event_type": "test2"}\n'
            )

            result = _read_trace_events("incident_001")
            assert len(result) == 2
            assert result[0]["event_id"] == "trace-001"
            assert result[1]["event_id"] == "trace-002"


class TestFormatTraceEvent:
    def test_formats_trace_event_with_all_fields(self):
        event = {
            "event_id": "trace-001",
            "event_type": "coordinator.output",
            "agent_name": "COORDINATOR",
            "message": "Coordinator finished incident bootstrap",
            "metadata": {"artifact_count": 5, "evidence_count": 3},
        }

        result = _format_trace_event(event)

        assert "trace-001" in result
        assert "coordinator.output" in result
        assert "COORDINATOR" in result
        assert "Coordinator finished incident bootstrap" in result
        assert "artifact_count" in result
        assert "5" in result

    def test_formats_trace_event_without_optional_fields(self):
        event = {
            "event_id": "trace-001",
            "event_type": "workflow.start",
        }

        result = _format_trace_event(event)

        assert "trace-001" in result
        assert "workflow.start" in result


class TestGetUserInput:
    @patch("builtins.input", return_value="user_input")
    def test_gets_user_input(self, mock_input):
        result = _get_user_input("Enter value")
        assert result == "user_input"
        mock_input.assert_called_once()

    @patch("builtins.input", return_value="")
    def test_returns_default_when_empty(self, mock_input):
        result = _get_user_input("Enter value", default="default_value")
        assert result == "default_value"

    @patch("builtins.input", return_value="")
    def test_returns_empty_string_when_no_default(self, mock_input):
        result = _get_user_input("Enter value")
        assert result == ""

    @patch("builtins.input", side_effect=EOFError)
    def test_handles_eof_error(self, mock_input):
        result = _get_user_input("Enter value")
        assert result == ""

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_handles_keyboard_interrupt(self, mock_input):
        result = _get_user_input("Enter value")
        assert result == ""


class TestGetYesNo:
    @patch("scripts.interactive_cli._get_user_input", return_value="y")
    def test_returns_true_for_yes(self, mock_input):
        result = _get_yes_no("Continue?")
        assert result is True

    @patch("scripts.interactive_cli._get_user_input", return_value="yes")
    def test_returns_true_for_yes_full(self, mock_input):
        result = _get_yes_no("Continue?")
        assert result is True

    @patch("scripts.interactive_cli._get_user_input", return_value="n")
    def test_returns_false_for_no(self, mock_input):
        result = _get_yes_no("Continue?")
        assert result is False

    @patch("scripts.interactive_cli._get_user_input", return_value="no")
    def test_returns_false_for_no_full(self, mock_input):
        result = _get_yes_no("Continue?")
        assert result is False

    @patch("scripts.interactive_cli._get_user_input", return_value="")
    def test_returns_default_for_empty_input(self, mock_input):
        assert _get_yes_no("Continue?", default=True) is True
        assert _get_yes_no("Continue?", default=False) is False

    @patch("scripts.interactive_cli._get_user_input", return_value="invalid")
    def test_returns_default_for_invalid_input(self, mock_input):
        result = _get_yes_no("Continue?", default=True)
        assert result is True


class TestActionRunTriageExisting:
    @patch("scripts.interactive_cli._get_yes_no")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("scripts.interactive_cli.run_triage_workflow")
    @patch("scripts.interactive_cli.export_report")
    @patch("builtins.print")
    def test_runs_triage_with_traces_and_reports(
        self, mock_print, mock_export, mock_workflow, mock_input, mock_yes_no, tmp_path
    ):
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            mock_input.return_value = str(tmp_path / "incident_001")
            mock_yes_no.side_effect = [True, True]

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

            incident_dir = tmp_path / "incident_001"
            incident_dir.mkdir()

            action_run_triage_existing()

            mock_workflow.assert_called_once()
            mock_export.assert_called_once()

    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_missing_incident_directory(self, mock_print, mock_input):
        mock_input.return_value = "/nonexistent/path"

        action_run_triage_existing()

        calls = [str(call) for call in mock_print.call_args_list]
        assert any("does not exist" in str(call) for call in calls)

    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_empty_incident_directory_input(self, mock_print, mock_input):
        mock_input.return_value = ""

        action_run_triage_existing()

        calls = [str(call) for call in mock_print.call_args_list]
        assert any("required" in str(call).lower() for call in calls)


class TestActionCreateIncident:
    @patch("scripts.interactive_cli._get_yes_no")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("scripts.interactive_cli.create_incident_package")
    @patch("builtins.print")
    def test_creates_incident_package(
        self, mock_print, mock_create, mock_input, mock_yes_no, tmp_path
    ):
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            mock_input.side_effect = [
                "test_incident",
                str(tmp_path),
                "pytest",
                "python -m pytest",
            ]
            mock_yes_no.return_value = False

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
        mock_input.return_value = ""

        action_create_incident()

        calls = [str(call) for call in mock_print.call_args_list]
        assert any("required" in str(call).lower() for call in calls)

    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_nonexistent_repo_directory(self, mock_print, mock_input):
        mock_input.side_effect = ["test_incident", "/nonexistent/repo"]

        action_create_incident()

        calls = [str(call) for call in mock_print.call_args_list]
        assert any("does not exist" in str(call) for call in calls)


class TestActionEvaluateFixtures:
    @patch("scripts.interactive_cli.subprocess.run")
    @patch("builtins.print")
    def test_runs_evaluate_fixtures_script(self, mock_print, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        action_evaluate_fixtures()

        mock_run.assert_called_once()

    @patch("scripts.interactive_cli.subprocess.run")
    @patch("builtins.print")
    def test_handles_script_failure(self, mock_print, mock_run):
        mock_run.return_value = MagicMock(returncode=1)

        action_evaluate_fixtures()

        calls = [str(call) for call in mock_print.call_args_list]
        assert any("failed" in str(call).lower() for call in calls)


class TestActionViewLatestReport:
    @patch("scripts.interactive_cli._find_latest_report")
    @patch("builtins.print")
    def test_displays_latest_report(self, mock_print, mock_find, tmp_path):
        report_file = tmp_path / "reports" / "incident_001" / "report.md"
        mock_find.return_value = report_file
        report_file.parent.mkdir(parents=True)
        report_file.write_text("# Report\n\nThis is a test report.", encoding="utf-8")

        action_view_latest_report()

        mock_find.assert_called_once()

    @patch("scripts.interactive_cli._find_latest_report")
    @patch("builtins.print")
    def test_handles_no_reports(self, mock_print, mock_find):
        mock_find.return_value = None

        action_view_latest_report()

        calls = [str(call) for call in mock_print.call_args_list]
        assert any(
            "not found" in str(call).lower() or "no reports" in str(call).lower()
            for call in calls
        )


class TestActionViewTraceEvents:
    @patch("scripts.interactive_cli._read_trace_events")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_displays_trace_events(self, mock_print, mock_input, mock_read):
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
        mock_input.return_value = ""

        action_view_trace_events()

        calls = [str(call) for call in mock_print.call_args_list]
        assert any("required" in str(call).lower() for call in calls)

    @patch("scripts.interactive_cli._read_trace_events")
    @patch("scripts.interactive_cli._get_user_input")
    @patch("builtins.print")
    def test_handles_no_trace_events(self, mock_print, mock_input, mock_read):
        mock_input.return_value = "incident_001"
        mock_read.return_value = []

        action_view_trace_events()

        calls = [str(call) for call in mock_print.call_args_list]
        assert any("no trace events found" in str(call).lower() for call in calls)


class TestActionCreateAndRunTriage:
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
        with patch("scripts.interactive_cli.REPO_ROOT", tmp_path):
            mock_input.side_effect = [
                "test_incident",
                str(tmp_path),
                "",
                "",
            ]
            mock_yes_no.return_value = False

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
