from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Repository:
    full_name: str
    default_branch: str
    private: bool
    html_url: str

    @classmethod
    def from_api(cls, value: dict[str, Any]) -> "Repository":
        return cls(
            full_name=str(value["full_name"]),
            default_branch=str(value.get("default_branch") or ""),
            private=bool(value.get("private", False)),
            html_url=str(value.get("html_url") or ""),
        )


@dataclass(frozen=True)
class ParsedUse:
    workflow_name: str
    job_id: str
    location_type: str
    step_index: int | None
    step_name: str
    line: int
    reference_kind: str
    target: str
    ref: str
    inline_version_hint: str
    raw_uses: str


@dataclass(frozen=True)
class Occurrence:
    repository: str
    visibility: str
    default_branch: str
    workflow_path: str
    workflow_name: str
    job_id: str
    location_type: str
    step_index: int | None
    step_name: str
    line: int
    reference_kind: str
    target: str
    ref: str
    inline_version_hint: str
    raw_uses: str
    workflow_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Occurrence":
        return cls(**value)


@dataclass(frozen=True)
class ScanError:
    repository: str
    stage: str
    path: str
    status: int | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepositoryResult:
    repository: Repository
    occurrences: list[Occurrence]
    workflow_count: int
    errors: list[ScanError]
    etag: str = ""
    cache_hit: bool = False
    workflows_missing: bool = False
