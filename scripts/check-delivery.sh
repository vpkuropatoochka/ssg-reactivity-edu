#!/usr/bin/env bash
set -euo pipefail

url=${1%/}
expected_revision=$2
response=$(mktemp)
trap 'rm -f "$response"' EXIT

check_http() {
  local path=$1 status
  status=$(curl --silent --show-error --connect-timeout 5 --max-time 15 \
    --output "$response" --write-out '%{http_code}' "$url/$path")
  printf '%s/%s HTTP %s\n' "$url" "$path" "$status"
  [[ $status == 200 ]]
}

check_http ""
if ! grep -Fq 'content="reactivity-derived-state"' "$response"; then
  echo 'HTML marker is missing' >&2
  exit 1
fi
check_http revision.txt
revision=$(cat "$response")
printf 'Revision: %s (expected %s)\n' "$revision" "$expected_revision"
[[ $revision == "$expected_revision" ]]
