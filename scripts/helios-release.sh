#!/usr/bin/env bash
set -euo pipefail
umask 022

action=$1 channel=$2 release=$3
shift 3
[[ $channel =~ ^[a-z0-9-]+$ && $release =~ ^[a-z0-9-]+$ ]]
web="$HOME/public_html"
releases="$web/.reactivity-releases/$channel"
public="$web/reactivity-preview/$channel"
if [[ $channel == main ]]; then public="$web/reactivity"; fi
previous="$releases/previous"
candidate="$releases/$release"

point() {
  local link=$1 version=$2 temporary
  if [[ $version == - ]]; then
    rm -f -- "$link"
    return
  fi
  temporary=$(mktemp -d "${link%/*}/.switch-XXXXXXXX") || return 1
  if ln -s "$releases/$version" "$temporary/link" &&
    mv -Tf -- "$temporary/link" "$link"; then
    rmdir -- "$temporary" || true
  else
    rm -rf -- "$temporary"
    return 1
  fi
}

linked_release() {
  local link=$1 target version
  if [[ ! -L $link ]]; then
    echo '-'
    return
  fi
  target=$(readlink -- "$link")
  version=${target##*/}
  if [[ $target != "$releases/$version" || ! -d $target ]]; then
    echo "Unexpected target for $link: $target" >&2
    return 1
  fi
  echo "$version"
}

verify_release() {
  local directory=$1 expected=${2:-} revision
  revision=$(cat "$directory/revision.txt")
  if [[ ! $revision =~ ^[0-9a-f]{40}$ || ( -n $expected && $revision != "$expected" ) ]]; then
    echo "Invalid revision in $directory: $revision" >&2
    return 1
  fi
  if ! grep -Fq 'content="reactivity-derived-state"' "$directory/index.html"; then
    echo "HTML marker is missing in $directory" >&2
    return 1
  fi
  echo "$revision"
}

case $action in
  prepare)
    mkdir -p -- "$releases" "${public%/*}"
    mkdir -- "$candidate"
    exit
    ;;
  discard)
    rm -rf -- "$candidate"
    exit
    ;;
esac

active=$(linked_release "$public")
saved=$(linked_release "$previous")
case $action in
  restore)
    if [[ $active != "$release" ]]; then
      echo 'Public release changed before recovery' >&2
      exit 1
    fi
    point "$public" "$1"
    point "$previous" "$2"
    exit
    ;;
  rollback)
    if [[ $saved == - ]]; then
      echo 'There is no previous release' >&2
      exit 1
    fi
    release=$saved
    candidate="$releases/$release"
    ;;
  activate) ;;
  *) echo "Unknown action: $action" >&2; exit 1 ;;
esac

revision=$(verify_release "$candidate" "${1:-}")
initial_migration=false
if [[ -d $public && ! -L $public ]]; then
  [[ $channel == main && $action == activate ]]
  verify_release "$public" > /dev/null
  active="initial-$release"
  [[ ! -e $releases/$active ]]
  mv -- "$public" "$releases/$active"
  initial_migration=true
fi
if ! point "$previous" "$active" || ! point "$public" "$release"; then
  if $initial_migration; then mv -- "$releases/$active" "$public"; fi
  point "$previous" "$saved"
  exit 1
fi
printf '%s %s %s %s\n' "$active" "$saved" "$release" "$revision"
