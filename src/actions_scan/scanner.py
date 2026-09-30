from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from actions_scan.cache import CacheStore
from actions_scan.github import GitHubAPIError, GitHubClient
from actions_scan.models import Occurrence, Repository, RepositoryResult, ScanError
from actions_scan.parser import WorkflowParseError, parse_workflow


@dataclass
class ScanOutcome:
    organization: str
    occurrences: list[Occurrence]
    errors: list[ScanError]
    summary: dict[str, int]


def scan_organization(
    client: GitHubClient,
    cache: CacheStore,
    organization: str,
    *,
    concurrency: int,
    expected_active_repositories: int | None = None,
) -> ScanOutcome:
    errors: list[ScanError] = []
    if cache.load_error:
        errors.append(ScanError("", "cache", cache.path.name, None, cache.load_error))

    try:
        payloads = client.list_organization_repositories(organization)
    except GitHubAPIError as exc:
        errors.append(ScanError("", "repositories", "", exc.status, str(exc)))
        return ScanOutcome(
            organization,
            [],
            errors,
            _summary(
                visible=0,
                archived=0,
                active=0,
                results=[],
                references=0,
                failures=len(errors),
            ),
        )

    archived_count = sum(bool(item.get("archived")) for item in payloads)
    active_payloads = [item for item in payloads if not item.get("archived")]
    repositories: list[Repository] = []
    for payload in active_payloads:
        try:
            repository = Repository.from_api(payload)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(ScanError("", "repository_metadata", "", None, str(exc)))
            continue
        if not repository.default_branch:
            errors.append(
                ScanError(
                    repository.full_name,
                    "repository_metadata",
                    "",
                    None,
                    "repository has no default branch",
                )
            )
            continue
        repositories.append(repository)

    if (
        expected_active_repositories is not None
        and len(active_payloads) != expected_active_repositories
    ):
        errors.append(
            ScanError(
                "",
                "repository_scope",
                "",
                None,
                "expected "
                f"{expected_active_repositories} active repositories but the token can see "
                f"{len(active_payloads)}",
            )
        )

    results: list[RepositoryResult] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_scan_repository, client, cache, repository): repository
            for repository in repositories
        }
        for future in as_completed(futures):
            repository = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # Guard one repository from aborting the audit.
                errors.append(
                    ScanError(
                        repository.full_name,
                        "scan",
                        "",
                        None,
                        client.redact(_safe_exception(exc)),
                    )
                )

    results.sort(key=lambda item: item.repository.full_name.casefold())
    occurrences = sorted(
        (item for result in results for item in result.occurrences),
        key=lambda item: (
            item.repository.casefold(),
            item.workflow_path.casefold(),
            item.line,
            item.raw_uses.casefold(),
        ),
    )
    for result in results:
        errors.extend(result.errors)
    errors.sort(key=lambda item: (item.repository.casefold(), item.path, item.stage, item.message))

    cache.prune({repository.full_name for repository in repositories})
    return ScanOutcome(
        organization,
        occurrences,
        errors,
        _summary(
            visible=len(payloads),
            archived=archived_count,
            active=len(active_payloads),
            results=results,
            references=len(occurrences),
            failures=len(errors),
        ),
    )


def _scan_repository(
    client: GitHubClient, cache: CacheStore, repository: Repository
) -> RepositoryResult:
    entry = cache.get(repository.full_name)
    if entry and entry.get("default_branch") != repository.default_branch:
        cache.remove(repository.full_name)
        entry = None
    etag = str(entry.get("etag") or "") if entry else ""

    try:
        listing = client.list_workflows(repository, etag=etag)
    except GitHubAPIError as exc:
        return _api_failure(repository, "workflow_directory", ".github/workflows", exc)

    if listing.state == "not_modified":
        try:
            occurrences = cache.cached_occurrences(entry or {})
            workflow_count = int((entry or {}).get("workflow_count", 0))
        except (TypeError, ValueError) as exc:
            cache.remove(repository.full_name)
            return RepositoryResult(
                repository,
                [],
                0,
                [
                    ScanError(
                        repository.full_name,
                        "cache",
                        cache.path.name,
                        None,
                        f"cached repository data was invalid: {exc}",
                    )
                ],
            )
        return RepositoryResult(
            repository,
            occurrences,
            workflow_count,
            [],
            etag=etag,
            cache_hit=True,
        )

    if listing.state == "missing":
        cache.remove(repository.full_name)
        return RepositoryResult(repository, [], 0, [], workflows_missing=True)

    occurrences: list[Occurrence] = []
    errors: list[ScanError] = []
    for workflow_file in listing.files:
        try:
            source = client.get_file_text(repository, workflow_file.path)
        except GitHubAPIError as exc:
            errors.append(
                ScanError(
                    repository.full_name,
                    "workflow_content",
                    workflow_file.path,
                    exc.status,
                    str(exc),
                )
            )
            continue
        try:
            parsed = parse_workflow(source)
        except WorkflowParseError as exc:
            errors.append(
                ScanError(
                    repository.full_name,
                    "workflow_parse",
                    workflow_file.path,
                    None,
                    str(exc),
                )
            )
            continue
        occurrences.extend(
            _occurrence(repository, workflow_file.path, item) for item in parsed
        )

    result = RepositoryResult(
        repository,
        occurrences,
        len(listing.files),
        errors,
        etag=listing.etag,
    )
    if not errors:
        cache.put(
            repository.full_name,
            default_branch=repository.default_branch,
            etag=listing.etag,
            workflow_count=len(listing.files),
            occurrences=occurrences,
        )
    return result


def _occurrence(repository: Repository, workflow_path: str, parsed: Any) -> Occurrence:
    branch = quote(repository.default_branch, safe="")
    path = quote(workflow_path, safe="/")
    base_url = repository.html_url or f"https://github.com/{repository.full_name}"
    return Occurrence(
        repository=repository.full_name,
        visibility="private" if repository.private else "public",
        default_branch=repository.default_branch,
        workflow_path=workflow_path,
        workflow_name=parsed.workflow_name,
        job_id=parsed.job_id,
        location_type=parsed.location_type,
        step_index=parsed.step_index,
        step_name=parsed.step_name,
        line=parsed.line,
        reference_kind=parsed.reference_kind,
        target=parsed.target,
        ref=parsed.ref,
        inline_version_hint=parsed.inline_version_hint,
        raw_uses=parsed.raw_uses,
        workflow_url=f"{base_url}/blob/{branch}/{path}#L{parsed.line}",
    )


def _api_failure(
    repository: Repository, stage: str, path: str, exc: GitHubAPIError
) -> RepositoryResult:
    return RepositoryResult(
        repository,
        [],
        0,
        [ScanError(repository.full_name, stage, path, exc.status, str(exc))],
    )


def _summary(
    *,
    visible: int,
    archived: int,
    active: int,
    results: list[RepositoryResult],
    references: int,
    failures: int,
) -> dict[str, int]:
    return {
        "repositories_visible": visible,
        "repositories_archived_skipped": archived,
        "repositories_active": active,
        "repositories_scanned": len(results),
        "repositories_with_workflows": sum(item.workflow_count > 0 for item in results),
        "repositories_without_workflows": sum(item.workflow_count == 0 for item in results),
        "workflows_found": sum(item.workflow_count for item in results),
        "references_found": references,
        "cache_hits": sum(item.cache_hit for item in results),
        "failures": failures,
    }


def _safe_exception(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]
