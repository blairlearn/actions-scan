from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from actions_scan.models import Occurrence


CACHE_VERSION = 1
CACHE_NAME = ".actions-inventory-cache.json"


class CacheStore:
    def __init__(self, output_directory: Path) -> None:
        self.path = output_directory / CACHE_NAME
        self._lock = threading.Lock()
        self.load_error = ""
        self._repositories: dict[str, dict[str, Any]] = {}
        self._load()

    def get(self, repository: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._repositories.get(repository)
            return dict(value) if value is not None else None

    def put(
        self,
        repository: str,
        *,
        default_branch: str,
        etag: str,
        workflow_count: int,
        occurrences: list[Occurrence],
    ) -> None:
        with self._lock:
            self._repositories[repository] = {
                "default_branch": default_branch,
                "etag": etag,
                "workflow_count": workflow_count,
                "occurrences": [item.to_dict() for item in occurrences],
            }

    def remove(self, repository: str) -> None:
        with self._lock:
            self._repositories.pop(repository, None)

    def prune(self, active_repositories: set[str]) -> None:
        with self._lock:
            self._repositories = {
                name: value
                for name, value in self._repositories.items()
                if name in active_repositories
            }

    def cached_occurrences(self, entry: dict[str, Any]) -> list[Occurrence]:
        values = entry.get("occurrences")
        if not isinstance(values, list):
            raise ValueError("cached occurrences were not a list")
        if not all(isinstance(item, dict) for item in values):
            raise ValueError("cached occurrence was not an object")
        return [Occurrence.from_dict(item) for item in values]

    def save(self) -> None:
        payload = {"version": CACHE_VERSION, "repositories": self._repositories}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        )
        try:
            with temporary:
                json.dump(payload, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
            os.replace(temporary.name, self.path)
        except Exception:
            try:
                os.unlink(temporary.name)
            except FileNotFoundError:
                pass
            raise

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != CACHE_VERSION:
                raise ValueError("unsupported cache schema version")
            repositories = payload.get("repositories")
            if not isinstance(repositories, dict):
                raise ValueError("cache repositories value was not an object")
            self._repositories = repositories
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.load_error = f"Ignoring invalid cache: {exc}"
            self._repositories = {}
