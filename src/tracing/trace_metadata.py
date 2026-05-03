"""Safe summaries and redaction helpers for JSONL trace metadata."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from src.state import (
    ArtifactStatus,
    EvidenceItem,
    Finding,
    ObservedFailure,
    TriageState,
    ValidatedCheck,
)

_SENSITIVE_SUBSTRINGS = ("SECRET", "TOKEN", "PASSWORD", "DATABASE_URL")
_CREDENTIAL_IN_URL = re.compile(
    r"://[^:]+:[^@]+@", re.IGNORECASE
)


def truncate_trace_text(text: str, *, limit: int = 240) -> str:
    """Truncate text for traces; avoids dumping large excerpts."""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[: limit - 3]}..."


def redact_trace_value(value: object, *, limit: int = 240) -> Any:
    """Mask suspicious strings and truncate oversized trace-safe scalars."""
    if isinstance(value, dict):
        return {str(k): redact_trace_value(v, limit=limit) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_trace_value(item, limit=limit) for item in value]
    if isinstance(value, str):
        upper = value.upper()
        if any(marker in upper for marker in _SENSITIVE_SUBSTRINGS):
            return "[REDACTED]"
        if _CREDENTIAL_IN_URL.search(value):
            return "[REDACTED_URL]"
        return truncate_trace_text(value, limit=limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return truncate_trace_text(str(value), limit=limit)


def sanitize_trace_metadata(metadata: dict[str, Any], *, limit: int = 240) -> dict[str, Any]:
    """Deep-copy metadata with redaction and truncation applied."""
    cleaned = redact_trace_value(metadata, limit=limit)
    return cleaned if isinstance(cleaned, dict) else {"value": cleaned}


def summarize_artifacts(state: TriageState) -> dict[str, Any]:
    records = state.artifacts
    names = sorted(records.keys())
    loaded = sum(1 for r in records.values() if r.status == ArtifactStatus.LOADED)
    missing = sum(1 for r in records.values() if r.status == ArtifactStatus.MISSING)
    failed = sum(1 for r in records.values() if r.status == ArtifactStatus.FAILED)
    return {
        "artifact_count": len(names),
        "artifact_names": names,
        "loaded_count": loaded,
        "missing_count": missing,
        "failed_count": failed,
    }


def summarize_findings(findings: list[Finding]) -> dict[str, Any]:
    return {
        "finding_count": len(findings),
        "finding_ids": [f.finding_id for f in findings],
        "categories": sorted({f.category.value for f in findings}),
    }


def summarize_observed_failures(failures: list[ObservedFailure]) -> dict[str, Any]:
    return {
        "observed_failure_count": len(failures),
        "categories": sorted({f.category.value for f in failures}),
    }


def summarize_evidence(evidence: list[EvidenceItem]) -> dict[str, Any]:
    return {
        "evidence_count": len(evidence),
        "evidence_ids": [e.evidence_id for e in evidence],
        "locations": sorted({e.location or "" for e in evidence}),
    }


def summarize_checks(checks: list[ValidatedCheck]) -> dict[str, Any]:
    passed = sum(1 for c in checks if c.passed)
    return {
        "validated_check_count": len(checks),
        "passed_check_count": passed,
        "failed_check_count": len(checks) - passed,
        "check_ids": [c.check_id for c in checks],
    }


def summarize_causes(state: TriageState) -> dict[str, Any]:
    causes = state.suspected_causes
    return {
        "suspected_cause_count": len(causes),
        "cause_ids": [c.cause_id for c in causes],
    }


def summarize_actions(state: TriageState) -> dict[str, Any]:
    actions = state.recommended_actions
    return {
        "recommended_action_count": len(actions),
        "action_ids": [a.action_id for a in actions],
    }


def summarize_confidence_scores(state: TriageState) -> dict[str, Any]:
    scores = state.confidence_scores
    return {
        "confidence_score_count": len(scores),
        "score_ids": [s.score_id for s in scores],
    }


def summarize_build_log_parse_result(result: BaseModel) -> dict[str, Any]:
    findings = list(result.findings)  # type: ignore[attr-defined]
    evidence = list(result.evidence)  # type: ignore[attr-defined]
    failures = list(result.observed_failures)  # type: ignore[attr-defined]
    return {
        **summarize_observed_failures(failures),
        **summarize_findings(findings),
        **summarize_evidence(evidence),
    }


def summarize_ci_validation_result(result: BaseModel) -> dict[str, Any]:
    findings = list(result.findings)  # type: ignore[attr-defined]
    evidence = list(result.evidence)  # type: ignore[attr-defined]
    checks = list(result.validated_checks)  # type: ignore[attr-defined]
    check_meta = summarize_checks(checks)
    meta = {
        **summarize_findings(findings),
        **summarize_evidence(evidence),
        **check_meta,
    }
    meta["validation_summary"] = (
        f"{check_meta['passed_check_count']} passed / "
        f"{check_meta['validated_check_count']} checks"
        if checks
        else "no_checks"
    )
    return meta


def summarize_dockerfile_result(result: BaseModel) -> dict[str, Any]:
    findings = list(result.findings)  # type: ignore[attr-defined]
    evidence = list(result.evidence)  # type: ignore[attr-defined]
    checks = list(result.validated_checks)  # type: ignore[attr-defined]
    merged = {
        **summarize_findings(findings),
        **summarize_evidence(evidence),
        **summarize_checks(checks),
    }
    return merged


def summarize_dependency_result(result: BaseModel) -> dict[str, Any]:
    findings = list(result.findings)  # type: ignore[attr-defined]
    evidence = list(result.evidence)  # type: ignore[attr-defined]
    checks = list(result.validated_checks)  # type: ignore[attr-defined]
    merged = {
        **summarize_findings(findings),
        **summarize_evidence(evidence),
        **summarize_checks(checks),
    }
    return merged


def slm_state_context(state: TriageState) -> dict[str, Any]:
    all_findings = (
        state.build_test_findings + state.config_findings + state.dependency_findings
    )
    return {
        "finding_count": len(all_findings),
        "evidence_count": len(state.evidence),
        "validated_check_count": len(state.validated_checks),
        "observed_failure_count": len(state.observed_failures),
    }


def ollama_response_summary(parsed: BaseModel | None, *, raw_text: str) -> dict[str, Any]:
    fields = sorted(parsed.__class__.model_fields.keys()) if parsed else []
    return {
        "response_character_count": len(raw_text),
        "parsed": parsed is not None,
        "parsed_fields": fields,
    }


__all__ = [
    "ollama_response_summary",
    "redact_trace_value",
    "sanitize_trace_metadata",
    "slm_state_context",
    "summarize_actions",
    "summarize_artifacts",
    "summarize_build_log_parse_result",
    "summarize_checks",
    "summarize_ci_validation_result",
    "summarize_confidence_scores",
    "summarize_causes",
    "summarize_dependency_result",
    "summarize_dockerfile_result",
    "summarize_evidence",
    "summarize_findings",
    "summarize_observed_failures",
    "truncate_trace_text",
]
