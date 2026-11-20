"""Manage release directories and public symlinks on Helios over SSH."""

import os
from pathlib import Path
import sys
import uuid


def point(link, target):
    if target == "-":
        link.unlink(missing_ok=True)
        return
    temporary = link.with_name(f".{link.name}-{uuid.uuid4().hex}")
    temporary.symlink_to(os.path.relpath(target, link.parent))
    try:
        temporary.replace(link)
    finally:
        temporary.unlink(missing_ok=True)


def linked_release(link, releases):
    if not link.is_symlink():
        return "-"
    target = link.resolve(strict=True)
    if target.parent != releases.resolve():
        raise ValueError(f"Unexpected target for {link}: {target}")
    return target.name


def verify_release(path, revision=None):
    actual = (path / "revision.txt").read_text().strip()
    if len(actual) != 40 or any(char not in "0123456789abcdef" for char in actual):
        raise ValueError(f"Invalid revision in {path}")
    if revision is not None and revision != actual:
        raise ValueError(f"Expected {revision}, found {actual} in {path}")
    if 'content="reactivity-derived-state"' not in (path / "index.html").read_text():
        raise ValueError(f"HTML marker is missing in {path}")
    return actual


def main():
    action, channel, release, *arguments = sys.argv[1:]
    web = Path.home() / "public_html"
    releases = web / ".reactivity-releases" / channel
    public = web / ("reactivity" if channel == "main" else f"reactivity-preview/{channel}")
    previous = releases / "previous"
    candidate = releases / release
    if action == "prepare":
        candidate.mkdir(parents=True)
        public.parent.mkdir(parents=True, exist_ok=True)
        return
    if action == "discard":
        # Only discard a candidate whose upload was interrupted before activation.
        import shutil

        shutil.rmtree(candidate)
        return

    active = linked_release(public, releases)
    saved = linked_release(previous, releases)
    if action == "restore":
        old_active, old_saved = arguments
        if active != release:
            raise ValueError("Public release changed before recovery")
        point(public, "-" if old_active == "-" else releases / old_active)
        point(previous, "-" if old_saved == "-" else releases / old_saved)
        return

    if action == "rollback":
        if saved == "-":
            raise ValueError("There is no previous release")
        candidate = releases / saved
    else:
        if action != "activate":
            raise ValueError(f"Unknown action: {action}")
    revision = verify_release(candidate, arguments[0] if action == "activate" else None)
    original_directory = public.exists() and not public.is_symlink()
    if original_directory:
        if channel != "main" or action != "activate":
            raise ValueError(f"Unexpected directory at {public}")
        verify_release(public)
        active = f"initial-{uuid.uuid4().hex}"
        public.rename(releases / active)
    try:
        point(previous, "-" if active == "-" else releases / active)
        point(public, candidate)
    except OSError:
        if original_directory:
            (releases / active).rename(public)
        point(previous, "-" if saved == "-" else releases / saved)
        raise
    print(active, saved, candidate.name, revision)


if __name__ == "__main__":
    main()
