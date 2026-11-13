#!/usr/bin/env python3
"""Bump a versioned prompt (feature 009): copy its active file to the next version, then record the fingerprint.

    uv run python scripts/bump_prompt.py judge          # judge.v1.md -> judge.v2.md (front-matter version: 2); edit it
    uv run python scripts/bump_prompt.py judge --lock   # after editing: pin judge@2's fingerprint in the lock

Two steps on purpose: the guard (``verify_lock()``, ``tests/unit/test_prompt_guard.py``) stays red between them, so a
new version cannot ship until its text is the one the lock pins. ``--lock`` refuses to re-record a version that is
already pinned with a different text (that is the silent change the guard exists to catch): bump again instead, or
pass ``--force`` for a version that has not been merged yet. Older files stay in ``src/kestrel/prompts/`` as the
non-active versions an A/B arm can pin. Ids are the registry ids: ``judge``, ``recommender``, ``attacker:<family>``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kestrel import prompt_registry as pr


class BumpError(Exception):
    """A refused bump or lock step; the message says what to do instead."""


def _versions(prompt_id: str, directory: Path) -> dict[str, pr.PromptFile]:
    files = pr.prompt_files(directory)
    versions = files.get(prompt_id)
    if not versions:
        raise BumpError(f"No prompt is registered as {prompt_id!r}; known ids: {', '.join(sorted(files))}.")
    return versions


def bump(prompt_id: str, *, directory: Path | None = None, lock_path: Path | None = None) -> Path:
    """Copy the active (highest) version of ``prompt_id`` to ``v<N+1>`` with its front-matter updated, and return the
    new file's path. Refused while the current version is not yet recorded in the lock, so unrecorded versions
    cannot pile up."""
    directory = directory or pr.PROMPTS_DIR
    versions = _versions(prompt_id, directory)
    current = max(versions, key=int)
    if current not in pr.read_lock(lock_path).get(prompt_id, {}):
        raise BumpError(f"{prompt_id}@{current} is not recorded in the lock yet; finish it with "
                        f"'bump_prompt.py {prompt_id} --lock' before bumping again.")
    new_version = str(int(current) + 1)
    target = pr.prompt_path(prompt_id, new_version, directory)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(pr.format_prompt_file(prompt_id, new_version, versions[current].text))
    return target


def record(prompt_id: str, *, directory: Path | None = None, lock_path: Path | None = None,
           force: bool = False) -> str:
    """Pin the fingerprint of the newest version of ``prompt_id`` in the lock; returns a one-line message. A version
    already recorded with a different text is refused unless ``force`` (immutable history, FR-005)."""
    directory = directory or pr.PROMPTS_DIR
    versions = _versions(prompt_id, directory)
    newest = max(versions, key=int)
    digest = pr.fingerprint(versions[newest].text)
    lock = pr.read_lock(lock_path)
    pinned = lock.setdefault(prompt_id, {})
    if pinned.get(newest) == digest:
        return f"{prompt_id}@{newest} is already recorded ({digest[:12]}…); nothing to do."
    if newest in pinned and not force:
        raise BumpError(f"{prompt_id}@{newest} is already recorded with a different text. A recorded version is "
                        f"immutable: bump again, or pass --force to re-record a version that has not been merged yet.")
    pinned[newest] = digest
    pr.write_lock(lock, lock_path)
    return f"Recorded {prompt_id}@{newest} ({digest[:12]}…) in {lock_path or pr.LOCK_PATH}."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bump a versioned prompt, then record its fingerprint in the lock.")
    parser.add_argument("prompt_id", help="a registry id: judge, recommender, or attacker:<family>")
    parser.add_argument("--lock", action="store_true", help="record the newest version's fingerprint in the lock")
    parser.add_argument("--force", action="store_true",
                        help="with --lock: re-record an already recorded (not yet merged) newest version")
    args = parser.parse_args(argv)
    try:
        if args.lock:
            print(record(args.prompt_id, force=args.force))
            drifted = pr.verify_lock()
            print("Guard: clean." if not drifted else f"Guard still reports: {', '.join(drifted)}")
            return 0 if not drifted else 1
        path = bump(args.prompt_id)
        print(f"Created {path}. Edit it, then run: python scripts/bump_prompt.py {args.prompt_id} --lock")
        return 0
    except BumpError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
