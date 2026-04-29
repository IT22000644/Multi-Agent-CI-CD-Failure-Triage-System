from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TriageBaseModel(BaseModel):
    """Base model with strict, assignment-safe Pydantic configuration for triage state."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class AgentName(StrEnum):
    """Named agents that can contribute evidence or findings."""

    COORDINATOR = "coordinator"
    BUILD_TEST_ANALYZER = "build_test_analyzer"
    INFRA_CONFIG_ANALYZER = "infra_config_analyzer"
    REMEDIATION_PLANNER = "remediation_planner"


class ArtifactType(StrEnum):
    """Supported artifact kinds that can be loaded for triage."""

    LOG = "log"
    TEST_REPORT = "test_report"
    WORKFLOW_YAML = "workflow_yaml"
    DOCKERFILE = "dockerfile"
    DEPENDENCY_FILE = "dependency_file"
    DIFF = "diff"
    STACK_TRACE = "stack_trace"
    OTHER = "other"


class ArtifactStatus(StrEnum):
    """Lifecycle status of an artifact as it is discovered and validated."""

    DISCOVERED = "discovered"
    QUEUED = "queued"
    LOADING = "loading"
    LOADED = "loaded"
    VALIDATED = "validated"
    FAILED = "failed"
    MISSING = "missing"
    SKIPPED = "skipped"


class FindingSeverity(StrEnum):
    """Severity levels used for findings and remediation risk."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FailureCategory(StrEnum):
    """Coarse failure categories used to organize observed failures and findings."""

    COMPILATION_ERROR = "compilation_error"
    TEST_FAILURE = "test_failure"
    DEPENDENCY_ISSUE = "dependency_issue"
    CI_CONFIG_ISSUE = "ci_config_issue"
    INFRASTRUCTURE_ISSUE = "infrastructure_issue"
    ENVIRONMENT_ISSUE = "environment_issue"
    RUNTIME_ERROR = "runtime_error"
    UNKNOWN = "unknown"


class ConfidenceLevel(StrEnum):
    """Qualitative confidence buckets derived from a numeric confidence score."""

    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class ConfidenceSubjectType(StrEnum):
    """Targets that a confidence score can be associated with."""

    FINDING = "finding"
    CAUSE = "cause"
    ACTION = "action"
    REPORT = "report"


class IncidentMetadata(TriageBaseModel):
    """Metadata that identifies and contextualizes a triage incident."""

    incident_id: str
    title: str | None = None
    description: str | None = None
    repository: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    pipeline_name: str | None = None
    run_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArtifactRecord(TriageBaseModel):
    """Loaded artifact with validation and loading status for the incident."""

    name: str
    artifact_type: ArtifactType
    path: str | None = None
    status: ArtifactStatus = ArtifactStatus.DISCOVERED
    content: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    error_message: str | None = None


class ArtifactCollection(TriageBaseModel):
    """Named collection of artifacts available for analysis."""

    records: dict[str, ArtifactRecord] = Field(default_factory=dict)
    loaded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str | None = None


class EvidenceItem(TriageBaseModel):
    """Concrete evidence snippet extracted from one or more artifacts."""

    evidence_id: str
    artifact_name: str
    artifact_type: ArtifactType | None = None
    location: str | None = None
    snippet: str
    agent_name: AgentName
    supports: str | None = None


class Finding(TriageBaseModel):
    """Analyzer output describing a concrete issue or observation."""

    finding_id: str
    agent_name: AgentName
    category: FailureCategory
    severity: FindingSeverity
    summary: str
    details: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ObservedFailure(TriageBaseModel):
    """Failure symptom observed in a pipeline artifact or execution trace."""

    category: FailureCategory
    summary: str
    source_artifact: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class SuspectedCause(TriageBaseModel):
    """Ranked hypothesis explaining why the failure occurred."""

    cause_id: str
    summary: str
    rationale: str
    related_finding_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    rank: int | None = Field(default=None, ge=1)


class RecommendedAction(TriageBaseModel):
    """Concrete remediation step recommended after triage analysis."""

    action_id: str
    summary: str
    details: str | None = None
    related_cause_ids: list[str] = Field(default_factory=list)
    risk_level: FindingSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    rank: int | None = Field(default=None, ge=1)


class ConfidenceScore(TriageBaseModel):
    """Confidence measurement tied to a specific finding, cause, action, or report."""

    score_id: str
    subject_type: ConfidenceSubjectType
    subject_id: str
    score: float = Field(ge=0.0, le=1.0)
    level: ConfidenceLevel
    rationale: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ValidatedCheck(TriageBaseModel):
    """Check performed to confirm or reject a triage hypothesis or artifact claim."""

    check_id: str
    summary: str
    passed: bool
    details: str | None = None
    agent_name: AgentName | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    validated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FinalReport(TriageBaseModel):
    """Final incident report produced by the remediation planner."""

    incident_id: str
    failure_classification: FailureCategory | None = None
    executive_summary: str | None = None
    root_cause_summary: str | None = None
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    evidence_summary: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TraceEvent(TriageBaseModel):
    """Observability event captured while the triage workflow is running."""

    event_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_name: AgentName | None = None
    event_type: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifact_name: str | None = None
    finding_id: str | None = None


class TriageState(TriageBaseModel):
    """Shared LangGraph state for end-to-end CI/CD failure triage."""

    metadata: IncidentMetadata
    artifacts: dict[str, ArtifactRecord] = Field(default_factory=dict)
    observed_failures: list[ObservedFailure] = Field(default_factory=list)
    build_test_findings: list[Finding] = Field(default_factory=list)
    config_findings: list[Finding] = Field(default_factory=list)
    dependency_findings: list[Finding] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    suspected_causes: list[SuspectedCause] = Field(default_factory=list)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    confidence_scores: list[ConfidenceScore] = Field(default_factory=list)
    validated_checks: list[ValidatedCheck] = Field(default_factory=list)
    final_report: FinalReport | None = None
    trace_events: list[TraceEvent] = Field(default_factory=list)


__all__ = [
    "AgentName",
    "ArtifactCollection",
    "ArtifactRecord",
    "ArtifactStatus",
    "ArtifactType",
    "ConfidenceLevel",
    "ConfidenceSubjectType",
    "ConfidenceScore",
    "EvidenceItem",
    "FailureCategory",
    "Finding",
    "FindingSeverity",
    "FinalReport",
    "IncidentMetadata",
    "ObservedFailure",
    "RecommendedAction",
    "SuspectedCause",
    "TraceEvent",
    "TriageState",
    "ValidatedCheck",
]
