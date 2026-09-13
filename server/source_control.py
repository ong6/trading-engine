"""Read-only local Git tracking status for unattended generated-data sync."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from engine.lib.settings import REPO_ROOT

from .host_command import bounded_printable_line, command_budget, run_bounded
from .read_model_utils import PUBLIC_SAFE_INTEGER_MAX

PUBLIC_INVALID_REASONS = frozenset(
    {
        "branch-unavailable",
        "git-unavailable",
        "projection-error",
        "tracking-count-invalid",
        "tracking-identity-invalid",
    }
)
PUBLIC_LOCAL_ONLY_REASONS = frozenset({"no-upstream", "tracking-ref-missing"})
PUBLIC_STATUSES = frozenset(
    {"behind", "current", "diverged", "invalid", "local-only", "unpushed"}
)
PUBLIC_IDENTITY_MAX_CHARS = 4_096
PUBLIC_TRACKING_COUNT_MAX = PUBLIC_SAFE_INTEGER_MAX
GIT_OBJECT_ID_MAX_CHARS = 64
_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_GIT_TRACKING_COUNTS = re.compile(r"([0-9]+)\t([0-9]+)\n")


@dataclass(frozen=True)
class _RepositoryObservation:
    branch: str
    remote: str | None = None
    merge_ref: str | None = None
    upstream_ref: str | None = None
    upstream: str | None = None
    upstream_object: str | None = None
    head_object: str | None = None
    local_only_reason: str | None = None


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    return run_bounded(["git", *args], cwd=repo_root)


def invalid_status(reason: str = "projection-error") -> dict:
    """Return the complete fail-closed shape without repository details."""
    if reason not in PUBLIC_INVALID_REASONS:
        raise ValueError(f"unknown source-control invalid reason: {reason}")
    return {
        "status": "invalid",
        "reason": reason,
        "branch": None,
        "remote": None,
        "upstream": None,
        "ahead": None,
        "behind": None,
        "network_checked": False,
    }


def _local_only_status(branch: str, reason: str, *, remote: str | None = None) -> dict:
    if reason not in PUBLIC_LOCAL_ONLY_REASONS:
        raise ValueError(f"unknown source-control local-only reason: {reason}")
    return {
        "status": "local-only",
        "reason": reason,
        "branch": branch,
        "remote": remote,
        "upstream": None,
        "ahead": None,
        "behind": None,
        "network_checked": False,
    }


def _current_branch(repo_root: Path) -> tuple[str | None, dict | None]:
    result = _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if result is None:
        return None, invalid_status("git-unavailable")
    if result.stderr or result.returncode not in {0, 1}:
        return None, invalid_status("git-unavailable")
    if result.returncode == 1:
        if result.stdout:
            return None, invalid_status("git-unavailable")
        return None, invalid_status("branch-unavailable")
    branch = bounded_printable_line(result.stdout, max_chars=PUBLIC_IDENTITY_MAX_CHARS)
    if branch is None:
        return None, invalid_status("branch-unavailable")
    return branch, None


def _tracking_config(
    branch: str,
    remote_result: subprocess.CompletedProcess[str] | None,
    merge_result: subprocess.CompletedProcess[str] | None,
) -> tuple[tuple[str, str] | None, dict | None]:
    """Classify the two branch-tracking config reads without hiding failures."""
    if remote_result is None or merge_result is None:
        return None, invalid_status("git-unavailable")
    results = (remote_result, merge_result)
    if any(result.returncode not in {0, 1} or result.stderr for result in results):
        return None, invalid_status("git-unavailable")
    if any(result.returncode == 1 and result.stdout for result in results):
        return None, invalid_status("git-unavailable")
    missing = tuple(result.returncode == 1 for result in results)
    if all(missing):
        return None, _local_only_status(branch, "no-upstream")
    if any(missing):
        return None, invalid_status("tracking-identity-invalid")
    remote = bounded_printable_line(remote_result.stdout, max_chars=PUBLIC_IDENTITY_MAX_CHARS)
    merge_ref = bounded_printable_line(
        merge_result.stdout, max_chars=PUBLIC_IDENTITY_MAX_CHARS
    )
    if remote is None or merge_ref is None or not merge_ref.startswith("refs/heads/"):
        return None, invalid_status("tracking-identity-invalid")
    return (remote, merge_ref), None


def _upstream_identity(value: str) -> tuple[str, str] | None:
    """Decode the full and short ref names emitted by one for-each-ref row."""
    if not isinstance(value, str) or not value.endswith("\n") or value.count("\n") != 1:
        return None
    fields = value[:-1].split("\0")
    if len(fields) != 2:
        return None
    full, short = (
        bounded_printable_line(field, max_chars=PUBLIC_IDENTITY_MAX_CHARS)
        for field in fields
    )
    if full is None or short is None or not full.startswith("refs/"):
        return None
    return full, short


def _configured_tracking(
    repo_root: Path, branch: str
) -> tuple[tuple[str, str, str, str, str | None] | None, dict | None]:
    configured, error = _tracking_config(
        branch,
        _git(repo_root, "config", "--get", f"branch.{branch}.remote"),
        _git(repo_root, "config", "--get", f"branch.{branch}.merge"),
    )
    if error is not None:
        return None, error
    remote, merge_ref = configured
    ref_check = _git(repo_root, "check-ref-format", merge_ref)
    if ref_check is None:
        return None, invalid_status("git-unavailable")
    if ref_check.returncode != 0 or ref_check.stdout or ref_check.stderr:
        return None, invalid_status("tracking-identity-invalid")

    upstream_result = _git(
        repo_root,
        "for-each-ref",
        "--format=%(upstream)%00%(upstream:short)",
        f"refs/heads/{branch}",
    )
    if upstream_result is None:
        return None, invalid_status("git-unavailable")
    if upstream_result.returncode != 0 or upstream_result.stderr:
        return None, invalid_status("git-unavailable")
    upstream_identity = _upstream_identity(upstream_result.stdout)
    if upstream_identity is None:
        return None, invalid_status("tracking-identity-invalid")
    upstream_ref, upstream = upstream_identity

    object_result = _git(
        repo_root, "rev-parse", "--verify", "--quiet", f"{upstream_ref}^{{commit}}"
    )
    if object_result is None:
        return None, invalid_status("git-unavailable")
    if object_result.returncode == 1 and not object_result.stdout and not object_result.stderr:
        return (remote, merge_ref, upstream_ref, upstream, None), None
    object_id = bounded_printable_line(object_result.stdout, max_chars=GIT_OBJECT_ID_MAX_CHARS)
    if (
        object_result.returncode != 0
        or object_result.stderr
        or object_id is None
        or _GIT_OBJECT_ID.fullmatch(object_id) is None
    ):
        return None, invalid_status("git-unavailable")
    return (remote, merge_ref, upstream_ref, upstream, object_id), None


def _head_object(repo_root: Path) -> tuple[str | None, dict | None]:
    result = _git(repo_root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if result is None:
        return None, invalid_status("git-unavailable")
    object_id = bounded_printable_line(result.stdout, max_chars=GIT_OBJECT_ID_MAX_CHARS)
    if (
        result.returncode != 0
        or result.stderr
        or object_id is None
        or _GIT_OBJECT_ID.fullmatch(object_id) is None
    ):
        return None, invalid_status("git-unavailable")
    return object_id, None


def _observation(
    repo_root: Path,
) -> tuple[_RepositoryObservation | None, dict | None]:
    branch, error = _current_branch(repo_root)
    if error is not None:
        return None, error
    tracking, error = _configured_tracking(repo_root, branch)
    if error is not None:
        if error["status"] == "local-only" and error["reason"] == "no-upstream":
            return _RepositoryObservation(
                branch=branch, local_only_reason="no-upstream"
            ), None
        return None, error
    remote, merge_ref, upstream_ref, upstream, upstream_object = tracking
    if upstream_object is None:
        return _RepositoryObservation(
            branch=branch,
            remote=remote,
            merge_ref=merge_ref,
            upstream_ref=upstream_ref,
            upstream=upstream,
            local_only_reason="tracking-ref-missing",
        ), None
    head_object, error = _head_object(repo_root)
    if error is not None:
        return None, error
    return _RepositoryObservation(
        branch=branch,
        remote=remote,
        merge_ref=merge_ref,
        upstream_ref=upstream_ref,
        upstream=upstream,
        upstream_object=upstream_object,
        head_object=head_object,
    ), None


def _tracking_counts(
    repo_root: Path, head_object: str, upstream_object: str
) -> tuple[tuple[int, int] | None, dict | None]:
    result = _git(
        repo_root,
        "rev-list",
        "--left-right",
        "--count",
        f"{head_object}...{upstream_object}",
    )
    if result is None:
        return None, invalid_status("git-unavailable")
    if result.returncode != 0 or result.stderr:
        return None, invalid_status("git-unavailable")
    match = _GIT_TRACKING_COUNTS.fullmatch(result.stdout)
    if match is None:
        return None, invalid_status("tracking-count-invalid")
    ahead, behind = (int(value) for value in match.groups())
    if (
        ahead < 0
        or behind < 0
        or ahead > PUBLIC_TRACKING_COUNT_MAX
        or behind > PUBLIC_TRACKING_COUNT_MAX
    ):
        return None, invalid_status("tracking-count-invalid")
    return (ahead, behind), None


def _relation(ahead: int, behind: int) -> str:
    if ahead and behind:
        return "diverged"
    if ahead:
        return "unpushed"
    if behind:
        return "behind"
    return "current"


def _status(repo_root: Path) -> dict:
    observation, error = _observation(repo_root)
    if error is not None:
        return error
    if observation.local_only_reason is None:
        counts, error = _tracking_counts(
            repo_root, observation.head_object, observation.upstream_object
        )
        if error is not None:
            return error
    current, error = _observation(repo_root)
    if error is not None or current != observation:
        return invalid_status("git-unavailable")
    if observation.local_only_reason is not None:
        return _local_only_status(
            observation.branch,
            observation.local_only_reason,
            remote=observation.remote,
        )
    ahead, behind = counts
    return {
        "status": _relation(ahead, behind),
        "reason": None,
        "branch": observation.branch,
        "remote": observation.remote,
        "upstream": observation.upstream,
        "ahead": ahead,
        "behind": behind,
        "network_checked": False,
    }


def status(*, repo_root: Path = REPO_ROOT) -> dict:
    """Describe one stable local tracking observation within one command budget."""
    with command_budget():
        return _status(repo_root)
