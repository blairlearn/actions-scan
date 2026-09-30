from __future__ import annotations

import pytest

from actions_scan.parser import WorkflowParseError, classify_reference, parse_workflow


WORKFLOW = """\
name: Build
on: push
jobs:
  delegated:
    uses: acme/shared/.github/workflows/build.yml@v3
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - uses: owner/tool@0123456789012345678901234567890123456789 # v2.4.1
      - uses: ./.github/actions/local
      - uses: docker://ghcr.io/acme/tool:1.2.0
      - uses: ${{ matrix.action }}
"""


def test_parse_direct_job_and_step_references() -> None:
    values = parse_workflow(WORKFLOW)

    assert len(values) == 6
    assert values[0].workflow_name == "Build"
    assert values[0].location_type == "job"
    assert values[0].reference_kind == "reusable_workflow"
    assert values[0].target == "acme/shared/.github/workflows/build.yml"
    assert values[0].ref == "v3"

    checkout = values[1]
    assert checkout.job_id == "build"
    assert checkout.step_index == 1
    assert checkout.step_name == "Checkout"
    assert checkout.line == 10
    assert checkout.reference_kind == "remote_action"
    assert checkout.target == "actions/checkout"
    assert checkout.ref == "v4"

    pinned = values[2]
    assert pinned.inline_version_hint == "v2.4.1"
    assert pinned.ref == "0123456789012345678901234567890123456789"
    assert values[3].reference_kind == "local_action"
    assert values[4].reference_kind == "docker_image"
    assert values[4].target == "ghcr.io/acme/tool"
    assert values[4].ref == "1.2.0"
    assert values[5].reference_kind == "unresolved"


@pytest.mark.parametrize(
    ("value", "kind", "target", "ref"),
    [
        ("actions/checkout@v4", "remote_action", "actions/checkout", "v4"),
        ("./local", "local_action", "./local", ""),
        ("docker://alpine@sha256:abc", "docker_image", "alpine", "sha256:abc"),
        ("docker://registry:5000/image", "docker_image", "registry:5000/image", ""),
        ("missing-ref", "unresolved", "missing-ref", ""),
    ],
)
def test_classify_reference(value: str, kind: str, target: str, ref: str) -> None:
    result = classify_reference(value)
    assert (result.kind, result.target, result.ref) == (kind, target, ref)


def test_malformed_yaml_is_reported() -> None:
    with pytest.raises(WorkflowParseError):
        parse_workflow("jobs:\n  build: [\n")


def test_non_mapping_jobs_is_reported() -> None:
    with pytest.raises(WorkflowParseError, match="jobs"):
        parse_workflow("jobs: []\n")


def test_non_string_uses_is_unresolved() -> None:
    value = parse_workflow("jobs:\n  build:\n    steps:\n      - uses: 123\n")[0]
    assert value.reference_kind == "unresolved"
    assert value.raw_uses == "123"


def test_local_job_reference_is_a_local_reusable_workflow() -> None:
    value = parse_workflow(
        "jobs:\n  delegated:\n    uses: ./.github/workflows/build.yml\n"
    )[0]
    assert value.reference_kind == "local_reusable_workflow"
