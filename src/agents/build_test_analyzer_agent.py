from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.llm import StructuredLLMOutputError, parse_llm_json_output
from src.llm.ollama_client import generate_with_ollama
from src.state import AgentName, ArtifactType, EvidenceItem, TriageState
from src.tools import parse_build_and_test_logs


class BuildTestAnalyzerInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    state: TriageState


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

    build_log = state.artifacts.get("build.log")
    test_report = state.artifacts.get("test-report.txt")

    result = parse_build_and_test_logs(build_log, test_report)

    state.observed_failures = list(result.observed_failures)
    state.build_test_findings = list(result.findings)
    state.evidence = list(state.evidence) + list(result.evidence)

    prompt = _build_failure_interpretation_prompt(state)
    interpretation = _parse_build_test_llm_output(generate_with_ollama(prompt))
    _append_llm_interpretation_evidence(state, interpretation)

    return state


__all__ = [
    "BuildTestAnalyzerInput",
    "BuildTestAnalyzerLLMOutput",
    "BuildTestAnalyzerOutputParseError",
    "run_build_test_analyzer",
]
