from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.llm import StructuredLLMOutputError, parse_llm_json_output
from src.llm.ollama_client import generate_with_ollama, load_ollama_config_from_env
from src.state import AgentName, ArtifactType, EvidenceItem, TriageState
from src.tools import parse_build_and_test_logs
from src.tracing.trace_logger import record_trace_event
from src.tracing.trace_metadata import (
    ollama_response_summary,
    slm_state_context,
    summarize_build_log_parse_result,
)


class BuildTestAnalyzerInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    state: TriageState
    trace_dir: str | Path | None = None


class BuildTestAnalyzerOutputParseError(RuntimeError):
    """Raised when the build/test analyzer LLM response is not valid structured output."""


class BuildTestAnalyzerLLMOutput(BaseModel):
    failure_interpretation: str = Field(min_length=1)
    likely_failure_mode: str | None = None
    relevant_evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _build_failure_interpretation_prompt(state: TriageState) -> str:
    parts: list[str] = [
        "Analyze these CI build and test artifacts.",
        "Return a concise semantic interpretation of the failure.",
        "Do not invent artifact names, IDs, or unsupported root causes.",
    ]

    build_log = state.artifacts.get("build.log")
    test_report = state.artifacts.get("test-report.txt")

    if build_log and build_log.content:
        parts.append("Build log excerpt:")
        parts.append(build_log.content[:4000])

    if test_report and test_report.content:
        parts.append("Test report excerpt:")
        parts.append(test_report.content[:4000])

    if state.observed_failures:
        parts.append("Detected observed failures:")
        for failure in state.observed_failures:
            parts.append(f"- {failure.category.value}: {failure.summary}")

    if state.build_test_findings:
        parts.append("Detected build/test findings:")
        for finding in state.build_test_findings:
            parts.append(f"- {finding.finding_id}: {finding.summary}")

    if state.evidence:
        parts.append("Evidence IDs:")
        for evidence in state.evidence:
            parts.append(f"- {evidence.evidence_id}: {evidence.snippet[:200]}")

    parts.append(
        "Return only valid JSON with this exact schema: "
        '{"failure_interpretation": string, "likely_failure_mode": string | null, '
        '"relevant_evidence_ids": string[], "limitations": string[]}.'
    )

    return "\n".join(parts)


def _parse_build_test_llm_output(text: str) -> BuildTestAnalyzerLLMOutput:
    try:
        return parse_llm_json_output(
            text,
            BuildTestAnalyzerLLMOutput,
            context="Build/test analyzer",
        )
    except StructuredLLMOutputError as exc:
        raise BuildTestAnalyzerOutputParseError(
            f"Build/test analyzer LLM output parse failed: {exc}"
        ) from exc


def _append_llm_interpretation_evidence(
    state: TriageState,
    output: BuildTestAnalyzerLLMOutput,
) -> None:
    text = output.failure_interpretation.strip()
    if not text:
        return

    supports = state.build_test_findings[0].finding_id if state.build_test_findings else None
    evidence_id = f"evidence-build-test-llm-{len(state.evidence) + 1:03d}"
    evidence = EvidenceItem(
        evidence_id=evidence_id,
        artifact_name="build.log",
        artifact_type=ArtifactType.LOG,
        location="ollama.semantic_interpretation",
        snippet=f"LLM_INTERPRETATION: {text}",
        agent_name=AgentName.BUILD_TEST_ANALYZER,
        supports=supports,
    )
    state.evidence.append(evidence)

    if supports:
        state.build_test_findings[0].evidence_ids.append(evidence_id)


def run_build_test_analyzer(input_data: BuildTestAnalyzerInput) -> TriageState:
    state = input_data.state.model_copy(deep=True)
    td = input_data.trace_dir

    artifact_names = [
        name for name in ("build.log", "test-report.txt") if name in state.artifacts
    ]
    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.BUILD_TEST_ANALYZER,
            event_type="build_test_analyzer.input",
            message="Build/test analyzer inputs",
            metadata={"artifact_names": artifact_names},
        )

    build_log = state.artifacts.get("build.log")
    test_report = state.artifacts.get("test-report.txt")

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.BUILD_TEST_ANALYZER,
            event_type="tool.build_log_parser.input",
            message="Parsing build and test artifacts",
            metadata={"artifact_names": artifact_names},
        )

    result = parse_build_and_test_logs(build_log, test_report)

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.BUILD_TEST_ANALYZER,
            event_type="tool.build_log_parser.output",
            message="Build log parser produced failures and findings",
            metadata=summarize_build_log_parse_result(result),
        )

    state.observed_failures = list(result.observed_failures)
    state.build_test_findings = list(result.findings)
    state.evidence = list(state.evidence) + list(result.evidence)

    prompt = _build_failure_interpretation_prompt(state)
    cfg = load_ollama_config_from_env()
    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.BUILD_TEST_ANALYZER,
            event_type="ollama.build_test_analyzer.request",
            message="SLM request for build/test semantic interpretation",
            metadata={
                "model": cfg.model,
                "prompt_character_count": len(prompt),
                "state_context": slm_state_context(state),
            },
        )

    raw_response = generate_with_ollama(prompt)
    interpretation = _parse_build_test_llm_output(raw_response)

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.BUILD_TEST_ANALYZER,
            event_type="ollama.build_test_analyzer.response",
            message="SLM response for build/test analyzer",
            metadata=ollama_response_summary(interpretation, raw_text=raw_response),
        )

    _append_llm_interpretation_evidence(state, interpretation)

    if td is not None:
        record_trace_event(
            state,
            td,
            agent_name=AgentName.BUILD_TEST_ANALYZER,
            event_type="build_test_analyzer.output",
            message="Build/test analyzer finished",
            metadata={
                **summarize_build_log_parse_result(result),
                "classification_hints": sorted(
                    {f.category.value for f in state.build_test_findings}
                ),
            },
        )

    return state


__all__ = [
    "BuildTestAnalyzerInput",
    "BuildTestAnalyzerLLMOutput",
    "BuildTestAnalyzerOutputParseError",
    "run_build_test_analyzer",
]
