from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.state import TriageState
from src.tools import (
    inspect_dependencies,
    inspect_dockerfile,
    validate_ci_config,
)


class InfraConfigAnalyzerInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    state: TriageState


def _collect_dependency_artifacts(records: dict[str, object]):
    deps = []
    for name in ("requirements.txt", "package.json", "pyproject.toml"):
        if name in records:
            deps.append(records[name])
    return deps


def run_infra_config_analyzer(input_data: InfraConfigAnalyzerInput) -> TriageState:
    state = input_data.state.model_copy(deep=True)

    ci_art = state.artifacts.get("ci.yml")
    docker_art = state.artifacts.get("Dockerfile")
    dep_artifacts = _collect_dependency_artifacts(state.artifacts)

    ci_result = validate_ci_config(ci_art)
    docker_result = inspect_dockerfile(docker_art)
    dependency_result = inspect_dependencies(dep_artifacts)

    state.config_findings = list(ci_result.findings) + list(docker_result.findings)
    state.dependency_findings = list(dependency_result.findings)
    state.evidence = (
        list(state.evidence)
        + list(ci_result.evidence)
        + list(dependency_result.evidence)
        + list(docker_result.evidence)
    )
    state.validated_checks = (
        list(state.validated_checks)
        + list(ci_result.validated_checks)
        + list(dependency_result.validated_checks)
        + list(docker_result.validated_checks)
    )

    return state


__all__ = ["InfraConfigAnalyzerInput", "run_infra_config_analyzer"]
