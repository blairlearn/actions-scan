from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from actions_scan.cache import CacheStore
from actions_scan.github import GitHubClient
from actions_scan.models import ScanError
from actions_scan.reporting import write_reports
from actions_scan.scanner import scan_organization


ORGANIZATION_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="actions-scan",
        description="Inventory direct GitHub Actions references across an organization.",
    )
    parser.add_argument("--org", required=True, help="GitHub organization login")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/output"),
        help="report and cache directory (default: /output)",
    )
    parser.add_argument(
        "--concurrency",
        type=_bounded_concurrency,
        default=5,
        help="concurrent repository scans, 1-20 (default: 5)",
    )
    parser.add_argument(
        "--expected-active-repos",
        type=_nonnegative_integer,
        help="fail if the token sees a different number of non-archived repositories",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not ORGANIZATION_PATTERN.fullmatch(args.org):
        parser.error("--org must be a valid GitHub organization login")

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("error: GITHUB_TOKEN must be set", file=sys.stderr)
        return 2

    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        cache = CacheStore(args.output_dir)
    except OSError as exc:
        print(f"error: cannot use output directory {args.output_dir}: {exc}", file=sys.stderr)
        return 2

    client = GitHubClient(token)
    outcome = scan_organization(
        client,
        cache,
        args.org,
        concurrency=args.concurrency,
        expected_active_repositories=args.expected_active_repos,
    )
    try:
        cache.save()
    except OSError as exc:
        outcome.errors.append(
            ScanError("", "cache_write", cache.path.name, None, str(exc)[:500])
        )
        outcome.summary["failures"] = len(outcome.errors)

    try:
        write_reports(args.output_dir, outcome)
    except OSError as exc:
        print(f"error: cannot write reports to {args.output_dir}: {exc}", file=sys.stderr)
        return 2

    summary = outcome.summary
    print(
        "Scanned "
        f"{summary['repositories_scanned']}/{summary['repositories_active']} active repositories; "
        f"found {summary['references_found']} references in {summary['workflows_found']} workflows; "
        f"failures: {summary['failures']}.",
        file=sys.stderr,
    )
    return 1 if outcome.errors else 0


def _bounded_concurrency(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 20:
        raise argparse.ArgumentTypeError("must be between 1 and 20")
    return parsed


def _nonnegative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
