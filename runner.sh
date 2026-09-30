#!/usr/bin/env bash

set -euo pipefail

usage() {
  echo "Usage: $0 ORGANIZATION" >&2
  echo "Set GITHUB_ORG_TOKEN to the fine-grained GitHub PAT before running." >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 64
fi

organization=$1
github_token=${GITHUB_ORG_TOKEN:-}

if [[ ! $organization =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?$ ]]; then
  echo "error: ORGANIZATION must be a valid GitHub organization login" >&2
  exit 64
fi

if [[ -z $github_token ]]; then
  echo "error: GITHUB_ORG_TOKEN must be set" >&2
  exit 64
fi

script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
output_directory=${OUTPUT_DIR:-"$script_directory/output"}
image=${ACTIONS_SCAN_IMAGE:-actions-scan}

mkdir -p -- "$output_directory"

export GITHUB_TOKEN=$github_token
trap 'unset GITHUB_TOKEN github_token' EXIT

docker run --rm \
  --env GITHUB_TOKEN \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$output_directory,dst=/output" \
  "$image" \
  --org "$organization"
