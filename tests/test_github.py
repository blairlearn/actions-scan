from __future__ import annotations

import responses

from actions_scan.github import API_ROOT, GitHubClient
from conftest import repository_payload


@responses.activate
def test_repository_listing_paginates_past_one_hundred() -> None:
    first_page = [repository_payload(f"repo-{index}") for index in range(100)]
    second_page = [repository_payload("repo-100")]
    responses.add(responses.GET, f"{API_ROOT}/orgs/acme/repos", json=first_page)
    responses.add(responses.GET, f"{API_ROOT}/orgs/acme/repos", json=second_page)

    client = GitHubClient("secret-token", sleep=lambda _: None)
    result = client.list_organization_repositories("acme")

    assert len(result) == 101
    assert "page=1" in responses.calls[0].request.url
    assert "page=2" in responses.calls[1].request.url
    assert responses.calls[0].request.headers["Authorization"] == "Bearer secret-token"


@responses.activate
def test_rate_limit_response_is_retried() -> None:
    responses.add(
        responses.GET,
        f"{API_ROOT}/orgs/acme/repos",
        json={"message": "secondary rate limit"},
        status=429,
        headers={"Retry-After": "0"},
    )
    responses.add(responses.GET, f"{API_ROOT}/orgs/acme/repos", json=[])
    delays: list[float] = []

    client = GitHubClient("token", sleep=delays.append)

    assert client.list_organization_repositories("acme") == []
    assert delays == [0.0]


@responses.activate
def test_api_error_redacts_token() -> None:
    token = "do-not-print-this-token"
    responses.add(
        responses.GET,
        f"{API_ROOT}/orgs/acme/repos",
        json={"message": f"bad credential {token}"},
        status=401,
    )
    client = GitHubClient(token, sleep=lambda _: None)

    try:
        client.list_organization_repositories("acme")
    except Exception as exc:
        assert token not in str(exc)
        assert "[REDACTED]" in str(exc)
    else:
        raise AssertionError("expected an API error")
