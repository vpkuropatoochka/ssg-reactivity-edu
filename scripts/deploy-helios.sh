#!/usr/bin/env bash
set -euo pipefail

: "${HELIOS_USER:?}" "${HELIOS_SSH_KEY:?}" "${HELIOS_KNOWN_HOSTS:?}" "${HELIOS_URL:?}"
[[ $HELIOS_USER =~ ^s[0-9]+$ ]]

mode=${1:-deploy}
base_url=${HELIOS_URL%/}
channel=main
url=$base_url
if [[ $GITHUB_REF_NAME != main ]]; then
  slug=$(printf '%s' "$GITHUB_REF_NAME" | LC_ALL=C tr -cs 'A-Za-z0-9-' '-' | cut -c1-40)
  slug=${slug,,}
  hash=$(printf '%s' "$GITHUB_REF_NAME" | sha256sum | cut -c1-16)
  channel="${slug}-${hash}"
  url="${base_url}-preview/$channel"
elif [[ $mode == interrupt-preview ]]; then
  echo 'The interruption experiment requires a preview branch' >&2
  exit 1
fi

ssh_dir=$(mktemp -d)
trap 'rm -r "$ssh_dir"' EXIT
install -m 600 /dev/null "$ssh_dir/id"
printf '%s\n' "$HELIOS_SSH_KEY" > "$ssh_dir/id"
printf '%s\n' "$HELIOS_KNOWN_HOSTS" > "$ssh_dir/known_hosts"
transport="ssh -p 2222 -i $ssh_dir/id -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$ssh_dir/known_hosts -o ConnectTimeout=15"
target="$HELIOS_USER@helios.cs.ifmo.ru"
release="$GITHUB_SHA-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
directory="public_html/.reactivity-releases/$channel/$release"

remote() {
  $transport "$target" "umask 022; python3 - $*" < scripts/helios-release.py
}

echo "Helios URL: $url"
if [[ $mode == rollback ]]; then
  state=$(remote rollback "$channel" "$release")
else
  if [[ $mode == interrupt-preview ]]; then
    for address in "$url" "$base_url"; do
      revision=$(curl -fsS --max-time 15 "$address/revision.txt")
      bash scripts/check-delivery.sh "$address" "$revision"
      if [[ $address == "$url" ]]; then preview_revision=$revision; else main_revision=$revision; fi
    done
  fi
  remote prepare "$channel" "$release"
  sync=(rsync -r --exclude='.lektor/' --chmod=D755,F644 -e "$transport")
  if [[ $mode == interrupt-preview ]]; then
    result=0
    timeout 15s "${sync[@]}" --partial --bwlimit=1 --info=progress2 build/ "$target:$directory/" || result=$?
    echo "Interrupted rsync exit code: $result"
    $transport "$target" "find $directory -type f -size +0c -print" > "$ssh_dir/partial-files"
    cat "$ssh_dir/partial-files"
    remote discard "$channel" "$release"
    if [[ $result != 124 || ! -s "$ssh_dir/partial-files" ]]; then
      echo 'Experiment did not confirm that a running transfer was interrupted' >&2
      exit 1
    fi
    bash scripts/check-delivery.sh "$url" "$preview_revision"
    bash scripts/check-delivery.sh "$base_url" "$main_revision"
    echo 'Transfer interrupted as planned and both public revisions were verified' >&2
    exit 1
  fi
  if ! "${sync[@]}" build/ "$target:$directory/"; then
    remote discard "$channel" "$release" || true
    exit 1
  fi
  state=$(remote activate "$channel" "$release" "$GITHUB_SHA")
fi

read -r old_active old_saved active revision <<< "$state"
echo "Active release: $active; previous release: $old_active"
if ! bash scripts/check-delivery.sh "$url" "$revision"; then
  remote restore "$channel" "$active" "$old_active" "$old_saved"
  echo "Restored previous public release: $old_active" >&2
  exit 1
fi
