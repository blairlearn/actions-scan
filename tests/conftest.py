from __future__ import annotations

import base64
from typing import Any

import responses

from actions_scan.github import API_ROOT


def repository_payload(
    name: str,
    *,
    archived: bool = False,
    private: bool = True,
    default_branch: str = "main",
) -> dict[str, Any]:
    return {
        "full_name": f"acme/{name}",
        "name": name,
        "archived": archived,
        "private": private,
        "default_branch": default_branch,
        "html_url": f"https://github.com/acme/{name}",
    }


def add_repository_page(items: list[dict[str, Any]], *, status: int = 200) -> None:
    responses.add(
        responses.GET,
        f"{API_ROOT}/orgs/acme/repos",
        json=items if status == 200 else {"message": "repository listing failed"},
        status=status,
    )


def add_workflow_directory(
    repository: str,
    files: list[str],
    *,
    status: int = 200,
    etag: str = '"tree-etag"',
) -> None:
    payload: Any
    if status == 200:
        payload = [
            {
                "name": path.rsplit("/", 1)[-1],
                "path": path,
                "type": "file",
                "sha": f"sha-{index}",
            }
            for index, path in enumerate(files)
        ]
    else:
        payload = {"message": "Not Found"}
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/{repository}/contents/.github/workflows",
        json=payload,
        status=status,
        headers={"ETag": etag} if status == 200 else {},
    )


def add_workflow_file(repository: str, path: str, source: str, *, status: int = 200) -> None:
    if status == 200:
        payload = {
            "encoding": "base64",
            "content": base64.b64encode(source.encode()).decode(),
        }
    else:
        payload = {"message": "Forbidden"}
    responses.add(
        responses.GET,
        f"{API_ROOT}/repos/{repository}/contents/{path}",
        json=payload,
        status=status,
    )
