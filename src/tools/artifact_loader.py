from __future__ import annotations

from pathlib import Path

from src.state import ArtifactCollection, ArtifactRecord, ArtifactStatus, ArtifactType

REQUIRED_ARTIFACTS: dict[str, ArtifactType] = {
    "incident.json": ArtifactType.OTHER,
    "build.log": ArtifactType.LOG,
    "test-report.txt": ArtifactType.TEST_REPORT,
    "ci.yml": ArtifactType.WORKFLOW_YAML,
    "Dockerfile": ArtifactType.DOCKERFILE,
    "requirements.txt": ArtifactType.DEPENDENCY_FILE,
}

OPTIONAL_ARTIFACTS: dict[str, ArtifactType] = {
    "diff.patch": ArtifactType.DIFF,
    "commit.txt": ArtifactType.OTHER,
    "package.json": ArtifactType.DEPENDENCY_FILE,
    "pyproject.toml": ArtifactType.DEPENDENCY_FILE,
    "docker-compose.yml": ArtifactType.WORKFLOW_YAML,
}


def _load_record(path: Path, name: str, artifact_type: ArtifactType) -> ArtifactRecord:
    if not path.exists():
        return ArtifactRecord(
            name=name,
            artifact_type=artifact_type,
            status=ArtifactStatus.MISSING,
            path=None,
            content=None,
            size_bytes=None,
            error_message=f"Required artifact '{name}' is missing.",
        )

    try:
        content = path.read_text(encoding="utf-8")
        return ArtifactRecord(
            name=name,
            artifact_type=artifact_type,
            status=ArtifactStatus.LOADED,
            path=str(path),
            content=content,
            size_bytes=path.stat().st_size,
            error_message=None,
        )
    except (OSError, UnicodeError) as exc:
        return ArtifactRecord(
            name=name,
            artifact_type=artifact_type,
            status=ArtifactStatus.FAILED,
            path=str(path),
            content=None,
            size_bytes=None,
            error_message=f"Failed to read artifact '{name}': {exc}",
        )


def load_incident_artifacts(incident_dir: str | Path) -> ArtifactCollection:
    """Load known artifacts from a local incident directory into typed records."""

    incident_path = Path(incident_dir)

    if not incident_path.exists():
        raise FileNotFoundError(f"Incident directory does not exist: {incident_path}")
    if not incident_path.is_dir():
        raise NotADirectoryError(f"Incident path is not a directory: {incident_path}")

    records: dict[str, ArtifactRecord] = {}

    for file_name, artifact_type in REQUIRED_ARTIFACTS.items():
        file_path = incident_path / file_name
        records[file_name] = _load_record(file_path, file_name, artifact_type)

    for file_name, artifact_type in OPTIONAL_ARTIFACTS.items():
        file_path = incident_path / file_name
        if file_path.exists():
            records[file_name] = _load_record(file_path, file_name, artifact_type)

    return ArtifactCollection(records=records, source=str(incident_path))


__all__ = ["load_incident_artifacts"]