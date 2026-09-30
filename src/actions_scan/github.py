from __future__ import annotations

import base64
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import requests

from actions_scan import __version__
from actions_scan.models import Repository


API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"


class GitHubAPIError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class WorkflowFile:
    path: str
    sha: str


@dataclass(frozen=True)
class DirectoryListing:
    state: str
    files: list[WorkflowFile]
    etag: str


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        timeout: tuple[float, float] = (5.0, 30.0),
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = token
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._local = threading.local()

    def list_organization_repositories(self, organization: str) -> list[dict[str, Any]]:
        repositories: list[dict[str, Any]] = []
        page = 1
        while True:
            response = self._request(
                "GET",
                f"{API_ROOT}/orgs/{quote(organization, safe='')}/repos",
                params={"type": "all", "per_page": 100, "page": page},
            )
            if response.status_code != 200:
                raise self._api_error(response)
            payload = self._json(response)
            if not isinstance(payload, list):
                raise GitHubAPIError(200, "repository list response was not a JSON array")
            repositories.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < 100:
                break
            page += 1
        return repositories

    def list_workflows(
        self, repository: Repository, *, etag: str = ""
    ) -> DirectoryListing:
        headers = {"If-None-Match": etag} if etag else None
        response = self._request(
            "GET",
            self._contents_url(repository, ".github/workflows"),
            params={"ref": repository.default_branch},
            headers=headers,
        )
        if response.status_code == 304:
            return DirectoryListing("not_modified", [], etag)
        if response.status_code == 404:
            return DirectoryListing("missing", [], "")
        if response.status_code != 200:
            raise self._api_error(response)

        payload = self._json(response)
        if not isinstance(payload, list):
            raise GitHubAPIError(200, "workflow directory response was not a JSON array")
        files = [
            WorkflowFile(path=str(item["path"]), sha=str(item.get("sha") or ""))
            for item in payload
            if isinstance(item, dict)
            and item.get("type") == "file"
            and str(item.get("name", "")).lower().endswith((".yml", ".yaml"))
            and item.get("path")
        ]
        files.sort(key=lambda item: item.path)
        return DirectoryListing("found", files, response.headers.get("ETag", ""))

    def get_file_text(self, repository: Repository, path: str) -> str:
        response = self._request(
            "GET",
            self._contents_url(repository, path),
            params={"ref": repository.default_branch},
        )
        if response.status_code != 200:
            raise self._api_error(response)
        payload = self._json(response)
        if not isinstance(payload, dict):
            raise GitHubAPIError(200, f"content response for {path} was not a JSON object")
        if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
            raise GitHubAPIError(200, f"content response for {path} did not contain base64 data")
        try:
            decoded = base64.b64decode(payload["content"]).decode("utf-8-sig")
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubAPIError(200, f"content response for {path} was not valid UTF-8") from exc
        return decoded

    def redact(self, message: str) -> str:
        """Remove the credential from an unexpected diagnostic."""
        return self._redact(message)

    def _contents_url(self, repository: Repository, path: str) -> str:
        repo = quote(repository.full_name, safe="/")
        return f"{API_ROOT}/repos/{repo}/contents/{quote(path, safe='/')}"

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(
                {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self._token}",
                    "User-Agent": f"actions-scan/{__version__}",
                    "X-GitHub-Api-Version": API_VERSION,
                }
            )
            self._local.session = session
        return session

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        last_exception: requests.RequestException | None = None
        for attempt in range(self._max_attempts):
            try:
                response = self._session().request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                last_exception = exc
                if attempt + 1 == self._max_attempts:
                    break
                self._sleep(min(2**attempt, 8))
                continue

            if not self._retryable(response) or attempt + 1 == self._max_attempts:
                return response
            delay = self._retry_delay(response, attempt)
            response.close()
            self._sleep(delay)

        message = self._redact(str(last_exception or "GitHub request failed"))
        raise GitHubAPIError(None, message)

    @staticmethod
    def _retryable(response: requests.Response) -> bool:
        if response.status_code == 429 or 500 <= response.status_code <= 599:
            return True
        if response.status_code != 403:
            return False
        body = response.text.lower()
        return (
            response.headers.get("X-RateLimit-Remaining") == "0"
            or "Retry-After" in response.headers
            or "secondary rate limit" in body
            or "rate limit exceeded" in body
        )

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 60.0)
            except ValueError:
                pass
        reset = response.headers.get("X-RateLimit-Reset")
        if reset and response.headers.get("X-RateLimit-Remaining") == "0":
            try:
                return min(max(float(reset) - time.time(), 0.0), 60.0)
            except ValueError:
                pass
        return float(min(2**attempt, 8))

    def _api_error(self, response: requests.Response) -> GitHubAPIError:
        message = "GitHub API request failed"
        try:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("message"):
                message = str(payload["message"])
        except requests.exceptions.JSONDecodeError:
            if response.text:
                message = response.text[:500]
        return GitHubAPIError(response.status_code, self._redact(message))

    @staticmethod
    def _json(response: requests.Response) -> Any:
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise GitHubAPIError(response.status_code, "GitHub API returned invalid JSON") from exc

    def _redact(self, message: str) -> str:
        return message.replace(self._token, "[REDACTED]")[:500]
