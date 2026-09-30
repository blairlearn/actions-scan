from __future__ import annotations

import csv
import json

import responses

from actions_scan.cache import CacheStore
from actions_scan.github import API_ROOT, GitHubClient
from actions_scan.reporting import write_reports
from actions_scan.scanner import scan_organization
from conftest import (
    add_repository_page,
    add_workflow_directory,
    add_workflow_file,
    repository_payload,
)


WORKFLOW = """\
name: CI
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: acme/build-action@abc123 # v1.4.0
"""


@responses.activate
def test_scan_skips_archived_and_writes_reports(tmp_path) -> None:
    add_repository_page(
        [repository_payload("active"), repository_payload("old", archived=True)]
    )
    path = ".github/workflows/ci.yml"
    add_workflow_directory("acme/active", [path, ".github/workflows/notes.txt"])
    add_workflow_file("acme/active", path, WORKFLOW)

    cache = CacheStore(tmp_path)
    outcome = scan_organization(
        GitHubClient("token", sleep=lambda _: None),
        cache,
        "acme",
        concurrency=2,
        expected_active_repositories=1,
    )
    cache.save()
    write_reports(tmp_path, outcome, generated_at="2026-09-30T00:00:00+00:00")

    assert outcome.errors == []
    assert outcome.summary == {
        "repositories_visible": 2,
        "repositories_archived_skipped": 1,
        "repositories_active": 1,
        "repositories_scanned": 1,
        "repositories_with_workflows": 1,
        "repositories_without_workflows": 0,
        "workflows_found": 1,
        "references_found": 2,
        "cache_hits": 0,
        "failures": 0,
    }
    assert {item.visibility for item in outcome.occurrences} == {"private"}
    assert {item.ref for item in outcome.occurrences} == {"v4", "abc123"}

    inventory = json.loads((tmp_path / "inventory.json").read_text())
    assert inventory["organization"] == "acme"
    assert len(inventory["occurrences"]) == 2
    with (tmp_path / "occurrences.csv").open(newline="") as stream:
        action_reader = csv.DictReader(stream)
        assert action_reader.fieldnames == [
            "Repository name",
            "Workflow filename",
            "Action name",
            "Action version",
        ]
        action_rows = list(action_reader)
    assert {row["Action name"] for row in action_rows} == {
        "actions/checkout",
        "acme/build-action",
    }
    assert {row["Repository name"] for row in action_rows} == {"active"}
    assert {row["Workflow filename"] for row in action_rows} == {"ci.yml"}
    assert {row["Action version"] for row in action_rows} == {"v4", "abc123"}
    assert not (tmp_path / "unique-actions.csv").exists()
    assert (tmp_path / "errors.csv").read_text().strip() == (
        "repository,stage,path,status,message"
    )
    assert (tmp_path / ".actions-inventory-cache.json").exists()


@responses.activate
def test_etag_reuses_cached_repository_result(tmp_path) -> None:
    path = ".github/workflows/ci.yml"
    add_repository_page([repository_payload("active")])
    add_workflow_directory("acme/active", [path], etag='"same-tree"')
    add_workflow_file("acme/active", path, WORKFLOW)
    cache = CacheStore(tmp_path)
    first = scan_organization(
        GitHubClient("token", sleep=lambda _: None), cache, "acme", concurrency=1
    )
    assert first.summary["references_found"] == 2
    cache.save()

    responses.reset()
    add_repository_page([repository_payload("active")])
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/acme/active/contents/.github/workflows",
        status=304,
    )
    second = scan_organization(
        GitHubClient("token", sleep=lambda _: None),
        CacheStore(tmp_path),
        "acme",
        concurrency=1,
    )

    assert second.errors == []
    assert second.summary["cache_hits"] == 1
    assert second.summary["references_found"] == 2
    directory_call = responses.calls[1].request
    assert directory_call.headers["If-None-Match"] == '"same-tree"'
    assert len(responses.calls) == 2


@responses.activate
def test_missing_workflow_directory_is_not_an_error(tmp_path) -> None:
    add_repository_page([repository_payload("empty")])
    add_workflow_directory("acme/empty", [], status=404)

    outcome = scan_organization(
        GitHubClient("token", sleep=lambda _: None),
        CacheStore(tmp_path),
        "acme",
        concurrency=1,
    )

    assert outcome.errors == []
    assert outcome.summary["repositories_without_workflows"] == 1


@responses.activate
def test_expected_repository_mismatch_is_a_failure(tmp_path) -> None:
    add_repository_page([])

    outcome = scan_organization(
        GitHubClient("token", sleep=lambda _: None),
        CacheStore(tmp_path),
        "acme",
        concurrency=1,
        expected_active_repositories=4,
    )

    assert outcome.summary["failures"] == 1
    assert outcome.errors[0].stage == "repository_scope"


@responses.activate
def test_workflow_access_error_preserves_other_results(tmp_path) -> None:
    add_repository_page([repository_payload("good"), repository_payload("denied")])
    path = ".github/workflows/ci.yml"
    add_workflow_directory("acme/good", [path])
    add_workflow_file("acme/good", path, WORKFLOW)
    add_workflow_directory("acme/denied", [path])
    add_workflow_file("acme/denied", path, WORKFLOW, status=403)

    outcome = scan_organization(
        GitHubClient("token", sleep=lambda _: None),
        CacheStore(tmp_path),
        "acme",
        concurrency=1,
    )

    assert len(outcome.occurrences) == 2
    assert outcome.summary["failures"] == 1
    assert outcome.errors[0].repository == "acme/denied"
    assert outcome.errors[0].stage == "workflow_content"
