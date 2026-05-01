"""Create a triage incident folder from local repo files and command output."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_COPY_FILES = [
    ("Dockerfile", "Dockerfile"),
    ("requirements.txt", "requirements.txt"),
    ("pyproject.toml", "pyproject.toml"),
    ("package.json", "package.json"),
    (".github/workflows/ci.yml", "ci.yml"),
    (".gitlab-ci.yml", "ci.yml"),
    ("ci.yml", "ci.yml"),
]


@dataclass
class CommandCapture:
    command: str
    output_name: str
    exit_code: int


@dataclass
class IncidentPackageResult:
    incident_dir: Path
    copied_files: list[Path]
    command_captures: list[CommandCapture]


def _safe_incident_id(incident_id: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in incident_id)
    safe = safe.strip("._-")
    if not safe:
        raise ValueError("incident_id must contain at least one safe filename character")
    return safe


def _copy_if_exists(repo_dir: Path, incident_dir: Path, source: str, target: str) -> Path | None:
    source_path = repo_dir / source
    if not source_path.is_file():
        return None

    target_path = incident_dir / target
    if target_path.exists():
        return None

    shutil.copy2(source_path, target_path)
    return target_path


def _copy_explicit_file(incident_dir: Path, source: Path, target_name: str) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Artifact file does not exist: {source}")
    target_path = incident_dir / target_name
    shutil.copy2(source, target_path)
    return target_path


def _run_command(
    repo_dir: Path,
    incident_dir: Path,
    command: str,
    output_name: str,
) -> CommandCapture:
    completed = subprocess.run(
        command,
        cwd=repo_dir,
        capture_output=True,
        shell=True,
        text=True,
        check=False,
    )
    output = [
        f"$ {command}",
        f"exit_code={completed.returncode}",
        "",
        "STDOUT:",
        completed.stdout,
        "",
        "STDERR:",
        completed.stderr,
    ]
    (incident_dir / output_name).write_text("\n".join(output), encoding="utf-8")
    return CommandCapture(
        command=command,
        output_name=output_name,
        exit_code=completed.returncode,
    )


def _write_incident_metadata(
    incident_dir: Path,
    *,
    incident_id: str,
    title: str,
    description: str,
    repository: str,
    branch: str | None,
    commit_sha: str | None,
    pipeline_name: str,
    run_id: str,
) -> Path:
    payload = {
        "incident_id": incident_id,
        "title": title,
        "description": description,
        "repository": repository,
        "branch": branch,
        "commit_sha": commit_sha,
        "pipeline_name": pipeline_name,
        "run_id": run_id,
    }
    path = incident_dir / "incident.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def create_incident_package(
    *,
    incident_id: str,
    output_root: Path,
    repo_dir: Path,
    title: str,
    description: str,
    repository: str,
    branch: str | None = None,
    commit_sha: str | None = None,
    pipeline_name: str = "local-validation",
    run_id: str = "manual",
    build_log: Path | None = None,
    test_report: Path | None = None,
    ci_config: Path | None = None,
    dockerfile: Path | None = None,
    dependency_file: Path | None = None,
    build_command: str | None = None,
    test_command: str | None = None,
    overwrite: bool = False,
) -> IncidentPackageResult:
    safe_id = _safe_incident_id(incident_id)
    incident_dir = output_root / safe_id
    if incident_dir.exists() and any(incident_dir.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Incident directory already exists and is not empty: {incident_dir}"
        )
    incident_dir.mkdir(parents=True, exist_ok=True)

    copied_files: list[Path] = []
    command_captures: list[CommandCapture] = []

    copied_files.append(
        _write_incident_metadata(
            incident_dir,
            incident_id=safe_id,
            title=title,
            description=description,
            repository=repository,
            branch=branch,
            commit_sha=commit_sha,
            pipeline_name=pipeline_name,
            run_id=run_id,
        )
    )

    explicit_files = [
        (build_log, "build.log"),
        (test_report, "test-report.txt"),
        (ci_config, "ci.yml"),
        (dockerfile, "Dockerfile"),
        (dependency_file, "requirements.txt"),
    ]
    for source, target in explicit_files:
        if source is not None:
            copied_files.append(_copy_explicit_file(incident_dir, source, target))

    for source, target in DEFAULT_COPY_FILES:
        copied = _copy_if_exists(repo_dir, incident_dir, source, target)
        if copied is not None:
            copied_files.append(copied)

    if build_command:
        command_captures.append(_run_command(repo_dir, incident_dir, build_command, "build.log"))

    if test_command:
        command_captures.append(
            _run_command(repo_dir, incident_dir, test_command, "test-report.txt")
        )

    for required_name in ("build.log", "test-report.txt"):
        target = incident_dir / required_name
        if not target.exists():
            target.write_text(
                f"No {required_name} was provided or captured for this incident.\n",
                encoding="utf-8",
            )

    return IncidentPackageResult(
        incident_dir=incident_dir,
        copied_files=copied_files,
        command_captures=command_captures,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a triage incident folder from local repo artifacts."
    )
    parser.add_argument("--id", required=True, help="Incident ID / output folder name.")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="Repository root.")
    parser.add_argument("--output-root", default=".tmp/incidents", help="Incident output root.")
    parser.add_argument("--title", default="Local CI/CD validation incident")
    parser.add_argument(
        "--description",
        default="Local command outputs and repository artifacts packaged for triage.",
    )
    parser.add_argument("--repository", default=REPO_ROOT.name)
    parser.add_argument("--branch", default=None)
    parser.add_argument("--commit-sha", default=None)
    parser.add_argument("--pipeline-name", default="local-validation")
    parser.add_argument("--run-id", default="manual")
    parser.add_argument("--build-log", type=Path, default=None)
    parser.add_argument("--test-report", type=Path, default=None)
    parser.add_argument("--ci-config", type=Path, default=None)
    parser.add_argument("--dockerfile", type=Path, default=None)
    parser.add_argument("--dependency-file", type=Path, default=None)
    parser.add_argument("--build-command", default=None)
    parser.add_argument("--test-command", default=None)
    parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args(argv)

    try:
        result = create_incident_package(
            incident_id=args.id,
            output_root=Path(args.output_root),
            repo_dir=Path(args.repo),
            title=args.title,
            description=args.description,
            repository=args.repository,
            branch=args.branch,
            commit_sha=args.commit_sha,
            pipeline_name=args.pipeline_name,
            run_id=args.run_id,
            build_log=args.build_log,
            test_report=args.test_report,
            ci_config=args.ci_config,
            dockerfile=args.dockerfile,
            dependency_file=args.dependency_file,
            build_command=args.build_command,
            test_command=args.test_command,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(f"Failed to create incident package: {exc}", file=sys.stderr)
        return 1

    print(f"Incident package created: {result.incident_dir}")
    for copied in result.copied_files:
        print(f"Copied: {copied}")
    for capture in result.command_captures:
        print(
            f"Captured command to {capture.output_name}: "
            f"exit_code={capture.exit_code} command={capture.command}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
