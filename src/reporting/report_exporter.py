from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from src.state import Finding, TriageState


class ReportExportResult(BaseModel):
    incident_id: str
    report_dir: Path
    summary_json_path: Path
    markdown_report_path: Path


def _classification_value(state: TriageState) -> str:
    if state.final_report and state.final_report.failure_classification:
        return state.final_report.failure_classification.value
    return "unknown"


def _finding_lines(title: str, findings: list[Finding]) -> list[str]:
    lines = [f"## {title}", ""]
    if not findings:
        lines.extend(["No findings recorded.", ""])
        return lines

    for finding in findings:
        lines.extend(
            [
                f"### {finding.finding_id}: {finding.summary}",
                "",
                f"- Category: `{finding.category.value}`",
                f"- Severity: `{finding.severity.value}`",
            ]
        )
        if finding.details:
            lines.append(f"- Details: {finding.details}")
        if finding.evidence_ids:
            lines.append(f"- Evidence IDs: {', '.join(finding.evidence_ids)}")
        lines.append("")

    return lines


def _build_markdown_report(state: TriageState, trace_file: str | None) -> str:
    metadata = state.metadata
    lines = [
        f"# CI/CD Failure Triage Report: {metadata.incident_id}",
        "",
        "## Incident Metadata",
        "",
        f"- Incident ID: `{metadata.incident_id}`",
        f"- Title: {metadata.title or 'N/A'}",
        f"- Repository: {metadata.repository or 'N/A'}",
        f"- Branch: {metadata.branch or 'N/A'}",
        f"- Commit SHA: {metadata.commit_sha or 'N/A'}",
        f"- Pipeline: {metadata.pipeline_name or 'N/A'}",
        f"- Run ID: {metadata.run_id or 'N/A'}",
        "",
        "## Classification",
        "",
        f"`{_classification_value(state)}`",
        "",
    ]

    executive_summary = (
        state.final_report.executive_summary if state.final_report else None
    )
    root_cause_summary = (
        state.final_report.root_cause_summary if state.final_report else None
    )

    if executive_summary:
        lines.extend(["## Executive Summary", "", executive_summary, ""])

    if root_cause_summary and root_cause_summary != executive_summary:
        lines.extend(["## Root Cause Summary", "", root_cause_summary, ""])

    lines.extend(["## Observed Failures", ""])
    if state.observed_failures:
        for failure in state.observed_failures:
            lines.extend(
                [
                    f"- `{failure.category.value}`: {failure.summary}",
                    f"  - Source: {failure.source_artifact or 'N/A'}",
                ]
            )
            if failure.evidence_ids:
                lines.append(f"  - Evidence IDs: {', '.join(failure.evidence_ids)}")
    else:
        lines.append("No observed failures recorded.")
    lines.append("")

    lines.extend(_finding_lines("Build/Test Findings", state.build_test_findings))
    lines.extend(_finding_lines("Config Findings", state.config_findings))
    lines.extend(_finding_lines("Dependency Findings", state.dependency_findings))

    lines.extend(["## Evidence", ""])
    if state.evidence:
        for evidence in state.evidence:
            lines.extend(
                [
                    f"### {evidence.evidence_id}",
                    "",
                    f"- Artifact: `{evidence.artifact_name}`",
                    f"- Agent: `{evidence.agent_name.value}`",
                    f"- Supports: {evidence.supports or 'N/A'}",
                    "",
                    "```text",
                    evidence.snippet,
                    "```",
                    "",
                ]
            )
    else:
        lines.extend(["No evidence recorded.", ""])

    lines.extend(["## Suspected Causes", ""])
    if state.suspected_causes:
        for cause in state.suspected_causes:
            lines.extend(
                [
                    f"- {cause.rank or '?'}: {cause.summary}",
                    f"  - Confidence: {cause.confidence:.2f}",
                    f"  - Rationale: {cause.rationale}",
                ]
            )
    else:
        lines.append("No suspected causes recorded.")
    lines.append("")

    lines.extend(["## Recommended Actions", ""])
    if state.recommended_actions:
        for action in state.recommended_actions:
            lines.extend(
                [
                    f"- {action.rank or '?'}: {action.summary}",
                    f"  - Risk: `{action.risk_level.value}`",
                    f"  - Confidence: {action.confidence:.2f}",
                ]
            )
            if action.details:
                lines.append(f"  - Details: {action.details}")
    else:
        lines.append("No recommended actions recorded.")
    lines.append("")

    lines.extend(["## Confidence Scores", ""])
    if state.confidence_scores:
        for score in state.confidence_scores:
            lines.extend(
                [
                    f"- `{score.score_id}`: {score.level.value} ({score.score:.2f})",
                    f"  - Subject: {score.subject_type.value} `{score.subject_id}`",
                ]
            )
            if score.rationale:
                lines.append(f"  - Rationale: {score.rationale}")
    else:
        lines.append("No confidence scores recorded.")
    lines.append("")

    lines.extend(["## Trace", "", f"- Trace file: `{trace_file or 'N/A'}`", ""])
    return "\n".join(lines)


def export_report(
    state: TriageState,
    output_dir: str | Path,
    trace_file: str | Path | None = None,
) -> ReportExportResult:
    report_dir = Path(output_dir) / state.metadata.incident_id
    report_dir.mkdir(parents=True, exist_ok=True)

    trace_file_text = str(trace_file) if trace_file is not None else None
    summary_json_path = report_dir / "summary.json"
    markdown_report_path = report_dir / "report.md"

    payload = {
        "incident_id": state.metadata.incident_id,
        "classification": _classification_value(state),
        "trace_file": trace_file_text,
        "state": state.model_dump(mode="json"),
    }
    summary_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown_report_path.write_text(
        _build_markdown_report(state, trace_file_text),
        encoding="utf-8",
    )

    return ReportExportResult(
        incident_id=state.metadata.incident_id,
        report_dir=report_dir,
        summary_json_path=summary_json_path,
        markdown_report_path=markdown_report_path,
    )


__all__ = ["ReportExportResult", "export_report"]
