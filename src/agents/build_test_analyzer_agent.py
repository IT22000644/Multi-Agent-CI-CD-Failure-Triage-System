from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.state import TriageState
from src.tools import parse_build_and_test_logs


class BuildTestAnalyzerInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    state: TriageState


def run_build_test_analyzer(input_data: BuildTestAnalyzerInput) -> TriageState:
    state = input_data.state.model_copy(deep=True)

    build_log = state.artifacts.get("build.log")
    test_report = state.artifacts.get("test-report.txt")

    result = parse_build_and_test_logs(build_log, test_report)

    state.observed_failures = list(result.observed_failures)
    state.build_test_findings = list(result.findings)
    state.evidence = list(state.evidence) + list(result.evidence)

    return state


__all__ = ["BuildTestAnalyzerInput", "run_build_test_analyzer"]
