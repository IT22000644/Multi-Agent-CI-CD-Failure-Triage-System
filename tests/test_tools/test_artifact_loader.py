from __future__ import annotations

from pathlib import Path

import pytest

from src.state import ArtifactCollection, ArtifactStatus, ArtifactType
from src.tools import load_incident_artifacts


def _write_required_files(incident_dir: Path) -> None:
    incident_dir.mkdir(parents=True, exist_ok=True)
    (incident_dir / "incident.json").write_text('{"incident_id":"tmp"}\n', encoding="utf-8")
    (incident_dir / "build.log").write_text("pytest -q\n", encoding="utf-8")
    (incident_dir / "test-report.txt").write_text("0 failed\n", encoding="utf-8")
    (incident_dir / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (incident_dir / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (incident_dir / "requirements.txt").write_text("pytest>=8.0.0\n", encoding="utf-8")


def test_complete_fixture_loads_successfully() -> None:
    result = load_incident_artifacts("fixtures/sample_incidents/incident_001")

    assert isinstance(result, ArtifactCollection)
    for required_name in [
        "incident.json",
        "build.log",
        "test-report.txt",
        "ci.yml",
        "Dockerfile",
        "requirements.txt",
    ]:
        assert required_name in result.records

    build_log = result.records["build.log"]
    assert build_log.status == ArtifactStatus.LOADED
    assert build_log.artifact_type == ArtifactType.LOG
    assert build_log.content is not None
    assert "DATABASE_URL is required" in build_log.content


def test_missing_required_files_are_reported_as_missing(tmp_path: Path) -> None:
    (tmp_path / "incident.json").write_text('{"incident_id":"tmp"}\n', encoding="utf-8")

    result = load_incident_artifacts(tmp_path)

    assert "build.log" in result.records
    build_log = result.records["build.log"]
    assert build_log.status == ArtifactStatus.MISSING
    assert build_log.error_message is not None


def test_optional_files_are_loaded_when_present(tmp_path: Path) -> None:
    _write_required_files(tmp_path)
    (tmp_path / "package.json").write_text('{"name":"sample"}\n', encoding="utf-8")

    result = load_incident_artifacts(tmp_path)

    assert "package.json" in result.records
    package_json = result.records["package.json"]
    assert package_json.status == ArtifactStatus.LOADED
    assert package_json.artifact_type == ArtifactType.DEPENDENCY_FILE


def test_optional_missing_files_are_not_included(tmp_path: Path) -> None:
    _write_required_files(tmp_path)

    result = load_incident_artifacts(tmp_path)

    assert "package.json" not in result.records


def test_invalid_path_raises_file_not_found_error(tmp_path: Path) -> None:
    missing_dir = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        load_incident_artifacts(missing_dir)


def test_file_path_instead_of_directory_raises_not_a_directory_error(tmp_path: Path) -> None:
    file_path = tmp_path / "incident.json"
    file_path.write_text('{"incident_id":"tmp"}\n', encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        load_incident_artifacts(file_path)