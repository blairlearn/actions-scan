from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from actions_scan.github import API_VERSION
from actions_scan.models import Occurrence, ScanError
from actions_scan.scanner import ScanOutcome


OCCURRENCE_FIELDS = [
    "Repository name",
    "Workflow filename",
    "Action name",
    "Action version",
]
ERROR_FIELDS = ["repository", "stage", "path", "status", "message"]


def write_reports(
    output_directory: Path,
    outcome: ScanOutcome,
    *,
    generated_at: str | None = None,
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    _remove_temporary(str(output_directory / "unique-actions.csv"))
    _write_csv(
        output_directory / "occurrences.csv",
        OCCURRENCE_FIELDS,
        (_concise_occurrence(item) for item in outcome.occurrences),
    )
    _write_csv(
        output_directory / "errors.csv",
        ERROR_FIELDS,
        (item.to_dict() for item in outcome.errors),
    )
    payload = {
        "schema_version": 1,
        "generated_at": generated_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "organization": outcome.organization,
        "github_api_version": API_VERSION,
        "summary": outcome.summary,
        "occurrences": [item.to_dict() for item in outcome.occurrences],
        "errors": [item.to_dict() for item in outcome.errors],
    }
    _write_json(output_directory / "inventory.json", payload)


def _concise_occurrence(item: Occurrence) -> dict[str, Any]:
    repository_name = item.repository.split("/", 1)[-1]
    workflow_filename = item.workflow_path
    if item.workflow_path.startswith(".github/workflows/"):
        workflow_filename = item.workflow_path.rsplit("/", 1)[-1]
    return {
        "Repository name": repository_name,
        "Workflow filename": workflow_filename,
        "Action name": item.target or item.raw_uses,
        "Action version": item.ref,
    }


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    )
    try:
        with temporary:
            writer = csv.DictWriter(temporary, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary.name, path)
    except Exception:
        _remove_temporary(temporary.name)
        raise


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    )
    try:
        with temporary:
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary.name, path)
    except Exception:
        _remove_temporary(temporary.name)
        raise


def _remove_temporary(name: str) -> None:
    try:
        os.unlink(name)
    except FileNotFoundError:
        pass
