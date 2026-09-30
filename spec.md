# actions-scan specification

## Status and authority

This document defines the required behavior of `actions-scan`. It is the
authoritative product specification. `README.md` is the concise user guide, and
`AGENTS.md` contains repository-working instructions. When behavior changes, update
this document, the implementation, tests, and user documentation together.

## Purpose

`actions-scan` creates an organization-wide inventory of direct GitHub Actions
`uses:` references. It must work for public and private repositories visible to a
fine-grained read-only personal access token, exclude archived repositories, and
make no changes to GitHub.

The scanner is deterministic software. It does not use AI services.

## Supported environment and inputs

- Target platform: GitHub.com.
- Execution environment: the supplied Docker image.
- Primary entry point: `runner.sh ORGANIZATION`.
- `runner.sh` reads the PAT from `GITHUB_ORG_TOKEN` and passes it into the container
  as `GITHUB_TOKEN`. The PAT must never be accepted as a command-line argument.
- The container entry point is `actions-scan` and supports:

  ```text
  actions-scan --org ORGANIZATION
               [--output-dir /output]
               [--concurrency 5]
               [--expected-active-repos NUMBER]
  ```

- `--concurrency` accepts integers from 1 through 20.
- `--expected-active-repos` is optional. A mismatch is a reported failure because
  the GitHub repository-list API cannot reveal repositories hidden from the token.
- `runner.sh` writes to `output/` beside the script by default. `OUTPUT_DIR` and
  `ACTIONS_SCAN_IMAGE` may override the output directory and image name.

## Authentication and security requirements

- Use a fine-grained PAT selected for every repository that should be scanned.
- The only required repository permission is **Contents: read**. Metadata read is
  implicit for fine-grained PATs.
- All GitHub operations must be read-only HTTP requests.
- The token must not be written to reports, cache files, exceptions, or logs.
- API-provided error text and unexpected diagnostics must be token-redacted.
- Runtime network requests are restricted to the fixed
  `https://api.github.com` API root. Redirect following is disabled so credentials
  cannot be forwarded to another host.
- The production container runs as an unprivileged user. The documented runner may
  override the container UID/GID with the invoking Unix user for bind-mount
  ownership.
- Generated `output/` data may reveal private repository names and workflow usage.
  It is ignored by Git and must not be committed.

## Repository discovery

1. Enumerate all repositories accessible to the token through the paginated
   organization repositories REST endpoint with `type=all` and `per_page=100`.
2. Exclude every repository whose API metadata has `archived: true`.
3. Include private, public, internal, forked, and disabled repositories unless they
   are archived. An inaccessible repository cannot be inventoried.
4. Scan only each repository's default branch.
5. A repository without a default branch is reported as an error without aborting
   other repositories.

## Workflow discovery and parsing

- Request `.github/workflows` through the authenticated Contents API.
- A `404` for that directory means the repository has no workflows and is not an
  error.
- Parse direct `.yml` and `.yaml` files in that directory. Ignore other file types.
- Parse YAML structurally; do not inventory commented-out text or use regular
  expressions as the source of truth.
- Extract direct references from:
  - `jobs.<job_id>.steps[*].uses`
  - `jobs.<job_id>.uses`
- Preserve the literal referenced ref after the final `@`, whether it is a version
  tag, branch, or commit SHA.
- Recognize remote actions, remote reusable workflows, local actions, local
  reusable workflows, Docker references, and unresolved/unsupported values.
- A malformed workflow is recorded in `errors.csv`; valid workflows and other
  repositories must still be processed.
- Do not recursively expand local or remote composite actions or reusable
  workflows.
- Do not scan non-default branches or Git history.
- Do not decide whether a version is current or outdated. Freshness review is a
  separate manual process.

## Primary CSV contract

`occurrences.csv` is the primary deliverable. It contains one row for every direct
`uses:` occurrence and exactly these columns, in this order:

```text
Repository name,Workflow filename,Action name,Action version
```

Column rules:

- **Repository name:** omit the organization prefix. `acme/widgets` becomes
  `widgets`.
- **Workflow filename:** for files under `.github/workflows/`, emit only the base
  filename. Preserve the full path if a future input can identify a workflow
  outside that directory.
- **Action name:** emit the parsed action/workflow/container/local target. If the
  value cannot be parsed, emit the original `uses:` value.
- **Action version:** emit the exact parsed ref. Leave it empty for reference types
  without a ref, such as a local action.

Rows are sorted deterministically by repository, workflow path, source line, and
raw `uses:` value. Duplicate uses at different locations remain separate rows.

## Diagnostic outputs

All files are written under the selected output directory:

- `occurrences.csv`: concise four-column primary report.
- `errors.csv`: repository, stage, path, HTTP status, and message for failures. It
  contains a header even when there are no failures.
- `inventory.json`: detailed machine-readable scan metadata, summary counts,
  occurrence metadata, and errors.
- `.actions-inventory-cache.json`: cache schema version, workflow-directory ETags,
  and prior successful occurrence details. It contains no credentials.

The obsolete `unique-actions.csv` is removed when reports are written. Report files
are replaced atomically. A partial scan still writes every usable result and all
known errors.

## Caching, concurrency, and resilience

- Use workflow-directory ETags with `If-None-Match`.
- On `304 Not Modified`, reuse the successful cached result for that repository.
- Do not replace a repository's valid cache entry with a partial or failed result.
- Remove cache entries for archived/no-longer-active repositories and repositories
  whose workflow directory no longer exists.
- Use bounded repository-level concurrency.
- Retry request exceptions, `429`, `5xx`, and rate-limit `403` responses up to four
  attempts with bounded backoff. Respect numeric `Retry-After` and rate-limit reset
  headers, capped at 60 seconds per delay.
- One repository failure must not abort scanning other repositories.

## Exit status

- `0`: scan and report generation completed without reported failures.
- `1`: partial scan, invalid workflow/cache, API failure, or expected repository
  count mismatch. Reports are still written.
- `2`: invalid invocation, missing token, or unusable output/report directory.

## Container requirements

- Use the pinned slim Python base image declared in `Dockerfile`.
- Install exact runtime versions from `requirements.lock`.
- The final `runtime` image excludes tests and test-only dependencies.
- The `test` target installs `requirements-test.lock`, copies the tests and runner,
  and runs the complete pytest suite during image construction.
- The image entry point is `actions-scan`; `/output` is writable by the default
  unprivileged user.

## Acceptance criteria

- More than 100 repositories are paginated correctly.
- Archived repositories are never scanned; accessible private repositories are.
- The four-column CSV contract is exact, including path/name shortening rules.
- Job-level reusable workflows and step-level actions are detected.
- Tags, branches, SHA refs, local references, Docker references, malformed YAML,
  and unsupported values are covered by tests.
- Missing workflow directories are successful zero-result scans.
- API failures preserve successful results and produce exit status 1.
- ETag cache hits make no workflow-file requests.
- The token is absent from Docker arguments, output files, cache files, and error
  messages.
- `docker build --target test -t actions-scan-test .` passes.
- `docker build -t actions-scan .` produces a non-root production image.
