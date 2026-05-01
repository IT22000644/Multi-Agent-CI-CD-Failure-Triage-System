from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.create_incident import create_incident_package


def _repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (repo_dir / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    return repo_dir


def test_create_incident_package_copies_metadata_and_repo_artifacts(tmp_path: Path) -> None:
    repo_dir = _repo(tmp_path)
    build_log = tmp_path / "build.log"
    build_log.write_text("ERROR: No matching distribution found\n", encoding="utf-8")

    result = create_incident_package(
        incident_id="local run 001",
        output_root=tmp_path / "incidents",
        repo_dir=repo_dir,
        title="Local run",
        description="Captured local run",
        repository="demo",
        build_log=build_log,
    )

    incident_dir = result.incident_dir
    metadata = json.loads((incident_dir / "incident.json").read_text(encoding="utf-8"))

    assert incident_dir.name == "local_run_001"
    assert metadata["incident_id"] == "local_run_001"
    assert (incident_dir / "build.log").exists()
    assert (incident_dir / "test-report.txt").exists()
    assert (incident_dir / "Dockerfile").exists()
    assert (incident_dir / "pyproject.toml").exists()


def test_create_incident_package_captures_commands(tmp_path: Path) -> None:
    repo_dir = _repo(tmp_path)

    result = create_incident_package(
        incident_id="command_capture",
        output_root=tmp_path / "incidents",
        repo_dir=repo_dir,
        title="Command capture",
        description="Captured commands",
        repository="demo",
        build_command="python --version",
        test_command="python --version",
    )

    build_log = result.incident_dir / "build.log"
    test_report = result.incident_dir / "test-report.txt"

    assert "$ python --version" in build_log.read_text(encoding="utf-8")
    assert "$ python --version" in test_report.read_text(encoding="utf-8")
    assert len(result.command_captures) == 2
    assert all(capture.exit_code == 0 for capture in result.command_captures)


def test_create_incident_package_refuses_existing_directory_without_overwrite(
    tmp_path: Path,
) -> None:
    repo_dir = _repo(tmp_path)
    incident_dir = tmp_path / "incidents" / "existing"
    incident_dir.mkdir(parents=True)
    (incident_dir / "incident.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_incident_package(
            incident_id="existing",
            output_root=tmp_path / "incidents",
            repo_dir=repo_dir,
            title="Existing",
            description="Existing",
            repository="demo",
        )
