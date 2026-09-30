# actions-scan

`actions-scan` inventories direct `uses:` references in GitHub Actions workflows
across an organization. It scans the default branch of every repository visible to
the token, skips archived repositories, and writes CSV and JSON reports suitable
for manual version review.

The scanner is deterministic and does not use AI services. It does not modify
repositories, expand composite actions or reusable workflows, scan non-default
branches, or decide whether a reference is out of date.

## Authentication

Create a **fine-grained personal access token** for the target organization and
grant it access to every repository that should be inventoried. The only repository
permission needed is **Contents: read**; Metadata read access is included with a
fine-grained token.

The organization may need to approve the token. If the organization uses SAML SSO,
ensure the token is authorized as required. A token can only reveal repositories it
is permitted to access, so use `--expected-active-repos` when you know the expected
non-archived count.

The wrapper reads the token from `GITHUB_ORG_TOKEN` and forwards it into the
container as `GITHUB_TOKEN`, which is the only token variable the scanner reads. A
token is never accepted as a command-line argument, written to a report, or logged.

## Build and run

```bash
docker build -t actions-scan .

export GITHUB_ORG_TOKEN="github_pat_..."
./runner.sh ORGANIZATION
```

`runner.sh` creates `output/` beside the script and handles the Docker options. Its
only argument is the organization login. You can override the defaults with
`OUTPUT_DIR=/path/to/reports` or
`ACTIONS_SCAN_IMAGE=registry.example/actions-scan:tag`.

To invoke Docker directly instead of using the wrapper:

```bash
export GITHUB_TOKEN="github_pat_..."
mkdir -p output

docker run --rm \
  --env GITHUB_TOKEN \
  --user "$(id -u):$(id -g)" \
  --mount type=bind,src="$PWD/output",dst=/output \
  actions-scan \
  --org ORGANIZATION
```

Passing `--env GITHUB_TOKEN` forwards the existing variable without placing its
value in the command or shell history. The `--user` option makes bind-mounted files
owned by the current Unix user. The image also has an unprivileged default user for
environments where the user override is unnecessary.

Available options:

```text
actions-scan --org ORGANIZATION
             [--output-dir /output]
             [--concurrency 5]
             [--expected-active-repos NUMBER]
```

Concurrency must be between 1 and 20. The default of 5 is intentionally
conservative with GitHub secondary rate limits.

## Reports

The mounted output directory receives:

- `occurrences.csv` — the primary report, with exactly four columns: repository
  name, workflow filename, action name, and the exact referenced action version.
  Organization prefixes and the standard `.github/workflows/` path are omitted.
- `inventory.json` — complete machine-readable results, scan metadata, totals, and
  detailed diagnostics.
- `errors.csv` — repository, API, and YAML failures. It always contains a header,
  even when the scan succeeds.
- `.actions-inventory-cache.json` — ETags and successful prior results used to avoid
  downloading unchanged workflows. It contains no credentials.

Output files are replaced atomically. When only part of a scan succeeds, the usable
results and errors are still written.

## Exit status and troubleshooting

- `0`: complete scan with no reported failures.
- `1`: partial scan, parse failure, invalid cache, or repository-count mismatch;
  inspect `errors.csv`.
- `2`: invocation error, missing `GITHUB_TOKEN`, or unusable output directory.

For `401` or `403` errors, check token expiration, organization approval, SSO
authorization, repository selection, and **Contents: read** permission. Rate-limit
responses are retried with bounded backoff; persistent failures are recorded rather
than silently omitted. Invalid workflow YAML is reported with its repository and
path.

If Docker cannot write the bind mount, create the directory first and use the
documented `--user "$(id -u):$(id -g)"` option. On platforms where that syntax is
not available, grant the container's default UID `10001` write access to the output
directory.

## Tests

Run the tests in the dedicated Docker build stage:

```bash
docker build --target test -t actions-scan-test .
```

The production image is the final `runtime` stage and does not contain the tests or
test-only dependencies.
