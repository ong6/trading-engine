#!/usr/bin/env python3
"""Reject private host details, fixed credential patterns, and private identities.

The checker is deliberately read-only.  It can inspect committed additions, a
worktree, CI's advertised revision pair, or the ref updates supplied to a
pre-push hook.  Findings never include the matched value.

The credential contract is intentionally fixed: PEM/OpenSSH private-key
blocks; AWS AKIA/ASIA, GitHub, GitLab, Slack, Google, Stripe, OpenAI,
Anthropic, npm, and PyPI token prefixes; and entropy-gated 16+ character
literal assignments whose key contains secret, password, passwd, token,
api_key, apikey, or private_key.  Assignment scanning covers Python, shell,
env, JSON, YAML, TOML, INI, and plain text, including source-escaped and
multiline serialized forms.  GitHub server-side secret scanning is the second
layer; this tool does not claim to recognize every possible credential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

# data/_meta.json alone is about 4 MB; every changed file must stay scannable.
MAX_TEXT_BYTES = 16 * 1024 * 1024
ZERO_SHA = "0" * 40
PUBLIC_EMAIL_DOMAINS = frozenset(
    {
        "example.com",
        "example.invalid",
        "fixtures.invalid",
        "noreply.github.com",
        "users.noreply.github.com",
    }
)
_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_REV_RE = re.compile(
    r"[A-Za-z0-9_./@{}:^~+!\-]+(?:\.\.[A-Za-z0-9_./@{}:^~+!\-]+)?\Z"
)
_EMAIL_RE = re.compile(r"^[^\s<>@]+@([^\s<>@]+)$")
_PATH_RULES = (
    (
        "absolute_home_path",
        re.compile(r"(?i)(?<![A-Za-z0-9])/(?:home|users)/[A-Za-z0-9._-]+(?:/|\b)"),
    ),
    (
        "absolute_root_home",
        re.compile(r"(?<![A-Za-z0-9])/" + r"root(?:/|(?=$|[\s\"'`,;:)\]]))"),
    ),
    (
        "absolute_windows_home",
        re.compile(
            r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]+users[\\/]+"
            r"[^\\/:\s\"']+(?=$|[\\/]+|[\s\"'`,;:)\]}])"
        ),
    ),
    ("absolute_data_mount", re.compile(r"(?<![A-Za-z0-9])/data[0-9]{2}(?:/|\b)")),
    (
        "nonportable_host",
        re.compile(
            r"(?i)\b(?:host|hostname)\s*[:=]\s*[a-z0-9][a-z0-9.-]*"
            r"\.(?:corp|internal|localdomain)\b"
        ),
    ),
)
_SECRET_RULES = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"
        ),
        0,
    ),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
        0,
    ),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"), 0),
    ("slack_token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{20,}\b"), 0),
    ("google_api_key", re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"), 0),
    ("stripe_key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"), 0),
    (
        "model_api_key",
        re.compile(r"\b(?:sk-ant-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{20,})\b"),
        0,
    ),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"), 0),
    ("pypi_token", re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b"), 0),
    (
        "credential_assignment",
        re.compile(
            r"(?i)(?<![A-Za-z0-9_-])(?:export\s+)?[\"']?"
            r"[A-Za-z0-9_-]*(?:secret|password|passwd|token|api[_-]?key|apikey|"
            r"private[_-]?key)[A-Za-z0-9_-]*[\"']?\s*[:=]\s*"
            r"(?:\"([^\"\r\n]{16,})\"|'([^'\r\n]{16,})'|"
            r"([A-Za-z0-9_./+=:@!$%^&*?~-]{16,}))"
        ),
        (1, 2, 3),
    ),
)
# The repository's commit rule carries the public Claude co-author trailer, so only
# internal or unapproved tool trailers are refused.
_TOOL_COAUTHOR_RE = re.compile(
    r"(?im)^co-authored-by:\s*(?:tra" + r"e(?:\s+cli)?|codex|chatgpt|openai)\b"
)
_PUBLIC_FIXTURE_WORDS = ("dummy", "example", "fixture", "placeholder", "redacted", "test-only")
_TEXT_LIMIT = object()


class HygieneError(RuntimeError):
    """The requested repository state could not be inspected safely."""


@dataclass(frozen=True, order=True)
class Finding:
    """One redacted policy finding."""

    path: str
    rule: str
    digest: str

    def as_dict(self) -> dict[str, str]:
        return {"digest": self.digest, "path": self.path, "rule": self.rule}


def _digest(rule: str, value: str) -> str:
    material = f"public-hygiene-v1\0{rule}\0{value}".encode("utf-8", "surrogateescape")
    return hashlib.sha256(material).hexdigest()


def _finding(path: str, rule: str, value: str, *, redact_path: bool = False) -> Finding:
    return Finding("<redacted-path>" if redact_path else path, rule, _digest(rule, value))


def _run_git(repo: Path, *args: str, allowed: tuple[int, ...] = (0,)) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HygieneError(f"git invocation failed: {exc}") from exc
    if result.returncode not in allowed:
        reason = os.fsdecode(result.stderr).strip() or f"exit {result.returncode}"
        raise HygieneError(f"git {args[0]} failed: {reason}")
    return result.stdout


def _repository_root(path: Path) -> Path:
    root = os.fsdecode(_run_git(path, "rev-parse", "--show-toplevel")).strip()
    if not root:
        raise HygieneError("not inside a Git worktree")
    return Path(root).resolve()


def _validate_revision(value: str) -> str:
    if value.startswith("-") or not _SAFE_REV_RE.fullmatch(value):
        raise HygieneError("unsafe revision expression")
    return value


def public_identity_error(name: str, email: str) -> str | None:
    """Return the public-identity refusal rule, if any."""
    if not name.strip() or any(character in name for character in "\r\n\0"):
        return "commit_identity_name"
    match = _EMAIL_RE.fullmatch(email.strip())
    if not match or match.group(1).lower() not in PUBLIC_EMAIL_DOMAINS:
        return "commit_identity_email"
    return None


def _public_fixture(path: str, value: str) -> bool:
    parts = PurePosixPath(path).parts
    if "tests" not in parts:
        return False
    lowered = value.casefold()
    return any(
        lowered == word or lowered.startswith(f"{word}-") or lowered.startswith(f"{word}_")
        for word in _PUBLIC_FIXTURE_WORDS
    )


def _call_expression(match: re.Match[str], value: str) -> bool:
    """An unquoted value followed by "(" is code, such as `token = VAR.set(state)`."""
    return match.group(3) is not None and value[match.end() : match.end() + 1] == "("


def _matched_candidate(match: re.Match[str], group: int | tuple[int, ...]) -> str:
    if isinstance(group, int):
        return match.group(group)
    return next(value for index in group if (value := match.group(index)) is not None)


def _high_entropy(value: str) -> bool:
    if len(value) < 16:
        return False
    counts = Counter(value)
    entropy = -sum(
        (count / len(value)) * math.log2(count / len(value)) for count in counts.values()
    )
    classes = sum(
        (
            any(character.islower() for character in value),
            any(character.isupper() for character in value),
            any(character.isdigit() for character in value),
            any(not character.isalnum() for character in value),
        )
    )
    return entropy >= 3.0 and classes >= 3


def _sensitive_path(path: str, denylist: tuple[str, ...]) -> bool:
    if any(pattern.search(path) for _, pattern in _PATH_RULES) or any(
        item.casefold() in path.casefold() for item in denylist
    ):
        return True
    for rule, pattern, group in _SECRET_RULES:
        for match in pattern.finditer(path):
            candidate = _matched_candidate(match, group)
            if rule != "credential_assignment" or (
                _high_entropy(candidate) and not _public_fixture(path, candidate)
            ):
                return True
    return False


def _scan_value(
    path: str,
    value: str,
    *,
    denylist: tuple[str, ...],
    include_secrets: bool = True,
) -> set[Finding]:
    findings: set[Finding] = set()
    redact_path = _sensitive_path(path, denylist)
    for rule, pattern in _PATH_RULES:
        for match in pattern.finditer(value):
            findings.add(_finding(path, rule, match.group(0), redact_path=redact_path))
    folded = value.casefold()
    for denied in denylist:
        if denied.casefold() in folded:
            findings.add(
                _finding(path, "host_private_denylist", denied, redact_path=redact_path)
            )
    if include_secrets:
        secret_inputs = (value, value.replace(r'\"', '"').replace(r"\'", "'"))
        for secret_input in dict.fromkeys(secret_inputs):
            for rule, pattern, group in _SECRET_RULES:
                for match in pattern.finditer(secret_input):
                    candidate = _matched_candidate(match, group)
                    if rule == "credential_assignment" and (
                        not _high_entropy(candidate)
                        or _public_fixture(path, candidate)
                        or _call_expression(match, secret_input)
                    ):
                        continue
                    findings.add(
                        _finding(path, rule, candidate, redact_path=redact_path)
                    )
    return findings


def load_denylist(path: Path | None) -> tuple[str, ...]:
    """Read an optional owner-only literal denylist."""
    if path is None:
        return ()
    try:
        details = path.lstat()
    except OSError as exc:
        raise HygieneError(f"cannot inspect denylist: {exc}") from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise HygieneError("denylist must be a regular non-symlink file")
    if stat.S_IMODE(details.st_mode) != 0o600 or details.st_uid != os.getuid():
        raise HygieneError("denylist must be owned by the current user with mode 0600")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HygieneError(f"cannot read denylist: {exc}") from exc
    values = []
    for raw in content.splitlines():
        value = raw.strip()
        if value and not value.startswith("#"):
            values.append(value)
    if any("\0" in value for value in values):
        raise HygieneError("denylist contains an invalid value")
    return tuple(dict.fromkeys(values))


class RepositoryScanner:
    """Read and scan Git objects without checking out or modifying them."""

    def __init__(self, repo: Path, denylist: tuple[str, ...] = ()) -> None:
        self.repo = _repository_root(repo)
        self.denylist = denylist
        self._trees: dict[str, dict[str, tuple[str, str]]] = {}
        self._blobs: dict[str, tuple[str, ...] | None | object] = {}

    def _tree(self, commit: str) -> dict[str, tuple[str, str]]:
        if commit in self._trees:
            return self._trees[commit]
        raw = _run_git(self.repo, "ls-tree", "-rz", "--full-tree", commit)
        result: dict[str, tuple[str, str]] = {}
        for record in raw.split(b"\0"):
            if not record:
                continue
            try:
                header, raw_path = record.split(b"\t", 1)
                mode, object_type, object_id = os.fsdecode(header).split(" ", 2)
            except ValueError as exc:
                raise HygieneError("unexpected Git tree record") from exc
            if object_type == "blob":
                result[os.fsdecode(raw_path)] = (mode, object_id)
        self._trees[commit] = result
        return result

    def _blob_lines(self, object_id: str) -> tuple[str, ...] | None | object:
        if object_id in self._blobs:
            return self._blobs[object_id]
        size_text = os.fsdecode(_run_git(self.repo, "cat-file", "-s", object_id)).strip()
        try:
            size = int(size_text)
        except ValueError as exc:
            raise HygieneError("invalid Git blob size") from exc
        try:
            process = subprocess.Popen(
                ["git", "cat-file", "blob", object_id],
                cwd=self.repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise HygieneError(f"git cat-file failed: {exc}") from exc
        if process.stdout is None:
            raise HygieneError("git cat-file produced no output stream")
        prefix = process.stdout.read(min(size, MAX_TEXT_BYTES) + 1)
        if b"\0" in prefix[:8192]:
            process.kill()
            process.communicate()
            self._blobs[object_id] = None
            return None
        if size > MAX_TEXT_BYTES:
            process.kill()
            process.communicate()
            self._blobs[object_id] = _TEXT_LIMIT
            return _TEXT_LIMIT
        remainder, stderr = process.communicate()
        if process.returncode != 0:
            reason = os.fsdecode(stderr).strip() or f"exit {process.returncode}"
            raise HygieneError(f"git cat-file failed: {reason}")
        raw = prefix + remainder
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            self._blobs[object_id] = None
            return None
        lines = tuple(text.splitlines())
        self._blobs[object_id] = lines
        return lines

    def _metadata(self, commit: str) -> tuple[str, str, str, str, str]:
        raw = _run_git(self.repo, "cat-file", "commit", commit)
        header, separator, message = raw.partition(b"\n\n")
        if not separator:
            raise HygieneError("commit object lacks a message separator")
        values: dict[str, tuple[str, str]] = {}
        for line in header.splitlines():
            if not (line.startswith(b"author ") or line.startswith(b"committer ")):
                continue
            kind, payload = line.split(b" ", 1)
            match = re.match(rb"(.*) <([^<>]+)> [0-9]+ [+-][0-9]{4}\Z", payload)
            if not match:
                raise HygieneError("commit has malformed identity metadata")
            values[os.fsdecode(kind)] = (os.fsdecode(match.group(1)), os.fsdecode(match.group(2)))
        if "author" not in values or "committer" not in values:
            raise HygieneError("commit lacks author or committer metadata")
        try:
            decoded_message = message.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HygieneError("commit message is not UTF-8") from exc
        return (*values["author"], *values["committer"], decoded_message)

    @staticmethod
    def _added_lines(
        current: tuple[str, ...], parents: Iterable[tuple[str, ...]]
    ) -> tuple[str, ...]:
        maximum: Counter[str] = Counter()
        for lines in parents:
            counts = Counter(lines)
            for line, count in counts.items():
                if count > maximum[line]:
                    maximum[line] = count
        remaining = Counter(current)
        added = remaining - maximum
        selected = []
        for line in current:
            if added[line] > 0:
                selected.append(line)
                added[line] -= 1
        return tuple(selected)

    def scan_commit(self, commit: str) -> set[Finding]:
        findings: set[Finding] = set()
        parent_row = os.fsdecode(
            _run_git(self.repo, "rev-list", "--parents", "-n", "1", commit)
        ).strip().split()
        if not parent_row or parent_row[0] != commit:
            raise HygieneError("could not resolve commit parents")
        parents = parent_row[1:]
        short = commit[:12]
        author_name, author_email, committer_name, committer_email, message = self._metadata(commit)
        for role, name, email in (
            ("author", author_name, author_email),
            ("committer", committer_name, committer_email),
        ):
            issue = public_identity_error(name, email)
            if issue:
                findings.add(_finding(f"commit:{short}", issue, f"{role}:{name}:{email}"))
            findings.update(
                _scan_value(
                    f"commit:{short}",
                    f"{name}\n{email}",
                    denylist=self.denylist,
                    include_secrets=False,
                )
            )
        findings.update(
            _scan_value(f"commit:{short}", message, denylist=self.denylist)
        )
        if (match := _TOOL_COAUTHOR_RE.search(message)) is not None:
            findings.add(_finding(f"commit:{short}", "tool_coauthor", match.group(0)))

        current_tree = self._tree(commit)
        parent_trees = [self._tree(parent) for parent in parents]
        changed = {
            path
            for path, entry in current_tree.items()
            if not parent_trees or any(tree.get(path) != entry for tree in parent_trees)
        }
        for path in sorted(changed):
            findings.update(_scan_value(path, path, denylist=self.denylist))
            mode, object_id = current_tree[path]
            current = self._blob_lines(object_id)
            if current is _TEXT_LIMIT:
                findings.add(_finding(path, "text_size_limit", object_id))
                continue
            if current is None:
                continue
            prior_lines = []
            limited = False
            for tree in parent_trees:
                prior = tree.get(path)
                if prior is None:
                    prior_lines.append(())
                    continue
                lines = self._blob_lines(prior[1])
                if lines is _TEXT_LIMIT:
                    findings.add(_finding(path, "text_size_limit", prior[1]))
                    limited = True
                    break
                prior_lines.append(lines or ())
            if limited:
                continue
            added = "\n".join(self._added_lines(current, prior_lines))
            findings.update(_scan_value(path, added, denylist=self.denylist))
        return findings

    def scan_commits(self, commits: Iterable[str]) -> set[Finding]:
        findings: set[Finding] = set()
        seen = set()
        for raw in commits:
            commit = raw.strip()
            if not commit or commit in seen:
                continue
            if not _SHA_RE.fullmatch(commit):
                raise HygieneError("Git returned an invalid commit identity")
            seen.add(commit)
            findings.update(self.scan_commit(commit))
        return findings

    def commits_for_range(self, revision_range: str) -> list[str]:
        expression = _validate_revision(revision_range)
        raw = _run_git(self.repo, "rev-list", "--reverse", "--topo-order", expression)
        return os.fsdecode(raw).splitlines()

    def scan_range(self, revision_range: str) -> set[Finding]:
        return self.scan_commits(self.commits_for_range(revision_range))

    def scan_worktree(self) -> set[Finding]:
        findings: set[Finding] = set()
        raw = _run_git(
            self.repo,
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        )
        for path in sorted(os.fsdecode(item) for item in raw.split(b"\0") if item):
            findings.update(_scan_value(path, path, denylist=self.denylist))
            absolute = self.repo / path
            try:
                details = absolute.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise HygieneError(f"cannot inspect worktree path: {exc}") from exc
            if stat.S_ISLNK(details.st_mode):
                try:
                    target = os.readlink(absolute)
                except OSError as exc:
                    raise HygieneError(f"cannot read worktree symlink: {exc}") from exc
                findings.update(_scan_value(path, target, denylist=self.denylist))
                continue
            if not stat.S_ISREG(details.st_mode):
                continue
            if details.st_size > MAX_TEXT_BYTES:
                with absolute.open("rb") as handle:
                    prefix = handle.read(8192)
                if b"\0" not in prefix:
                    findings.add(_finding(path, "text_size_limit", path))
                continue
            try:
                descriptor = os.open(
                    absolute,
                    os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                )
                with os.fdopen(descriptor, "rb") as handle:
                    raw_content = handle.read(MAX_TEXT_BYTES + 1)
            except OSError as exc:
                raise HygieneError(f"cannot read worktree path: {exc}") from exc
            if b"\0" in raw_content[:8192]:
                continue
            try:
                content = raw_content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            findings.update(_scan_value(path, content, denylist=self.denylist))
        return findings


def _new_branch_commits(scanner: RepositoryScanner, local_sha: str, remote: str) -> list[str]:
    if remote.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._/-]+", remote):
        raise HygieneError("unsafe remote name")
    raw = _run_git(
        scanner.repo,
        "rev-list",
        "--reverse",
        "--topo-order",
        local_sha,
        "--not",
        f"--remotes={remote}",
    )
    return os.fsdecode(raw).splitlines()


def _pre_push_commits(
    scanner: RepositoryScanner, stream: Iterable[str], remote: str
) -> list[str]:
    commits: list[str] = []
    for line in stream:
        fields = line.split()
        if len(fields) != 4:
            raise HygieneError("malformed pre-push ref update")
        _local_ref, local_sha, _remote_ref, remote_sha = fields
        if not _SHA_RE.fullmatch(local_sha) or not _SHA_RE.fullmatch(remote_sha):
            raise HygieneError("pre-push update contains an invalid object identity")
        if local_sha == ZERO_SHA:
            continue
        if remote_sha == ZERO_SHA:
            commits.extend(_new_branch_commits(scanner, local_sha, remote))
        else:
            commits.extend(scanner.commits_for_range(f"{remote_sha}..{local_sha}"))
    return commits


def _ci_commits(scanner: RepositoryScanner) -> list[str]:
    head = os.environ.get("PUBLIC_HYGIENE_HEAD_SHA", "")
    base = os.environ.get("PUBLIC_HYGIENE_BASE_SHA", "")
    if not _SHA_RE.fullmatch(head):
        raise HygieneError("CI head identity is missing or invalid")
    if base == ZERO_SHA:
        return scanner.commits_for_range(f"{head}^!")
    if not _SHA_RE.fullmatch(base):
        raise HygieneError("CI base identity is missing or invalid")
    return scanner.commits_for_range(f"{base}..{head}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--range", dest="ranges", action="append", default=[])
    parser.add_argument("--worktree", action="store_true")
    parser.add_argument("--pre-push", action="store_true")
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument("--ci", action="store_true")
    parser.add_argument("--denylist", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    modes = bool(args.ranges) + args.worktree + args.pre_push + args.ci
    if modes == 0:
        print("public hygiene: no scan mode selected", file=sys.stderr)
        return 2
    if args.pre_push and modes != 1:
        print("public hygiene: --pre-push cannot be combined", file=sys.stderr)
        return 2
    try:
        denylist = load_denylist(args.denylist)
        scanner = RepositoryScanner(args.repo_root, denylist)
        findings: set[Finding] = set()
        for revision_range in args.ranges:
            findings.update(scanner.scan_range(revision_range))
        if args.worktree:
            findings.update(scanner.scan_worktree())
        if args.pre_push:
            commits = _pre_push_commits(scanner, sys.stdin, args.remote_name)
            findings.update(scanner.scan_commits(commits))
        if args.ci:
            findings.update(scanner.scan_commits(_ci_commits(scanner)))
    except HygieneError as exc:
        print(f"public hygiene: ERROR: {exc}", file=sys.stderr)
        return 2
    for finding in sorted(findings):
        print(json.dumps(finding.as_dict(), sort_keys=True, separators=(",", ":")))
    if findings:
        print(f"public hygiene: FAIL ({len(findings)} findings)", file=sys.stderr)
        return 1
    print("public hygiene: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
