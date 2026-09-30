from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "runner.sh"


def test_runner_requires_one_argument() -> None:
    result = subprocess.run(
        ["bash", str(RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 64
    assert "Usage:" in result.stderr


def test_runner_rejects_invalid_organization() -> None:
    environment = os.environ.copy()
    environment["GITHUB_ORG_TOKEN"] = "pat"
    result = subprocess.run(
        ["bash", str(RUNNER), "invalid-"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 64
    assert "valid GitHub organization" in result.stderr


def test_runner_requires_token_environment_variable() -> None:
    environment = os.environ.copy()
    environment.pop("GITHUB_ORG_TOKEN", None)

    result = subprocess.run(
        ["bash", str(RUNNER), "acme"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 64
    assert "GITHUB_ORG_TOKEN" in result.stderr


def test_runner_forwards_pat_only_through_environment(tmp_path) -> None:
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    fake_docker = binary_directory / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "printf '%s' \"$GITHUB_TOKEN\" > \"$CAPTURE_TOKEN\"\n"
        "printf '%s\\n' \"$@\" > \"$CAPTURE_ARGS\"\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    token_capture = tmp_path / "token"
    argument_capture = tmp_path / "arguments"
    output_directory = tmp_path / "reports"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{binary_directory}{os.pathsep}{environment['PATH']}",
            "CAPTURE_TOKEN": str(token_capture),
            "CAPTURE_ARGS": str(argument_capture),
            "OUTPUT_DIR": str(output_directory),
            "ACTIONS_SCAN_IMAGE": "example/actions-scan:test",
            "GITHUB_ORG_TOKEN": "github_pat_secret",
        }
    )

    result = subprocess.run(
        ["bash", str(RUNNER), "acme"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0
    assert token_capture.read_text() == "github_pat_secret"
    arguments = argument_capture.read_text()
    assert "github_pat_secret" not in arguments
    assert "GITHUB_TOKEN" in arguments
    assert "example/actions-scan:test" in arguments
    assert "--org\nacme" in arguments
    assert output_directory.is_dir()
