# Repository instructions for agents

## Start here

Read `spec.md` before changing behavior. Treat it as the product contract. Read
`README.md` for the supported user experience and commands.

This is a small Python 3.11+ application packaged for Python 3.13 in Docker. There
are no repository-specific skills or external memory files; this document and
`spec.md` intentionally contain the durable agent context.

## Safety invariants

- Never read, print, commit, or copy the real token. The host wrapper reads
  `GITHUB_ORG_TOKEN`; the Python process reads `GITHUB_TOKEN`.
- Never add a token command-line option or interpolate its value into `docker run`.
- Keep GitHub operations read-only and keep the API root fixed to
  `https://api.github.com` with redirects disabled.
- Do not add GitHub write permissions, workflow execution, cloning, AI services, or
  external telemetry without an explicit product-spec change.
- Treat `output/` as sensitive generated data. Do not inspect or commit it unless a
  task explicitly requires diagnosis of those files and the user authorizes it.
- Preserve unrelated user changes and generated data.

## Required behavior to preserve

- Scan only accessible, non-archived repositories and their default branches.
- Parse direct workflow `uses:` nodes structurally.
- Keep `occurrences.csv` to exactly four ordered columns:
  `Repository name`, `Workflow filename`, `Action name`, `Action version`.
- Keep partial-result/error behavior, atomic report writes, ETag caching, bounded
  retries, and deterministic row ordering.
- Keep the production image non-root and free of test-only content.

## Code map

- `src/actions_scan/github.py`: authenticated read-only REST client and retries.
- `src/actions_scan/parser.py`: YAML AST traversal and reference classification.
- `src/actions_scan/scanner.py`: repository orchestration, concurrency, caching, and
  occurrence construction.
- `src/actions_scan/reporting.py`: concise CSV and diagnostic report contracts.
- `src/actions_scan/cache.py`: versioned, atomic ETag/result cache.
- `src/actions_scan/cli.py`: argument validation, environment token, exit statuses.
- `runner.sh`: host-side Docker wrapper using `GITHUB_ORG_TOKEN`.
- `Dockerfile`: `test` and non-root `runtime` stages.
- `tests/`: mocked API, parser, reporting, CLI, cache behavior, and runner tests.

## Validation

For any behavioral or packaging change, run:

```bash
bash -n runner.sh
python3 -m compileall -q src tests
docker build --target test -t actions-scan-test .
docker build -t actions-scan .
```

The Docker test target is the authoritative suite because local Python dependencies
may not be installed. Do not perform a live organization scan during routine tests.
Use mocked API responses.

For security or container changes, also verify:

```bash
docker image inspect actions-scan --format '{{.Config.User}} {{json .Config.Entrypoint}}'
docker run --rm --entrypoint id actions-scan
docker run --rm actions-scan --org acme
```

Expected properties: entry point `actions-scan`, non-root runtime identity, and exit
status 2 with a missing-token message when no `GITHUB_TOKEN` is provided.

## Change discipline

- Update `spec.md`, `README.md`, implementation, and tests together when an
  interface or report contract changes.
- Keep runtime and test dependency versions exact in the lock files. If direct
  dependencies change, keep `pyproject.toml` consistent.
- Increment the cache schema version when cached occurrence structure changes in an
  incompatible way.
- Add focused regression tests for every bug fix and edge case.
- Do not commit files from `output/`, Python caches, local environments, or tokens.
