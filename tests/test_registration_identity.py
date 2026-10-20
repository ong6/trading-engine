"""Registration code identity (tools/registration_identity.py) in this checkout and in toys.

The checkout test is the CI and deploy-gate check: every ``*-registration.json`` with a
``code_identity`` cites a commit that resolves (directly or through
``docs/history/commit-map-*.txt``), is the last change to its pinned files, and pins the bytes
on disk; a diff from ``REGISTRATION_BASE_REF`` (default ``origin/main`` when it exists) that
changes a pinned file also carries a registration revision. The toy repositories prove each
rule refuses what it should.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools import registration_identity as identity

ROOT = Path(__file__).resolve().parents[1]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _base_ref() -> str | None:
    ref = os.environ.get("REGISTRATION_BASE_REF", "origin/main")
    if not ref:
        return None
    done = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                          cwd=ROOT, capture_output=True, text=True)
    return ref if done.returncode == 0 else None


def test_registrations_with_code_identity_are_found():
    found = {item.path for item in identity.registrations(ROOT)}
    assert "server/p15-registration.json" in found


def test_registration_identity_holds_in_this_checkout():
    assert identity.problems(ROOT, base=_base_ref()) == []


# --------------------------------------------------------------------------- toy repos
def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _register(repo: Path, source_commit: str, revision: int) -> None:
    pinned = repo / "engine" / "rule.py"
    payload = {"registration_revision": revision, "code_identity": {
        "source_commit": source_commit,
        "files": {"engine/rule.py": hashlib.sha256(pinned.read_bytes()).hexdigest()}}}
    (repo / "server" / "toy-registration.json").write_text(json.dumps(payload, indent=1))


@pytest.fixture
def toy(tmp_path: Path) -> Path:
    """A repo whose registration (revision 1) pins engine/rule.py at its last change."""
    repo = tmp_path / "repo"
    (repo / "engine").mkdir(parents=True)
    (repo / "server").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "engine" / "rule.py").write_text("THRESHOLD = 1\n")
    (repo / "notes.md").write_text("notes\n")
    source = _commit(repo, "rule")
    _register(repo, source, 1)
    _commit(repo, "register revision 1")
    _git(repo, "branch", "base")
    return repo


def test_toy_registration_holds(toy: Path):
    assert identity.problems(toy, base="base") == []


def test_unpinned_change_needs_no_revision(toy: Path):
    (toy / "notes.md").write_text("more notes\n")
    _commit(toy, "notes")
    assert identity.problems(toy, base="base") == []


def test_pinned_change_without_revision_is_refused(toy: Path):
    (toy / "engine" / "rule.py").write_text("THRESHOLD = 2\n")
    _commit(toy, "tune the rule")
    found = identity.problems(toy, base="base")
    assert any("is not the last change to its pinned files" in item for item in found)
    assert any("differs from its registered sha256" in item for item in found)
    assert any("without a registration revision in the same diff" in item for item in found)


def test_uncommitted_pinned_edit_is_refused(toy: Path):
    (toy / "engine" / "rule.py").write_text("THRESHOLD = 3\n")
    found = identity.problems(toy)
    assert found == ["server/toy-registration.json: pinned file engine/rule.py differs "
                     "from its registered sha256"]


def test_pinned_change_with_revision_in_the_same_diff_holds(toy: Path):
    (toy / "engine" / "rule.py").write_text("THRESHOLD = 2\n")
    source = _commit(toy, "tune the rule")
    _register(toy, source, 2)
    _commit(toy, "register revision 2")
    assert identity.problems(toy, base="base") == []


def test_source_commit_resolves_through_a_commit_map(toy: Path):
    source = _git(toy, "rev-list", "-1", "HEAD", "--", "engine/rule.py")
    old = "0" * 39 + "1"
    (toy / "docs" / "history").mkdir(parents=True)
    (toy / "docs" / "history" / "commit-map-2026-10-20.txt").write_text(
        f"# old new\n{old} {source}\n")
    _register(toy, old, 1)
    _commit(toy, "cite the pre-rewrite id")
    assert identity.problems(toy) == []


def test_unresolvable_source_commit_is_refused(toy: Path):
    _register(toy, "f" * 40, 1)
    _commit(toy, "cite a commit from nowhere")
    found = identity.problems(toy)
    assert len(found) == 1 and "does not resolve" in found[0]
