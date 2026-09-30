from __future__ import annotations

from actions_scan.models import Occurrence
from actions_scan.reporting import _concise_occurrence


def occurrence(path: str) -> Occurrence:
    return Occurrence(
        repository="acme/widgets",
        visibility="private",
        default_branch="main",
        workflow_path=path,
        workflow_name="CI",
        job_id="build",
        location_type="step",
        step_index=1,
        step_name="Checkout",
        line=8,
        reference_kind="remote_action",
        target="actions/checkout",
        ref="v4",
        inline_version_hint="",
        raw_uses="actions/checkout@v4",
        workflow_url="https://github.com/acme/widgets/blob/main/example.yml#L8",
    )


def test_concise_report_omits_standard_workflow_path() -> None:
    row = _concise_occurrence(occurrence(".github/workflows/ci.yml"))

    assert row == {
        "Repository name": "widgets",
        "Workflow filename": "ci.yml",
        "Action name": "actions/checkout",
        "Action version": "v4",
    }


def test_concise_report_keeps_nonstandard_workflow_path() -> None:
    row = _concise_occurrence(occurrence("automation/ci.yml"))

    assert row["Workflow filename"] == "automation/ci.yml"
