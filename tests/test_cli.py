from __future__ import annotations

import json

import responses

from actions_scan.cli import main
from conftest import (
    add_repository_page,
    add_workflow_directory,
    add_workflow_file,
    repository_payload,
)


def test_missing_token_returns_invocation_error(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert main(["--org", "acme", "--output-dir", str(tmp_path)]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


@responses.activate
def test_cli_writes_all_reports_for_parse_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    path = ".github/workflows/broken.yml"
    add_repository_page([repository_payload("app")])
    add_workflow_directory("acme/app", [path])
    add_workflow_file("acme/app", path, "jobs:\n  build: [\n")

    exit_code = main(
        [
            "--org",
            "acme",
            "--output-dir",
            str(tmp_path),
            "--concurrency",
            "1",
        ]
    )

    assert exit_code == 1
    assert {path.name for path in tmp_path.iterdir()} >= {
        "occurrences.csv",
        "inventory.json",
        "errors.csv",
        ".actions-inventory-cache.json",
    }
    inventory = json.loads((tmp_path / "inventory.json").read_text())
    assert inventory["summary"]["failures"] == 1
    assert inventory["errors"][0]["stage"] == "workflow_parse"
