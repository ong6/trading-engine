#!/usr/bin/env python3
"""Registration code identity: a pinned file never changes without a registration revision.

Every tracked ``*-registration.json`` that carries ``code_identity`` pins a set of files by
sha256 and cites ``code_identity.source_commit``. Three rules hold for each one:

1. the cited commit resolves in this repository, directly or through the history rewrite
   maps in ``docs/history/commit-map-*.txt`` (old -> new, applied in file order);
2. it is the last commit that touched any pinned file, and every pinned file's bytes match
   their recorded sha256 (so an uncommitted edit is caught too);
3. against a base revision (``--base``; ``REGISTRATION_BASE_REF`` in the test), a diff that
   changes a pinned file also changes that registration's ``code_identity``.

``python -m tools.registration_identity [--root DIR] [--base REF]`` prints each problem and
exits 2 when there is one, 0 when there is none. ``tests/test_registration_identity.py`` runs
the same checks in CI and in ``tools/deploy_gate.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMIT_MAPS = "docs/history/commit-map-*.txt"
PATTERN = "*-registration.json"


@dataclass(frozen=True)
class Registration:
    path: str
    source_commit: str
    files: dict[str, str]


def _git(root: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=False)
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip() if done.returncode == 0 else ""


def registrations(root: Path) -> list[Registration]:
    """Every tracked registration that pins code, in path order."""
    found = []
    for relative in sorted(_git(root, "ls-files", "--", PATTERN).split()):
        payload = json.loads((root / relative).read_text())
        identity = payload.get("code_identity") if isinstance(payload, dict) else None
        if identity is None:
            continue
        found.append(Registration(relative, str(identity.get("source_commit", "")),
                                  dict(identity.get("files") or {})))
    return found


def rewritten(root: Path, commit: str) -> str:
    """Follow a cited commit through each recorded history rewrite (old -> new)."""
    for commit_map in sorted(root.glob(COMMIT_MAPS)):
        for line in commit_map.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[0] == commit:
                commit = fields[1]
                break
    return commit


def resolve_commit(root: Path, commit: str) -> str | None:
    """The full ID of the cited commit in this history, or None if it does not resolve."""
    if not commit:
        return None
    return _git(root, "rev-parse", "--verify", "--quiet",
                f"{rewritten(root, commit)}^{{commit}}", check=False) or None


def _changed_since(root: Path, base: str) -> set[str]:
    """Paths changed between the merge base with ``base`` and the working tree."""
    merge_base = _git(root, "merge-base", base, "HEAD")
    committed = _git(root, "diff", "--name-only", f"{merge_base}..HEAD").split("\n")
    working = _git(root, "diff", "--name-only", "HEAD").split("\n")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").split("\n")
    return {path for path in (*committed, *working, *untracked) if path}


def _identity(text: str) -> dict | None:
    payload = json.loads(text) if text else None
    return payload.get("code_identity") if isinstance(payload, dict) else None


def problems(root: Path = REPO_ROOT, *, base: str | None = None) -> list[str]:
    """Every identity violation in ``root``; empty when all registrations hold."""
    root = root.resolve()
    found = []
    for registration in registrations(root):
        name = registration.path
        if not registration.files:
            found.append(f"{name}: code_identity pins no files")
            continue
        resolved = resolve_commit(root, registration.source_commit)
        if resolved is None:
            found.append(f"{name}: source_commit {registration.source_commit or '(missing)'} "
                         "does not resolve, directly or through docs/history/commit-map-*.txt")
        latest = _git(root, "rev-list", "-1", "HEAD", "--", *sorted(registration.files))
        if resolved is not None and resolved != latest:
            touched = _git(root, "diff", "--name-only", resolved, latest, "--",
                           *sorted(registration.files)).split()
            found.append(f"{name}: source_commit {registration.source_commit[:12]} is not the "
                         f"last change to its pinned files ({latest[:12]} changed "
                         f"{', '.join(touched) or 'them'}); issue a registration revision")
        for relative, recorded in sorted(registration.files.items()):
            path = root / relative
            if not path.is_file():
                found.append(f"{name}: pinned file {relative} is missing")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != recorded:
                found.append(f"{name}: pinned file {relative} differs from its registered sha256")
        if base is not None:
            changed = _changed_since(root, base)
            pinned = sorted(changed & set(registration.files))
            merge_base = _git(root, "merge-base", base, "HEAD")
            before = _identity(_git(root, "show", f"{merge_base}:{name}", check=False))
            if pinned and before == _identity((root / name).read_text()):
                found.append(f"{name}: {', '.join(pinned)} changed since {base} without a "
                             "registration revision in the same diff")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--base", help="also check the diff from this revision's merge base")
    args = parser.parse_args(argv)
    found = problems(args.root, base=args.base)
    for problem in found:
        print(f"FAIL  {problem}")
    print(f"{'FAIL' if found else 'PASS'}  registration identity "
          f"({len(registrations(args.root.resolve()))} registrations pin code)")
    return 2 if found else 0


if __name__ == "__main__":
    sys.exit(main())
