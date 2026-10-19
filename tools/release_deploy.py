#!/usr/bin/env python3
"""Run one dry-by-default, resumable engine release transaction.

The command deliberately keeps product migrations behind a small adapter registry.  Host
mutation requires ``--execute``; without it every subcommand reports the gates and steps it
would perform.  Completed steps have input-bound receipts, so a retry either skips the exact
same operation or refuses changed inputs.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from engine.lib.settings import REPO_ROOT
from tools import (
    backup_database,
    install_automation,
    publish_snapshot,
    release_manifest,
    worktree_audit,
)

STATE_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1
FULL_SHA = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
UNIT_NAME = re.compile(r"[A-Za-z0-9_.@:-]+\.(?:service|timer)")
ACTIVE_STATES = frozenset({"active", "activating", "reloading"})
VALID_PHASES = frozenset(
    {
        "preparing",
        "prepared",
        "applying",
        "awaiting-migration-approval",
        "awaiting-optional-units",
        "applied",
        "verifying",
        "verified",
        "rolling-back",
        "rolled-back",
        "resuming",
        "resumed",
        "aborting",
        "aborted",
    }
)
AUTOPUSH_UNITS = frozenset({"te-autopush.service", "te-autopush.timer"})
SPECIAL_UNITS = frozenset(
    {
        *AUTOPUSH_UNITS,
        "store-sync.service",
        "store-sync.timer",
        "trading-data-backup.service",
        "trading-data-backup.timer",
    }
)
OPTIONAL_UNITS = frozenset({"massive-options-daily.service", "massive-options-daily.timer"})
R15_RUNTIME_VERSIONS = {"e1": 8, "forward": 12, "xs": 23}
RUNTIME_LINKS = {
    ".venv": "python_environment",
    "ui/node_modules": "node_modules",
    "ui/.next": "ui_build",
}
PRODUCER_PATTERN = re.compile(
    r"run_(?:daily|weekly_walkforward|weekly_liquid|weekend_sweeps|weekly_verify)\.sh"
    r"|tools\.verify_friday_postflight|engine\.(?:collect|verify_prices|queue_runner|sync)"
    r"|store-sync|trading-alpha/|te-autopush|tools\.free_(?:massive_options|sources|massive_minute)"
    r"|engine\.free_massive_minute"
)


class DeployError(RuntimeError):
    """The transaction cannot safely continue."""


class ApprovalRequired(DeployError):
    """A migration dry-run needs explicit operator acceptance."""

    def __init__(self, digest: str, migration: str, plan: dict[str, Any]):
        super().__init__(f"migration {migration} requires --approve-plan {digest}")
        self.digest = digest
        self.migration = migration
        self.plan = plan


class OptionalUnitsPaused(DeployError):
    """Only declared optional units failed activation and need operator acceptance."""

    def __init__(self, digest: str, units: list[str]):
        super().__init__(f"optional unit activation requires --approve-optional {digest}")
        self.digest = digest
        self.units = units


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _regular_json(path: Path) -> dict[str, Any]:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) & 0o077
        ):
            raise DeployError(f"JSON input is not a regular file: {path.name}")
        payload = json.loads(path.read_text())
        after = path.lstat()
    except (OSError, ValueError) as exc:
        raise DeployError(f"cannot read JSON input {path.name}: {exc}") from exc

    def identity(value: os.stat_result) -> tuple[int, int, int, int]:
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    if identity(before) != identity(after) or not isinstance(payload, dict):
        raise DeployError(f"JSON input changed or has the wrong type: {path.name}")
    return payload


@dataclass
class ReleaseState:
    schema_version: int
    transaction_id: str
    created_at: str
    updated_at: str
    phase: str
    repo_root: str
    database: str
    approved_sha: str
    original_sha: str
    adapter_set: str
    d0: str | None
    source_branch: str = "main"
    source_upstream: str = "origin/main"
    prepared: dict[str, Any] = field(default_factory=dict)
    inventory: dict[str, Any] = field(default_factory=dict)
    backup: dict[str, Any] = field(default_factory=dict)
    prior_runtimes: dict[str, Any] = field(default_factory=dict)
    automation: dict[str, Any] = field(default_factory=dict)
    migration_approval: dict[str, Any] | None = None
    optional_unit_pause: dict[str, Any] | None = None
    last_failure: dict[str, Any] | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> ReleaseState:
        expected = {item.name for item in cls.__dataclass_fields__.values()}
        if set(payload) != expected:
            raise DeployError("release state has unknown or missing fields")
        try:
            state = cls(**payload)
        except TypeError as exc:
            raise DeployError(f"invalid release state: {exc}") from exc
        scalar_types = {
            "schema_version": int,
            "transaction_id": str,
            "created_at": str,
            "updated_at": str,
            "phase": str,
            "repo_root": str,
            "database": str,
            "approved_sha": str,
            "original_sha": str,
            "source_branch": str,
            "source_upstream": str,
            "adapter_set": str,
        }
        if any(type(getattr(state, key)) is not kind for key, kind in scalar_types.items()):
            raise DeployError("release state scalar has the wrong type")
        if state.schema_version != STATE_SCHEMA_VERSION or state.phase not in VALID_PHASES:
            raise DeployError("unsupported release state schema or phase")
        if not FULL_SHA.fullmatch(state.approved_sha) or not FULL_SHA.fullmatch(state.original_sha):
            raise DeployError("release state contains an invalid Git identity")
        if state.d0 is not None and not isinstance(state.d0, str):
            raise DeployError("release state d0 has the wrong type")
        if state.adapter_set not in ADAPTERS:
            raise DeployError("release state names an unknown adapter set")
        if state.source_branch != "main" or state.source_upstream != "origin/main":
            raise DeployError("release state has an invalid branch or upstream")
        for value in (
            state.prepared,
            state.inventory,
            state.backup,
            state.prior_runtimes,
            state.automation,
        ):
            if not isinstance(value, dict):
                raise DeployError("release state object has the wrong type")
        if state.migration_approval is not None and not isinstance(state.migration_approval, dict):
            raise DeployError("migration approval has the wrong type")
        if state.optional_unit_pause is not None and not isinstance(
            state.optional_unit_pause, dict
        ):
            raise DeployError("optional unit pause has the wrong type")
        return state


class StateStore:
    def __init__(self, directory: Path):
        self.directory = directory.absolute()
        self.state_path = self.directory / "state.json"

    def _validate_directory(self) -> None:
        try:
            value = self.directory.lstat()
        except OSError as exc:
            raise DeployError(f"state directory is unavailable: {exc}") from exc
        if (
            not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.getuid()
            or stat.S_IMODE(value.st_mode) != 0o700
        ):
            raise DeployError("state directory must be an owner-owned mode-0700 directory")

    def create(self, state: ReleaseState) -> None:
        if os.path.lexists(self.directory):
            raise DeployError("state directory already exists; refusing to overwrite")
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(self.directory, 0o700)
        self.save(state)

    def load(self) -> ReleaseState:
        self._validate_directory()
        state = ReleaseState.from_json(_regular_json(self.state_path))
        if (
            Path(state.repo_root).resolve() == self.directory.resolve()
            or Path(state.repo_root).resolve() in self.directory.resolve().parents
        ):
            raise DeployError("state directory cannot contain the release checkout")
        return state

    def save(self, state: ReleaseState) -> None:
        self._validate_directory()
        state.updated_at = _utc_now()
        _atomic_json(self.state_path, asdict(state))


class ReceiptJournal:
    def __init__(self, store: StateStore):
        self.directory = store.directory / "receipts"

    def _path(self, step: str) -> Path:
        if re.fullmatch(r"[a-z0-9][a-z0-9-]*", step) is None:
            raise DeployError(f"invalid receipt step: {step}")
        return self.directory / f"{step}.json"

    def completed(self, step: str) -> dict[str, Any] | None:
        receipt = self.read(step)
        if (
            receipt is None
            or receipt.get("status") != "complete"
            or not isinstance(receipt.get("result"), dict)
        ):
            return None
        return receipt

    def read(self, step: str) -> dict[str, Any] | None:
        path = self._path(step)
        if not path.exists():
            return None
        receipt = _regular_json(path)
        transaction_id = _regular_json(self.directory.parent / "state.json").get("transaction_id")
        if (
            receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
            or receipt.get("step") != step
            or receipt.get("transaction_id") != transaction_id
            or receipt.get("status") not in {"running", "failed", "complete"}
        ):
            return None
        return receipt

    def run(
        self,
        step: str,
        inputs: dict[str, Any],
        action: Callable[[], dict[str, Any] | None],
        reconcile: Callable[[], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        path = self._path(step)
        transaction_id = _regular_json(self.directory.parent / "state.json").get("transaction_id")
        if not isinstance(transaction_id, str):
            raise DeployError("receipt has no transaction identity")
        fingerprint = _digest({"transaction_id": transaction_id, "inputs": inputs})
        if path.exists():
            prior = _regular_json(path)
            if prior.get("input_sha256") != fingerprint:
                raise DeployError(f"receipt inputs changed for {step}")
            if prior.get("status") == "complete" and isinstance(prior.get("result"), dict):
                return prior["result"]
            if reconcile is not None:
                recovered = reconcile()
                if recovered is not None:
                    if not isinstance(recovered, dict):
                        raise DeployError(f"step {step} reconciliation returned a non-object")
                    completed = {
                        **prior,
                        "status": "complete",
                        "completed_at": _utc_now(),
                        "result": recovered,
                        "error": None,
                        "reconciled": True,
                    }
                    _atomic_json(path, completed)
                    return recovered
        started = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "step": step,
            "transaction_id": transaction_id,
            "input_sha256": fingerprint,
            "status": "running",
            "started_at": _utc_now(),
            "completed_at": None,
            "result": {},
            "error": None,
        }
        _atomic_json(path, started)
        try:
            result = action() or {}
            if not isinstance(result, dict):
                raise DeployError(f"step {step} returned a non-object result")
        except BaseException as exc:
            _atomic_json(
                path,
                {**started, "status": "failed", "error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        _atomic_json(
            path,
            {
                **started,
                "status": "complete",
                "completed_at": _utc_now(),
                "result": result,
            },
        )
        return result


@dataclass(frozen=True)
class Migration:
    migration_id: str
    version: int
    approval_required: bool = False


ADAPTERS: dict[str, tuple[Migration, ...]] = {
    "none": (),
    "revision-15": (
        Migration("r15-e1-runtime-contract", 1),
        Migration("r15-forward-runtime-contract", 1),
        Migration("r15-xs-runtime-contract", 1),
        Migration("r15-price-cleanup", 1, approval_required=True),
        Migration("r15-e1-report-first", 1),
        Migration("r15-forward-report-first", 1),
        Migration("r15-xs-report-first", 1),
        Migration("r15-e1-report-second", 1),
        Migration("r15-forward-report-second", 1),
        Migration("r15-xs-report-second", 1),
        Migration("r15-agent-evaluation-report", 1),
    ),
}


class CommandRunner:
    def __init__(self, host_command_dir: Path | None = None):
        self.host_command_dir = host_command_dir.resolve() if host_command_dir else None

    def host(self, name: str) -> str:
        if self.host_command_dir is None:
            return name
        candidate = self.host_command_dir / name
        if candidate.is_symlink() or not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise DeployError(f"fake host command is unavailable: {name}")
        return str(candidate)

    def environment(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = os.environ.copy()
        if self.host_command_dir is not None:
            env["PATH"] = f"{self.host_command_dir}{os.pathsep}{env.get('PATH', '')}"
        if extra:
            env.update(extra)
        return env

    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 300,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self.environment(env),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeployError(f"command failed to start: {args[0]}: {exc}") from exc
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise DeployError(f"{Path(args[0]).name} failed: {detail}")
        return result


class ReleaseOperations:
    """Concrete host operations.  Tests substitute this class, never real host tools."""

    def __init__(
        self,
        store: StateStore,
        *,
        home: Path,
        command_runner: CommandRunner,
        api_url: str,
        ui_url: str,
        minimum_free_bytes: int,
        tool_paths: dict[str, Path | None] | None = None,
    ):
        self.store = store
        self.home = home.resolve()
        self.runner = command_runner
        self.api_url = api_url.rstrip("/")
        self.ui_url = ui_url.rstrip("/")
        self.minimum_free_bytes = minimum_free_bytes
        self.tool_paths = tool_paths or {}
        self.selected_tools: dict[str, dict[str, Any]] = {}

    def _executable_identity(self, path: Path) -> dict[str, Any]:
        requested = path.absolute()
        try:
            resolved = requested.resolve(strict=True)
        except OSError as exc:
            raise DeployError(f"release executable is unavailable: {requested}") from exc
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise DeployError(f"release executable is not executable: {requested}")
        return {
            "path": str(requested),
            "resolved_path": str(resolved),
            "sha256": _sha256(resolved),
        }

    def _resolve_tool(self, name: str) -> dict[str, Any]:
        requested = self.tool_paths.get(name)
        candidates: list[Path] = []
        if requested is not None:
            candidates.append(requested)
        else:
            if name in {"node", "npm"}:
                candidates.append(self.home / "tools/node/bin" / name)
            elif name == "uv":
                candidates.append(self.home / ".local/bin/uv")
            discovered = shutil.which(name)
            if discovered:
                candidates.append(Path(discovered))
        for candidate in candidates:
            try:
                return self._executable_identity(candidate)
            except DeployError:
                continue
        raise DeployError(f"required release executable is unavailable: {name}")

    def _resolve_release_tools(self) -> dict[str, dict[str, Any]]:
        result = {name: self._resolve_tool(name) for name in ("git", "uv", "node", "npm")}
        self.selected_tools = result
        return result

    def _tool(self, name: str) -> str:
        if name not in self.selected_tools:
            self.selected_tools[name] = self._resolve_tool(name)
        return self.selected_tools[name]["path"]

    def _git(self, root: Path, *args: str, check: bool = True) -> str:
        result = self.runner.run([self._tool("git"), *args], cwd=root, check=check, timeout=60)
        return result.stdout.strip()

    def _head(self, root: Path) -> str:
        value = self._git(root, "rev-parse", "HEAD")
        if FULL_SHA.fullmatch(value) is None:
            raise DeployError("Git returned an invalid HEAD")
        return value

    def _branch(self, root: Path) -> str:
        result = self.runner.run(
            [self._tool("git"), "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=root,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def _upstream(self, root: Path) -> str:
        result = self.runner.run(
            [
                self._tool("git"),
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            ],
            cwd=root,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def _check_workspace(self, state: ReleaseState, copies: int) -> dict[str, int]:
        try:
            database_size = Path(state.database).stat().st_size
            anchor = self.store.directory.parent
            while not anchor.exists() and anchor != anchor.parent:
                anchor = anchor.parent
            free = shutil.disk_usage(anchor).free
        except OSError as exc:
            raise DeployError(f"cannot inspect recovery workspace: {exc}") from exc
        required = self.minimum_free_bytes + copies * database_size
        if free < required:
            raise DeployError(
                f"insufficient recovery workspace: {free} free bytes, {required} required"
            )
        return {"free_bytes": free, "required_bytes": required, "database_bytes": database_size}

    def _source_status(
        self, root: Path, *, allowed_paths: frozenset[str] = frozenset()
    ) -> list[str]:
        raw = self.runner.run(
            [self._tool("git"), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
        ).stdout
        fields = raw.split("\0")
        changed: list[str] = []
        index = 0
        while index < len(fields):
            row = fields[index]
            index += 1
            if not row:
                continue
            if len(row) < 4 or row[2] != " ":
                raise DeployError("unexpected Git status record")
            status, path = row[:2], row[3:]
            if status[0] not in {" ", "?"}:
                raise DeployError(f"index is not clean: {path}")
            if status[0] in "RC" or status[1] in "RC":
                raise DeployError("renamed or copied paths are not deployable")
            if path not in allowed_paths and not path.startswith(("data/", "logs/")):
                changed.append(path)
        if changed:
            raise DeployError(f"source changed outside generated paths: {', '.join(changed)}")
        return changed

    def _registration_source_commit(self, root: Path, approved_sha: str) -> str:
        raw = self.runner.run(
            [
                self._tool("git"),
                "show",
                f"{approved_sha}:server/p15-registration.json",
            ],
            cwd=root,
        ).stdout
        try:
            source_commit = json.loads(raw)["code_identity"]["source_commit"]
        except (KeyError, TypeError, ValueError) as exc:
            raise DeployError("approved registration has no valid source_commit") from exc
        if not isinstance(source_commit, str) or FULL_SHA.fullmatch(source_commit) is None:
            raise DeployError("approved registration has no valid source_commit")
        ancestor = self.runner.run(
            [self._tool("git"), "merge-base", "--is-ancestor", source_commit, approved_sha],
            cwd=root,
            check=False,
        )
        if ancestor.returncode != 0:
            raise DeployError("registered source_commit is not an ancestor of the approved SHA")
        return source_commit

    def preflight_prepare(
        self,
        *,
        repo_root: Path,
        database: Path,
        approved_sha: str,
        adapter_set: str,
        d0: str | None,
    ) -> dict[str, Any]:
        if FULL_SHA.fullmatch(approved_sha) is None:
            raise DeployError("approved SHA must be 40 lowercase hexadecimal characters")
        if adapter_set not in ADAPTERS:
            raise DeployError(f"unknown adapter set: {adapter_set}")
        if adapter_set == "revision-15" and d0 is None:
            raise DeployError("revision-15 requires --d0")
        tools = self._resolve_release_tools()
        repo_root = repo_root.resolve(strict=True)
        database = database.resolve(strict=True)
        if self.store.directory == repo_root or repo_root in self.store.directory.parents:
            raise DeployError("state directory must be outside the release checkout")
        if os.path.lexists(self.store.directory):
            raise DeployError("state directory already exists; refusing to overwrite")
        audit = worktree_audit.build_audit(repo_root)
        gates = audit["review_gates"]
        if (
            not gates["index_empty"]
            or not gates["ownership_complete"]
            or not gates["untracked_files_safe"]
            or not audit["protected_research"]["identity_complete"]
        ):
            raise DeployError("strict worktree audit failed")
        self._source_status(repo_root)
        source_branch = self._branch(repo_root)
        source_upstream = self._upstream(repo_root)
        if source_branch != "main" or source_upstream != "origin/main":
            raise DeployError("release checkout must be main tracking origin/main")
        original_sha = self._head(repo_root)
        self._git(repo_root, "cat-file", "-e", f"{approved_sha}^{{commit}}")
        ancestor = self.runner.run(
            [self._tool("git"), "merge-base", "--is-ancestor", original_sha, approved_sha],
            cwd=repo_root,
            check=False,
        )
        if ancestor.returncode != 0:
            raise DeployError("approved source is not a fast-forward of the current source")
        registration_source_commit = self._registration_source_commit(repo_root, approved_sha)
        lock_hashes = {}
        for relative in ("uv.lock", "ui/package-lock.json"):
            content = self.runner.run(
                [self._tool("git"), "show", f"{approved_sha}:{relative}"], cwd=repo_root
            ).stdout.encode()
            lock_hashes[relative] = hashlib.sha256(content).hexdigest()
        probe = ReleaseState(
            schema_version=STATE_SCHEMA_VERSION,
            transaction_id="dry-run",
            created_at=_utc_now(),
            updated_at=_utc_now(),
            phase="preparing",
            repo_root=str(repo_root),
            database=str(database),
            approved_sha=approved_sha,
            original_sha=original_sha,
            adapter_set=adapter_set,
            d0=d0,
        )
        workspace = self._check_workspace(probe, copies=3)
        return {
            "original_sha": original_sha,
            "approved_sha": approved_sha,
            "source_branch": source_branch,
            "source_upstream": source_upstream,
            "lock_sha256": lock_hashes,
            "tools": tools,
            "adapter_set": adapter_set,
            "registration_source_commit": registration_source_commit,
            "migrations": [asdict(item) for item in ADAPTERS[adapter_set]],
            "workspace": workspace,
            "audit_sha256": _digest(audit),
        }

    def prepare_release(self, state: ReleaseState, preflight: dict[str, Any]) -> dict[str, Any]:
        root = Path(state.repo_root)
        prepared = self.store.directory / "prepared"
        source = prepared / "source"
        prepared.mkdir(mode=0o700)
        self.runner.run(
            [
                preflight["tools"]["git"]["path"],
                "worktree",
                "add",
                "--detach",
                str(source),
                state.approved_sha,
            ],
            cwd=root,
            timeout=120,
        )
        manifest = release_manifest.build_manifest(source, Path(state.database))
        if not manifest["release_eligible"] or manifest["git"]["sha"] != state.approved_sha:
            raise DeployError(f"approved source is not release eligible: {manifest['reasons']}")
        _atomic_json(prepared / "release-manifest.json", manifest)
        locks = {name: _sha256(source / name) for name in ("uv.lock", "ui/package-lock.json")}
        if locks != preflight["lock_sha256"]:
            raise DeployError("dependency locks changed after preflight")

        python_env = prepared / f"python-{locks['uv.lock']}"
        uv = preflight["tools"]["uv"]["path"]
        self.runner.run(
            [uv, "sync", "--project", str(source), "--frozen", "--no-dev", "--no-install-project"],
            cwd=source,
            env={"UV_PROJECT_ENVIRONMENT": str(python_env)},
            timeout=1800,
        )
        python = python_env / "bin/python"
        if not python.is_file():
            raise DeployError("prepared Python environment has no interpreter")

        ui_runtime = prepared / f"ui-{locks['ui/package-lock.json']}"
        shutil.copytree(
            source / "ui", ui_runtime, ignore=shutil.ignore_patterns("node_modules", ".next")
        )
        npm = preflight["tools"]["npm"]["path"]
        node_path = str(Path(preflight["tools"]["node"]["path"]).parent)
        tool_env = {"PATH": f"{node_path}{os.pathsep}{os.environ.get('PATH', '')}"}
        self.runner.run([npm, "ci"], cwd=ui_runtime, env=tool_env, timeout=1800)
        self.runner.run([npm, "run", "build"], cwd=ui_runtime, env=tool_env, timeout=1800)
        if not (ui_runtime / "node_modules").is_dir() or not (ui_runtime / ".next").is_dir():
            raise DeployError("prepared UI environment is incomplete")

        env = {"PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
        self.runner.run(
            [str(python), "-c", "import engine.lib.db, server.main, tools.release_manifest"],
            cwd=source,
            env=env,
        )
        if state.adapter_set == "revision-15":
            self.runner.run(
                [
                    str(python),
                    "-c",
                    "import json; assert json.load(open('server/p15-registration.json'))"
                    "['registration_revision'] == 15",
                ],
                cwd=source,
                env=env,
            )
        runtime_versions = json.loads(
            self.runner.run(
                [
                    str(python),
                    "-c",
                    "import json; from engine import forward_review,xs_forward_review; "
                    "from farm import experiment_runner; print(json.dumps({"
                    "'forward_review':forward_review.RUNTIME_CONTRACT_VERSION,"
                    "'xs_forward_review':xs_forward_review.RUNTIME_CONTRACT_VERSION,"
                    "'e1_forward':experiment_runner.RUNTIME_CONTRACT_VERSION}))",
                ],
                cwd=source,
                env=env,
            ).stdout
        )
        registration_path = source / "server/p15-registration.json"
        registration = json.loads(registration_path.read_text())
        versions = {
            "python": self.runner.run([str(python), "--version"]).stdout.strip(),
            "node": self.runner.run(
                [preflight["tools"]["node"]["path"], "--version"]
            ).stdout.strip(),
        }
        return {
            "source": str(source),
            "python_environment": str(python_env),
            "node_environment": str(ui_runtime),
            "node_modules": str(ui_runtime / "node_modules"),
            "ui_build": str(ui_runtime / ".next"),
            "lock_sha256": locks,
            "tools": preflight["tools"],
            "unit_policy": {
                name: "optional" if name in OPTIONAL_UNITS else "required"
                for name in sorted(install_automation.UNIT_SOURCES)
            },
            "semantic": {
                "registration_revision": registration["registration_revision"],
                "registration_source_commit": registration["code_identity"]["source_commit"],
                "registration_sha256": _sha256(registration_path),
                "runtime_versions": runtime_versions,
            },
            "release_manifest_sha256": manifest["manifest_sha256"],
            "release_tool_sha256": _sha256(source / "tools/release_deploy.py"),
            "versions": versions,
            "migrations": [asdict(item) for item in ADAPTERS[state.adapter_set]],
        }

    def validate_state_source(self, state: ReleaseState, expected: str) -> None:
        root = Path(state.repo_root)
        if self._head(root) != expected:
            raise DeployError("release checkout source changed")
        allowed = frozenset(state.prior_runtimes) if expected == state.approved_sha else frozenset()
        self._source_status(root, allowed_paths=allowed)
        migrations = state.prepared.get("migrations")
        if migrations != [asdict(item) for item in ADAPTERS.get(state.adapter_set, ())]:
            raise DeployError("unknown or changed migration registry")

    def validate_reconciled_source(self, state: ReleaseState, reconciled_sha: str) -> None:
        root = Path(state.repo_root)
        if self._head(root) != reconciled_sha:
            raise DeployError("current source does not match the reconciled SHA")
        if self._branch(root) != state.source_branch:
            raise DeployError("reconciled source is not on the saved release branch")
        if self._upstream(root) != state.source_upstream:
            raise DeployError("reconciled source does not track the saved upstream")
        self._source_status(root)

    def validate_recovery_tools(self, state: ReleaseState) -> None:
        tools = state.prepared["tools"]
        if not isinstance(tools, dict) or set(tools) != {"git", "uv", "node", "npm"}:
            raise DeployError("prepared release tool paths are incomplete")
        git = tools["git"]
        if not isinstance(git, dict) or self._executable_identity(Path(git.get("path", ""))) != git:
            raise DeployError("prepared release executable changed: git")
        self.selected_tools = tools

    def validate_prepared(self, state: ReleaseState) -> None:
        source = Path(state.prepared["source"])
        locks = state.prepared["lock_sha256"]
        tools = state.prepared["tools"]
        if not isinstance(tools, dict) or set(tools) != {"git", "uv", "node", "npm"}:
            raise DeployError("prepared release tool paths are incomplete")
        for name, identity in tools.items():
            if (
                not isinstance(identity, dict)
                or self._executable_identity(Path(identity.get("path", ""))) != identity
            ):
                raise DeployError(f"prepared release executable changed: {name}")
        self.selected_tools = tools
        if self._head(source) != state.approved_sha:
            raise DeployError("prepared source identity changed")
        if self.runner.run(
            [self._tool("git"), "status", "--porcelain=v1", "--untracked-files=all"], cwd=source
        ).stdout:
            raise DeployError("prepared source worktree changed")
        if (
            _sha256(source / "uv.lock") != locks["uv.lock"]
            or _sha256(source / "ui/package-lock.json") != locks["ui/package-lock.json"]
        ):
            raise DeployError("prepared dependency locks changed")
        if _sha256(source / "tools/release_deploy.py") != state.prepared["release_tool_sha256"]:
            raise DeployError("prepared release tool identity changed")
        manifest = _regular_json(self.store.directory / "prepared/release-manifest.json")
        if manifest.get("manifest_sha256") != state.prepared["release_manifest_sha256"]:
            raise DeployError("prepared release manifest identity changed")

    def _systemctl(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.runner.run(
            [self.runner.host("systemctl"), "--user", *args], check=check, timeout=60
        )

    def _unit_properties(self, name: str) -> dict[str, str]:
        raw = self._systemctl(
            "show",
            name,
            "--property=Id,LoadState,ActiveState,SubState,UnitFileState,ExecStart,Triggers,MainPID,ControlGroup",
        ).stdout
        return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)

    def _unit_names(self) -> set[str]:
        names: set[str] = set(install_automation.UNIT_SOURCES)
        for action in ("list-unit-files", "list-units"):
            raw = self._systemctl(action, "--all", "--no-legend", "--plain", "--no-pager").stdout
            for line in raw.splitlines():
                fields = line.split()
                if fields and fields[0].endswith((".service", ".timer")):
                    names.add(fields[0])
        properties = {name: self._unit_properties(name) for name in sorted(names)}
        managed = {
            name
            for name, values in properties.items()
            if values.get("LoadState") != "not-found"
            and (name.startswith(("trading-engine-", "massive-")) or name in SPECIAL_UNITS)
        }
        managed |= {
            name
            for name, values in properties.items()
            if set(values.get("Triggers", "").split()) & managed
        }
        managed |= set(install_automation.UNIT_SOURCES)
        return managed

    def _read_crontab(self) -> dict[str, Any]:
        result = self.runner.run([self.runner.host("crontab"), "-l"], check=False, timeout=30)
        if result.returncode == 0:
            return {"present": True, "content": result.stdout}
        if result.returncode == 1 and result.stderr.lower().startswith("no crontab for "):
            return {"present": False, "content": ""}
        raise DeployError("installed crontab is unreadable")

    def _capture_path(self, path: Path, destination: Path) -> dict[str, Any]:
        if path.is_symlink():
            return {"kind": "symlink", "target": os.readlink(path)}
        if not path.exists():
            return {"kind": "absent"}
        if not path.is_file():
            raise DeployError(f"installed unit has an unsupported type: {path.name}")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(path, destination, follow_symlinks=False)
        return {"kind": "file", "saved": str(destination), "sha256": _sha256(destination)}

    def _tree_manifest(self, root: Path) -> dict[str, Any]:
        entries: dict[str, dict[str, Any]] = {}
        if root.exists():
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root).as_posix()
                if path.is_symlink():
                    entries[relative] = {"kind": "symlink", "target": os.readlink(path)}
                elif path.is_file() and not path.name.endswith(".lock"):
                    entries[relative] = {
                        "kind": "file",
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                elif not path.is_dir():
                    raise DeployError(f"artifact tree contains an unsupported node: {relative}")
        return {"schema_version": 1, "entries": entries, "sha256": _digest(entries)}

    def _verified_tree_manifest(self, root: Path, expected: dict[str, Any]) -> None:
        if self._tree_manifest(root) != expected:
            raise DeployError(f"artifact tree identity mismatch: {root.name}")

    def _artifact_manifest(self, root: Path) -> dict[str, Any]:
        entries = {}
        for name in ("data", "logs"):
            subtree = self._tree_manifest(root / name)
            entries.update({f"{name}/{path}": value for path, value in subtree["entries"].items()})
        for relative in backup_database.OPTIONAL_OPERATIONAL_CONTROL_FILES:
            path = root / relative
            if path.is_symlink():
                entries[relative] = {"kind": "symlink", "target": os.readlink(path)}
            elif path.is_file():
                entries[relative] = {
                    "kind": "file",
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
        return {"schema_version": 1, "entries": entries, "sha256": _digest(entries)}

    def capture_inventory(self, state: ReleaseState) -> dict[str, Any]:
        root = Path(state.repo_root)
        names = self._unit_names()
        units = {name: self._unit_properties(name) for name in sorted(names)}
        cron = self._read_crontab()
        if any(UNIT_NAME.fullmatch(name) is None for name in names):
            raise DeployError("systemd returned an unsafe unit name")
        saved_units = self.store.directory / "inventory" / "units"
        unit_files = {
            name: self._capture_path(self.home / ".config/systemd/user" / name, saved_units / name)
            for name in sorted(names)
        }
        artifacts = self.store.directory / "inventory" / "artifacts"
        try:
            predeploy_meta = self.request_json(f"{self.api_url}/meta")[0]
        except DeployError as exc:
            raise DeployError(f"predeploy semantic API is unavailable: {exc}") from exc
        processes = self.runner.run(
            [self.runner.host("ps"), "-eo", "pid=,ppid=,args="], timeout=30
        ).stdout
        registration_path = root / "server/p15-registration.json"
        registration = json.loads(registration_path.read_text())
        return {
            "captured_at": _utc_now(),
            "units": units,
            "unit_files": unit_files,
            "crontab": cron,
            "predeploy_meta": predeploy_meta,
            "registration": {
                "registration_revision": registration["registration_revision"],
                "registration_source_commit": registration["code_identity"]["source_commit"],
                "registration_sha256": _sha256(registration_path),
            },
            "processes_sha256": hashlib.sha256(processes.encode()).hexdigest(),
            "artifacts": str(artifacts),
        }

    def capture_artifacts(self, state: ReleaseState) -> dict[str, Any]:
        root = Path(state.repo_root)
        artifacts = Path(state.inventory["artifacts"])
        manifest_path = self.store.directory / "inventory/artifacts.json"
        if artifacts.exists():
            manifest = self._artifact_manifest(artifacts)
            if manifest_path.exists() and _regular_json(manifest_path) != manifest:
                raise DeployError("captured artifact image changed")
            if not manifest_path.exists():
                _atomic_json(manifest_path, manifest)
            return manifest
        temporary = artifacts.with_name("artifacts.partial")
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(mode=0o700, parents=True)
        for name in ("data", "logs"):
            source = root / name
            if source.is_dir():
                shutil.copytree(
                    source,
                    temporary / name,
                    ignore=shutil.ignore_patterns("*.lock"),
                    symlinks=True,
                )
        for relative in backup_database.OPTIONAL_OPERATIONAL_CONTROL_FILES:
            source = root / relative
            target = temporary / relative
            if source.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(os.readlink(source), target)
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        os.replace(temporary, artifacts)
        manifest = self._artifact_manifest(artifacts)
        _atomic_json(manifest_path, manifest)
        return manifest

    def reconcile_artifacts(self, state: ReleaseState) -> dict[str, Any] | None:
        artifacts = Path(state.inventory["artifacts"])
        if not artifacts.is_dir():
            return None
        manifest = self._artifact_manifest(artifacts)
        manifest_path = self.store.directory / "inventory/artifacts.json"
        if manifest_path.exists() and _regular_json(manifest_path) != manifest:
            raise DeployError("captured artifact image changed")
        if not manifest_path.exists():
            _atomic_json(manifest_path, manifest)
        return manifest

    def _stop_units(self, names: set[str]) -> None:
        timers = sorted(name for name in names if name.endswith(".timer"))
        services = sorted(name for name in names if name.endswith(".service"))
        if timers:
            self._systemctl("stop", *timers)
        if services:
            self._systemctl("stop", *services)

    def _surviving_producers(self, root: Path) -> list[str]:
        raw = self.runner.run(
            [self.runner.host("ps"), "-eo", "pid=,ppid=,args="], timeout=30
        ).stdout
        found = []
        for line in raw.splitlines():
            fields = line.strip().split(None, 2)
            if len(fields) != 3 or not fields[0].isdigit():
                continue
            pid, _parent, command = fields
            if (
                int(pid) != os.getpid()
                and str(root) in command
                and PRODUCER_PATTERN.search(command)
            ):
                found.append(command)
        return found

    def quiesce(self, state: ReleaseState) -> dict[str, Any]:
        names = set(state.inventory["units"])
        discovered = self._unit_names()
        unexpected = {
            name
            for name in discovered - names
            if self._unit_properties(name).get("LoadState") != "not-found"
        }
        if unexpected:
            raise DeployError(
                f"refusing unit outside saved inventory: {', '.join(sorted(unexpected))}"
            )
        properties = {name: self._unit_properties(name) for name in sorted(names)}
        loaded = {
            name for name, values in properties.items() if values.get("LoadState") != "not-found"
        }
        saved_cron = state.inventory["crontab"]
        cron = self._read_crontab()
        if not saved_cron["present"] and cron["present"] and not state.automation:
            raise DeployError("crontab appeared after inventory capture")
        if saved_cron["present"] and cron["present"] and not state.automation:
            if cron["content"] != saved_cron["content"]:
                raise DeployError("crontab changed after inventory capture")
        if cron["present"]:
            result = self.runner.run([self.runner.host("crontab"), "-r"], check=False, timeout=30)
            if result.returncode != 0:
                raise DeployError("failed to remove the installed crontab")
            if self._read_crontab()["present"]:
                raise DeployError("installed crontab survived removal")
        self._stop_units(loaded)
        for name in sorted(loaded):
            values = self._unit_properties(name)
            if values.get("LoadState") != "not-found" and (
                values.get("ActiveState") not in {"inactive", "failed"}
                or values.get("MainPID", "0") != "0"
            ):
                raise DeployError(f"unit survived quiescence: {name}")
        jobs = self._systemctl("list-jobs", "--no-legend", "--no-pager").stdout
        if any(name in jobs for name in loaded):
            raise DeployError("a managed systemd job survived quiescence")
        surviving = self._surviving_producers(Path(state.repo_root))
        if surviving:
            raise DeployError(f"producer process survived quiescence: {surviving[0]}")
        return {"units_stopped": sorted(loaded), "crontab_removed": cron["present"]}

    @contextmanager
    def producer_locks(self, state: ReleaseState) -> Iterator[frozenset[str]]:
        root = Path(state.repo_root)
        with ExitStack() as stack:
            for relative in backup_database.LOCK_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.is_symlink():
                    raise DeployError(f"producer lock is a symlink: {relative}")
                flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(path, flags, 0o600)
                stack.callback(os.close, descriptor)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise DeployError(f"producer lock is held: {relative}") from exc
            yield frozenset(backup_database.LOCK_FILES)

    def predeploy_adapter_check(self, state: ReleaseState) -> dict[str, Any]:
        if state.adapter_set == "none":
            return {"adapter_set": "none"}
        code = """
import json, os
from datetime import date
from pathlib import Path
from engine.lib import db
registration=json.load(open('server/p15-registration.json'))['registration_revision']
assert registration == 14, registration
with db.connect(Path(os.environ['TRADING_ENGINE_DB']), read_only=True) as con:
 rows=con.execute("SELECT DISTINCT break_date,registration_revision FROM sim_book_breaks WHERE kind='cost_profile'").fetchall()
assert rows == [(date.fromisoformat(os.environ['RELEASE_D0']), 14)], rows
print(json.dumps({'registration_revision': registration, 'cost_breaks': [[str(a), b] for a,b in rows]}))
"""
        return self._python_json(
            state,
            code,
            env={"RELEASE_D0": state.d0 or ""},
            python=Path(state.repo_root) / ".venv/bin/python",
        )

    def create_backup(self, state: ReleaseState) -> dict[str, Any]:
        self._check_workspace(state, copies=3)
        destination = self.store.directory / "recovery"
        if destination.exists():
            return backup_database.verify_backup(destination)
        result = backup_database.create_backup(
            Path(state.repo_root), Path(state.database), destination
        )
        verified = backup_database.verify_backup(destination)
        if result["manifest_sha256"] != verified["manifest_sha256"]:
            raise DeployError("recovery bundle identity changed after creation")
        manifest = _regular_json(destination / backup_database.MANIFEST_FILENAME)
        if manifest.get("release_identity", {}).get("git_sha") != state.original_sha:
            raise DeployError("recovery bundle does not identify the predeploy source")
        return verified

    def switch_source(self, state: ReleaseState) -> dict[str, Any]:
        root = Path(state.repo_root)
        if self._head(root) == state.approved_sha:
            self._overlay_artifacts(state)
            return {"git_sha": state.approved_sha, "idempotent": True}
        self.validate_state_source(state, state.original_sha)
        if (root / "data").exists():
            self.runner.run([self._tool("git"), "checkout", "HEAD", "--", "data"], cwd=root)
        self.runner.run(
            [self._tool("git"), "merge", "--ff-only", state.approved_sha],
            cwd=root,
            timeout=120,
        )
        if self._head(root) != state.approved_sha:
            raise DeployError("source switch did not select the approved SHA")
        self._overlay_artifacts(state)
        return {"git_sha": state.approved_sha, "idempotent": False}

    def _overlay_artifacts(self, state: ReleaseState) -> None:
        root = Path(state.repo_root)
        artifacts = Path(state.inventory["artifacts"])
        for name in ("data", "logs"):
            saved = artifacts / name
            if saved.is_dir():
                shutil.copytree(saved, root / name, dirs_exist_ok=True)

    def reconcile_source_switch(self, state: ReleaseState) -> dict[str, Any] | None:
        if self._head(Path(state.repo_root)) != state.approved_sha:
            return None
        self.validate_state_source(state, state.approved_sha)
        self._overlay_artifacts(state)
        return {"git_sha": state.approved_sha, "reconciled": True}

    def _prior_runtime_identity(self, live: Path, saved: Path) -> dict[str, Any]:
        identity = saved / "identity.json"
        if saved.exists():
            if not identity.exists():
                raise DeployError(f"prior runtime capture is incomplete: {live}")
            return _regular_json(identity)
        saved.mkdir(mode=0o700, parents=True)
        if live.is_symlink():
            prior = {"kind": "symlink", "target": os.readlink(live)}
        elif not live.exists():
            prior = {"kind": "absent"}
        elif live.is_dir():
            prior = {"kind": "directory", "saved": str(saved / "directory")}
        else:
            raise DeployError(f"runtime selection target has an unsupported type: {live}")
        _atomic_json(identity, prior)
        return prior

    def _select_runtime(self, live: Path, prepared: Path, saved: Path) -> dict[str, Any]:
        if not prepared.is_dir():
            raise DeployError(f"prepared runtime is missing: {prepared}")
        prior = self._prior_runtime_identity(live, saved)
        if live.is_symlink() and Path(os.path.realpath(live)) == prepared.resolve():
            return prior
        if live.is_symlink():
            if prior["kind"] == "symlink" and os.readlink(live) != prior["target"]:
                raise DeployError(f"runtime changed during selection: {live}")
            live.unlink()
        elif live.is_dir():
            if prior["kind"] != "directory" or Path(prior["saved"]).exists():
                raise DeployError(f"runtime changed during selection: {live}")
            try:
                os.replace(live, Path(prior["saved"]))
            except OSError as exc:
                raise DeployError(f"cannot atomically save prior runtime {live}: {exc}") from exc
        elif os.path.lexists(live) or prior["kind"] not in {"absent", "directory", "symlink"}:
            raise DeployError(f"runtime changed during selection: {live}")
        if prior["kind"] == "directory" and not Path(prior["saved"]).is_dir():
            raise DeployError(f"saved prior runtime is unavailable: {live}")
        live.parent.mkdir(parents=True, exist_ok=True)
        temporary = live.parent / f".{live.name}.release-{secrets.token_hex(6)}"
        os.symlink(prepared, temporary)
        os.replace(temporary, live)
        return prior

    def switch_runtimes(self, state: ReleaseState) -> dict[str, Any]:
        root = Path(state.repo_root)
        saved_root = self.store.directory / "inventory" / "runtimes"
        result = {}
        for relative, key in RUNTIME_LINKS.items():
            name = relative.replace("/", "--").lstrip(".")
            live = root / relative
            saved = saved_root / name
            state.prior_runtimes[relative] = self._prior_runtime_identity(live, saved)
            self.store.save(state)
            result[relative] = self._select_runtime(live, Path(state.prepared[key]), saved)
            state.prior_runtimes[relative] = result[relative]
            self.store.save(state)
        return result

    def reconcile_runtime_switch(self, state: ReleaseState) -> dict[str, Any] | None:
        root = Path(state.repo_root)
        saved_root = self.store.directory / "inventory/runtimes"
        result = {}
        for relative, key in RUNTIME_LINKS.items():
            identity = saved_root / relative.replace("/", "--").lstrip(".") / "identity.json"
            live = root / relative
            if not identity.exists() or not live.is_symlink():
                return None
            if Path(os.path.realpath(live)) != Path(state.prepared[key]).resolve():
                return None
            result[relative] = _regular_json(identity)
        state.prior_runtimes = result
        self.store.save(state)
        return result

    def _hydrate_prior_runtimes(self, state: ReleaseState) -> None:
        saved_root = self.store.directory / "inventory/runtimes"
        for relative in RUNTIME_LINKS:
            if relative in state.prior_runtimes:
                continue
            identity = saved_root / relative.replace("/", "--").lstrip(".") / "identity.json"
            if identity.exists():
                state.prior_runtimes[relative] = _regular_json(identity)
        self.store.save(state)

    def _python_json(
        self,
        state: ReleaseState,
        code: str,
        *,
        env: dict[str, str] | None = None,
        python: Path | None = None,
    ) -> dict[str, Any]:
        root = Path(state.repo_root)
        merged = {
            "PYTHONPATH": str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TRADING_ENGINE_DB": state.database,
            **(env or {}),
        }
        result = self.runner.run(
            [str(python or Path(state.prepared["python_environment"]) / "bin/python"), "-c", code],
            cwd=root,
            env=merged,
            timeout=900,
        )
        try:
            value = json.loads(result.stdout)
        except ValueError as exc:
            raise DeployError("migration returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise DeployError("migration returned a non-object result")
        return value

    def _python_module(self, state: ReleaseState, *args: str) -> dict[str, Any]:
        root = Path(state.repo_root)
        result = self.runner.run(
            [state.prepared["python_environment"] + "/bin/python", "-m", *args],
            cwd=root,
            env={"PYTHONPATH": str(root), "TRADING_ENGINE_DB": state.database},
            timeout=900,
        )
        return {"stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest()}

    def plan_migration(self, state: ReleaseState, migration: Migration) -> dict[str, Any]:
        if migration.migration_id != "r15-price-cleanup":
            return {}
        code = """
import json
from pathlib import Path
from engine.lib import db
from engine.price_quarantine import cleanup_hard_invalid_prices
with db.connect(Path(__import__('os').environ['TRADING_ENGINE_DB'])) as con:
 report=cleanup_hard_invalid_prices(con)
 report['reject_rows_before']=con.execute('SELECT COUNT(*) FROM price_observation_rejects').fetchone()[0]
print(json.dumps(report, sort_keys=True))
"""
        return self._python_json(state, code)

    def apply_migration(
        self, state: ReleaseState, migration: Migration, plan: dict[str, Any] | None
    ) -> dict[str, Any]:
        migration_id = migration.migration_id
        modules = {
            "r15-e1-runtime-contract": ("farm.experiment_runner", "--migrate-runtime-contract"),
            "r15-forward-runtime-contract": (
                "engine.forward_review",
                "--migrate-runtime-contract",
            ),
            "r15-xs-runtime-contract": (
                "engine.xs_forward_review",
                "--migrate-runtime-contract",
            ),
            "r15-e1-report-first": ("farm.experiment_runner", "--report-only"),
            "r15-forward-report-first": ("engine.forward_review",),
            "r15-xs-report-first": ("engine.xs_forward_review",),
            "r15-e1-report-second": ("farm.experiment_runner", "--report-only"),
            "r15-forward-report-second": ("engine.forward_review",),
            "r15-xs-report-second": ("engine.xs_forward_review",),
            "r15-agent-evaluation-report": ("server.agent_evaluation_reporting",),
        }
        if migration_id in modules:
            return self._python_module(state, *modules[migration_id])
        if migration_id != "r15-price-cleanup" or plan is None:
            raise DeployError(f"unknown migration: {migration_id}")
        code = """
import json, os
from pathlib import Path
from engine.lib import db
from engine.price_quarantine import cleanup_hard_invalid_prices
expected=json.loads(os.environ['RELEASE_MIGRATION_PLAN'])
expected_report={k:v for k,v in expected.items() if k!='reject_rows_before'}
with db.connect(Path(os.environ['TRADING_ENGINE_DB'])) as con:
 actual=cleanup_hard_invalid_prices(con)
 assert actual == expected_report, (actual, expected_report)
 applied=cleanup_hard_invalid_prices(con, dry_run=False)
 assert applied['moved'] == expected['invalid_rows'], (applied, expected)
 assert cleanup_hard_invalid_prices(con)['invalid_rows'] == 0
 applied['reject_rows_before']=expected['reject_rows_before']
 applied['reject_rows_after']=con.execute('SELECT COUNT(*) FROM price_observation_rejects').fetchone()[0]
 assert applied['reject_rows_after'] == expected['reject_rows_before'] + expected['invalid_rows']
print(json.dumps(applied, sort_keys=True))
"""
        return self._python_json(
            state, code, env={"RELEASE_MIGRATION_PLAN": json.dumps(plan, sort_keys=True)}
        )

    def migration_intent(
        self, state: ReleaseState, migration: Migration, plan: dict[str, Any] | None
    ) -> dict[str, Any]:
        path = self.store.directory / "migration-intents" / f"{migration.migration_id}.json"
        if path.exists():
            return _regular_json(path)
        root = Path(state.repo_root)
        migration_id = migration.migration_id
        if migration_id == "r15-price-cleanup":
            intent = {"plan_sha256": _digest(plan)}
        elif migration_id == "r15-agent-evaluation-report":
            output = root / "data/reports/agent-evaluation.json"
            intent = {"output_sha256_before": _sha256(output) if output.is_file() else None}
        elif migration_id.startswith("r15-e1-"):
            output = root / "data/reports/experiments/e1-spy-monday-forward.json"
            intent = {"output_sha256_before": _sha256(output) if output.is_file() else None}
        elif migration_id.startswith("r15-forward-"):
            output = root / "data/reports/forward/sector_momentum.json"
            intent = {"output_sha256_before": _sha256(output) if output.is_file() else None}
        elif migration_id.startswith("r15-xs-"):
            output = root / "data/reports/forward/xs_momentum_12_1.json"
            intent = {"output_sha256_before": _sha256(output) if output.is_file() else None}
        else:
            raise DeployError(f"unknown migration: {migration_id}")
        _atomic_json(path, intent)
        return intent

    def reconcile_migration(
        self,
        state: ReleaseState,
        migration: Migration,
        plan: dict[str, Any] | None,
        intent: dict[str, Any],
    ) -> dict[str, Any] | None:
        root = Path(state.repo_root)
        migration_id = migration.migration_id
        if migration_id == "r15-price-cleanup":
            if plan is None:
                return None
            if intent.get("plan_sha256") != _digest(plan):
                raise DeployError("price cleanup intent changed")
            current = self.plan_migration(state, migration)
            expected_rejects = plan["reject_rows_before"] + plan["invalid_rows"]
            if current["invalid_rows"] != 0 or current["reject_rows_before"] != expected_rejects:
                return None
            return {
                "reconciled": True,
                "moved": plan["invalid_rows"],
                "reject_rows_after": expected_rejects,
            }
        if migration_id == "r15-agent-evaluation-report":
            path = root / "data/reports/agent-evaluation.json"
            try:
                payload = json.loads(path.read_text())
            except (OSError, ValueError):
                return None
            required = {"cohorts", "coverage", "data_provenance", "generated_at"}
            if not isinstance(payload, dict) or not required <= set(payload):
                return None
            if intent.get("output_sha256_before") == _sha256(path):
                return None
            return {"reconciled": True, "output_sha256": _sha256(path)}
        if migration_id.startswith("r15-e1-"):
            path = root / "data/reports/experiments/e1-spy-monday-forward.json"
            expected = R15_RUNTIME_VERSIONS["e1"]
            nested = False
        elif migration_id.startswith("r15-forward-"):
            path = root / "data/reports/forward/sector_momentum.json"
            expected = R15_RUNTIME_VERSIONS["forward"]
            nested = True
        elif migration_id.startswith("r15-xs-"):
            path = root / "data/reports/forward/xs_momentum_12_1.json"
            expected = R15_RUNTIME_VERSIONS["xs"]
            nested = True
        else:
            raise DeployError(f"unknown migration: {migration_id}")
        try:
            payload = json.loads(path.read_text())
            runtime = payload["frozen_runtime"] if nested else payload
        except (OSError, KeyError, TypeError, ValueError):
            return None
        if runtime.get("runtime_contract_version") != expected:
            return None
        if nested and payload.get("status") not in {
            "WAITING",
            "ACCUMULATING",
            "PASS-FORWARD",
            "INCONCLUSIVE",
            "REVIEW-KILL",
        }:
            return None
        if intent.get("output_sha256_before") == _sha256(path):
            return None
        return {"reconciled": True, "output_sha256": _sha256(path)}

    def _automation_invoke(
        self, state: ReleaseState, mode: str
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        root = Path(state.repo_root)
        result = self.runner.run(
            [
                state.prepared["python_environment"] + "/bin/python",
                "-m",
                "tools.install_automation",
                "--repo-root",
                str(root),
                "--home",
                str(self.home),
                mode,
            ],
            cwd=root,
            env={"PYTHONPATH": str(root)},
            timeout=900,
            check=False,
        )
        try:
            summary = json.loads(result.stdout)
        except ValueError as exc:
            raise DeployError("automation installer returned invalid JSON") from exc
        if not isinstance(summary, dict):
            raise DeployError("automation installer returned a non-object")
        return result, summary

    def _record_automation_mutations(self, state: ReleaseState) -> dict[str, Any]:
        root = Path(state.repo_root)
        changed_files = []
        enablement = []
        for name, saved in state.inventory["unit_files"].items():
            target = self.home / ".config/systemd/user" / name
            if target.is_symlink():
                current = {"kind": "symlink", "target": os.readlink(target)}
            elif target.is_file():
                current = {"kind": "file", "sha256": _sha256(target)}
            elif not target.exists():
                current = {"kind": "absent"}
            else:
                raise DeployError(f"installed unit has an unsupported type: {name}")
            original = {key: saved[key] for key in ("kind", "target", "sha256") if key in saved}
            if current != original:
                relative = install_automation.UNIT_SOURCES.get(name)
                if (
                    relative is None
                    or current.get("kind") != "file"
                    or current.get("sha256") != _sha256(root / relative)
                ):
                    raise DeployError(f"unit changed outside the recorded installer plan: {name}")
                changed_files.append(name)
            prior = state.inventory["units"][name].get("UnitFileState")
            observed = self._unit_properties(name).get("UnitFileState")
            if observed != prior:
                if name not in install_automation.AUTOSTART_UNITS or observed != "enabled":
                    raise DeployError(f"unit enablement changed outside installer policy: {name}")
                enablement.append(name)
        state.automation.update(
            {
                "installed_unit_files": sorted(changed_files),
                "enablement_units": sorted(enablement),
            }
        )
        self.store.save(state)
        return state.automation

    def _optional_automation_result(
        self, state: ReleaseState, summary: dict[str, Any], apply_exit: int
    ) -> dict[str, Any] | None:
        changes = summary.get("changes", {})
        unit_failures = sorted(
            set(changes.get("service_units", []))
            | set(changes.get("enable_units", []))
            | set(changes.get("start_units", []))
        )
        if summary.get("errors") or changes.get("crontab") or changes.get("enable_linger"):
            return None
        policy = state.prepared["unit_policy"]
        if any(policy.get(name) != "optional" for name in unit_failures):
            return None
        if not unit_failures:
            return None
        return {
            "status": "optional-failures",
            **state.automation,
            "optional_failures": unit_failures,
            "apply_exit": apply_exit,
            "post_audit_sha256": _digest(summary),
        }

    def install_automation(self, state: ReleaseState) -> dict[str, Any]:
        self._record_automation_mutations(state)
        _audit_result, before = self._automation_invoke(state, "--audit")
        if before.get("status") not in {"ok", "changes-required"} or before.get("errors"):
            reasons = ", ".join(map(str, before.get("errors", []))) or str(
                before.get("status", "unknown")
            )
            raise DeployError(f"automation installer preflight is invalid: {reasons}")
        changes = before.get("changes", {})
        state.automation.update(
            {
                "planned_unit_files": sorted(changes.get("service_units", [])),
                "optional_failures": [],
            }
        )
        self.store.save(state)
        try:
            applied, first = self._automation_invoke(state, "--apply")
        finally:
            self._record_automation_mutations(state)
        _post_result, after = self._automation_invoke(state, "--audit")
        residual = after.get("changes", {})
        unit_failures = sorted(
            set(residual.get("service_units", []))
            | set(residual.get("enable_units", []))
            | set(residual.get("start_units", []))
        )
        non_unit_drift = any(
            (
                residual.get("crontab"),
                residual.get("enable_linger"),
            )
        )
        policy = state.prepared["unit_policy"]
        required_failures = [name for name in unit_failures if policy.get(name) != "optional"]
        if after.get("errors") or non_unit_drift or required_failures:
            raise DeployError("automation installer did not converge required automation")
        optional_failures = [name for name in unit_failures if policy.get(name) == "optional"]
        state.automation.update(
            {
                "optional_failures": optional_failures,
                "apply_exit": applied.returncode,
                "apply_errors": [str(value) for value in first.get("errors", [])],
                "result_sha256": _digest(first),
                "post_audit_sha256": _digest(after),
            }
        )
        self.store.save(state)
        if optional_failures:
            return {"status": "optional-failures", **state.automation}
        if applied.returncode != 0 or after.get("status") != "ok":
            raise DeployError("automation installer did not converge")
        return {
            "status": "ok",
            **state.automation,
        }

    def reconcile_automation(self, state: ReleaseState) -> dict[str, Any] | None:
        self._record_automation_mutations(state)
        result, summary = self._automation_invoke(state, "--audit")
        if result.returncode == 0 and summary.get("status") == "ok":
            return {"status": "ok", **state.automation, "reconciled": True}
        return self._optional_automation_result(state, summary, result.returncode)

    def _snapshot_name(self, state: ReleaseState, purpose: str) -> str:
        instant = datetime.fromisoformat(state.created_at.replace("Z", "+00:00"))
        if purpose == "rollback":
            instant += timedelta(microseconds=1)
        return f"market-{instant.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.duckdb"

    def reconcile_snapshot(self, state: ReleaseState, *, purpose: str) -> dict[str, Any] | None:
        directory = Path(state.database).parent / "snapshots"
        name = self._snapshot_name(state, purpose)
        snapshot = directory / name
        manifest_path = snapshot.with_suffix(".json")
        latest = directory / "market-latest.duckdb"
        present = (
            os.path.lexists(snapshot),
            os.path.lexists(manifest_path),
            os.path.lexists(latest),
        )
        if not any(present[:2]):
            return None
        if (
            not all(present)
            or not snapshot.is_file()
            or not manifest_path.is_file()
            or not latest.is_symlink()
        ):
            raise DeployError(f"{purpose} snapshot identity is incomplete")
        manifest = _regular_json(manifest_path)
        if (
            manifest.get("snapshot") != name
            or manifest.get("sha256") != _sha256(snapshot)
            or os.readlink(latest) != name
        ):
            raise DeployError(f"{purpose} snapshot identity is incomplete")
        return manifest

    def publish_snapshot(
        self, state: ReleaseState, held_locks: frozenset[str], *, purpose: str
    ) -> dict[str, Any]:
        reconciled = self.reconcile_snapshot(state, purpose=purpose)
        if reconciled is not None:
            return reconciled
        instant = datetime.fromisoformat(state.created_at.replace("Z", "+00:00"))
        if purpose == "rollback":
            instant += timedelta(microseconds=1)
        result = publish_snapshot.publish_snapshot(
            Path(state.repo_root),
            Path(state.database),
            held_locks=held_locks,
            now=instant,
        )
        if result.get("snapshot") != self._snapshot_name(state, purpose):
            raise DeployError(f"{purpose} snapshot was not transaction-addressed")
        return result

    def request_json(self, url: str) -> tuple[dict[str, Any], dict[str, str]]:
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                body = response.read()
                headers = {name.lower(): value for name, value in response.headers.items()}
        except (OSError, urllib.error.URLError) as exc:
            raise DeployError(f"semantic request failed for {url}: {exc}") from exc
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise DeployError(f"semantic request returned invalid JSON: {url}") from exc
        if not isinstance(payload, dict):
            raise DeployError(f"semantic request returned a non-object: {url}")
        return payload, headers

    def request_route(self, url: str, *, marker: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                body = response.read()
                status_code = response.status
                content_type = response.headers.get("Content-Type", "").lower()
        except (OSError, urllib.error.URLError) as exc:
            raise DeployError(f"route request failed for {url}: {exc}") from exc
        lowered = body.lower()
        if (
            status_code != 200
            or "text/html" not in content_type
            or b"<html" not in lowered
            or b"<body" not in lowered
            or b"</html>" not in lowered
            or marker.encode() not in lowered
        ):
            raise DeployError(f"route is not semantically readable: {url}")
        return {
            "status": status_code,
            "content_type": content_type,
            "body_sha256": hashlib.sha256(body).hexdigest(),
        }

    def _start_readers(self) -> None:
        self._systemctl(
            "start",
            "--no-block",
            "trading-engine-api.service",
            "trading-engine-ui.service",
        )

    def _wait_health(self) -> tuple[dict[str, Any], dict[str, str]]:
        last_error = "unavailable"
        for _attempt in range(60):
            try:
                health, headers = self.request_json(f"{self.api_url}/health")
                if health == {"ok": True, "status": "ok", "db_readable": True}:
                    if headers.get("x-data-source") == "snapshot":
                        raise DeployError("primary API check unexpectedly used a snapshot")
                    return health, headers
                last_error = f"unexpected payload: {health}"
            except DeployError as exc:
                last_error = str(exc)
            time.sleep(1)
        raise DeployError(f"API did not become semantically healthy: {last_error}")

    def _verify_runtime(self, state: ReleaseState, rolled_back: bool) -> dict[str, Any]:
        root = Path(state.repo_root)
        if rolled_back:
            for relative, prior in state.prior_runtimes.items():
                live = root / relative
                if prior["kind"] == "absent" and os.path.lexists(live):
                    raise DeployError(f"rollback did not restore absent runtime: {relative}")
                if prior["kind"] == "symlink" and (
                    not live.is_symlink() or os.readlink(live) != prior["target"]
                ):
                    raise DeployError(f"rollback did not restore runtime target: {relative}")
                if prior["kind"] == "directory" and not live.is_dir():
                    raise DeployError(f"rollback did not restore runtime directory: {relative}")
            python = root / ".venv/bin/python"
            if not python.is_file():
                raise DeployError("rollback did not restore an executable Python runtime")
            runtime = self._python_json(
                state,
                "import json,sys; print(json.dumps({'prefix':sys.prefix}))",
                python=python,
            )
            return {"status": "restored", "python_prefix": runtime["prefix"]}
        for relative, key in RUNTIME_LINKS.items():
            live = root / relative
            if (
                not live.is_symlink()
                or Path(os.path.realpath(live)) != Path(state.prepared[key]).resolve()
            ):
                raise DeployError(f"selected runtime identity changed: {relative}")
        code = "import json,sys; print(json.dumps({'prefix':sys.prefix}))"
        runtime = self._python_json(state, code)
        if (
            Path(runtime["prefix"]).resolve()
            != Path(state.prepared["python_environment"]).resolve()
        ):
            raise DeployError("running Python does not match the prepared environment")
        return {"status": "selected", "python_prefix": runtime["prefix"]}

    def _common_semantics(
        self, state: ReleaseState, meta: dict[str, Any], rolled_back: bool
    ) -> dict[str, Any]:
        keys = ("forward_review", "xs_forward_review", "e1_forward")
        if any(meta.get(key, {}).get("status") != "ACCUMULATING" for key in keys):
            raise DeployError("forward evidence is not accumulating")
        expected = state.inventory["registration"] if rolled_back else state.prepared["semantic"]
        registration_path = Path(state.repo_root) / "server/p15-registration.json"
        registration = json.loads(registration_path.read_text())
        observed_registration = {
            "registration_revision": registration["registration_revision"],
            "registration_source_commit": registration["code_identity"]["source_commit"],
            "registration_sha256": _sha256(registration_path),
        }
        for key, value in observed_registration.items():
            if value != expected[key]:
                raise DeployError(f"registered release identity mismatch: {key}")
        code = """
import json
from datetime import datetime, timezone
from pathlib import Path
from engine import forward_review, xs_forward_review
from engine.lib import db
from farm import experiment_runner
from server import agent_evaluation
with db.connect(Path(__import__('os').environ['TRADING_ENGINE_DB']), read_only=True) as con:
 agent_evaluation.validate_p15_evidence(con, generated_at=datetime.now(timezone.utc))
print(json.dumps({'versions': {'forward_review': forward_review.RUNTIME_CONTRACT_VERSION,
 'xs_forward_review': xs_forward_review.RUNTIME_CONTRACT_VERSION,
 'e1_forward': experiment_runner.RUNTIME_CONTRACT_VERSION}, 'evidence': 'valid'}))
"""
        python = Path(state.repo_root) / ".venv/bin/python" if rolled_back else None
        checked = self._python_json(state, code, python=python)
        observed = {key: meta[key].get("runtime_contract_version") for key in keys}
        expected_versions = (
            {
                key: state.inventory["predeploy_meta"][key]["runtime_contract_version"]
                for key in keys
            }
            if rolled_back
            else expected["runtime_versions"]
        )
        if observed != checked["versions"] or observed != expected_versions:
            raise DeployError("runtime contract versions do not match the semantic API")
        return {**observed_registration, "runtime_versions": observed, "evidence": "valid"}

    def _adapter_semantics(self, state: ReleaseState, rolled_back: bool) -> dict[str, Any]:
        if state.adapter_set == "none" or rolled_back:
            return {"adapter_set": state.adapter_set}
        code = """
import json
from pathlib import Path
from engine.lib import db
with db.connect(Path(__import__('os').environ['TRADING_ENGINE_DB']), read_only=True) as con:
 rows=con.execute("SELECT DISTINCT registration_revision FROM sim_book_breaks WHERE kind='cost_profile'").fetchall()
assert rows == [(14,)], rows
print(json.dumps({'cost_break_revisions': [row[0] for row in rows]}))
"""
        return {"adapter_set": state.adapter_set, **self._python_json(state, code)}

    def _forced_snapshot(self, state: ReleaseState, *, rolled_back: bool) -> dict[str, Any]:
        code = (
            "import duckdb,sys; c=duckdb.connect(sys.argv[1]); "
            "print('ready',flush=True); sys.stdin.read(1); c.close()"
        )
        python = (
            Path(state.repo_root) / ".venv/bin/python"
            if rolled_back
            else Path(state.prepared["python_environment"]) / "bin/python"
        )
        process = subprocess.Popen(
            [str(python), "-c", code, state.database],
            cwd=state.repo_root,
            env=self.runner.environment({"PYTHONPATH": state.repo_root}),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            if process.stdout is None or process.stdout.readline().strip() != "ready":
                raise DeployError("could not acquire the forced-snapshot writer")
            health, headers = self.request_json(f"{self.api_url}/health")
            if health.get("status") != "ok" or headers.get("x-data-source") != "snapshot":
                raise DeployError("API did not use the forced snapshot")
            return {"header": headers["x-data-source"]}
        finally:
            try:
                process.communicate(input="x", timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)

    def semantic_verify(self, state: ReleaseState, *, rolled_back: bool) -> dict[str, Any]:
        self._start_readers()
        health, _health_headers = self._wait_health()
        meta, _headers = self.request_json(f"{self.api_url}/meta")
        routes = {
            path: self.request_route(f"{self.ui_url}{path}", marker=marker)
            for path, marker in (
                ("/", "dashboard"),
                ("/positions", "position"),
                ("/league", "league"),
            )
        }
        runtime = self._verify_runtime(state, rolled_back)
        common = self._common_semantics(state, meta, rolled_back)
        adapter = self._adapter_semantics(state, rolled_back)
        forced = self._forced_snapshot(state, rolled_back=rolled_back)
        return {
            "health": health,
            "meta_sha256": _digest(meta),
            "routes": routes,
            "runtime": runtime,
            "common": common,
            "adapter": adapter,
            "forced_snapshot": forced,
        }

    def _restore_crontab(self, saved: dict[str, Any]) -> None:
        if saved["present"]:
            self.runner.run(
                [self.runner.host("crontab"), "-"], input_text=saved["content"], timeout=30
            )
        else:
            self.runner.run([self.runner.host("crontab"), "-r"], check=False, timeout=30)

    def release_producers(self, state: ReleaseState, *, include_autopush: bool) -> dict[str, Any]:
        units = state.inventory["units"]
        if not isinstance(units, dict) or any(UNIT_NAME.fullmatch(name) is None for name in units):
            raise DeployError("saved unit inventory is invalid")
        desired = {
            name
            for name, values in units.items()
            if values.get("ActiveState") in ACTIVE_STATES
            and (include_autopush or name not in AUTOPUSH_UNITS)
        }
        discovered = self._unit_names()
        unexpected = {
            name
            for name in discovered - set(units)
            if self._unit_properties(name).get("LoadState") != "not-found"
        }
        if unexpected:
            raise DeployError(
                f"refusing unit outside saved inventory: {', '.join(sorted(unexpected))}"
            )
        loaded = {
            name for name in units if self._unit_properties(name).get("LoadState") != "not-found"
        }
        unexpected_active = {
            name
            for name in loaded - desired
            if self._unit_properties(name).get("ActiveState") in ACTIVE_STATES
        }
        self._stop_units(unexpected_active)
        services = [
            name
            for name, values in units.items()
            if name.endswith(".service")
            and values.get("ActiveState") in ACTIVE_STATES
            and (include_autopush or name not in AUTOPUSH_UNITS)
            and name not in {"trading-engine-api.service", "trading-engine-ui.service"}
        ]
        timers = [
            name
            for name, values in units.items()
            if name.endswith(".timer")
            and values.get("ActiveState") in ACTIVE_STATES
            and (include_autopush or name not in AUTOPUSH_UNITS)
        ]
        if services:
            self._systemctl("start", "--no-block", *sorted(services))
        if timers:
            self._systemctl("start", *sorted(timers))
        self._restore_crontab(state.inventory["crontab"])
        for name in sorted(loaded):
            active = self._unit_properties(name).get("ActiveState") in ACTIVE_STATES
            if active != (name in desired):
                raise DeployError(f"saved activation state was not restored: {name}")
        if self._read_crontab() != state.inventory["crontab"]:
            raise DeployError("saved crontab was not restored exactly")
        return {
            "services_started": sorted(services),
            "timers_started": sorted(timers),
            "autopush_held": not include_autopush,
        }

    def capture_incident(self, state: ReleaseState) -> dict[str, Any]:
        self._check_workspace(state, copies=2)
        incident = self.store.directory / "incident"
        if incident.exists():
            reconciled = self.reconcile_incident(state)
            if reconciled is None:  # pragma: no cover - guarded by exists()
                raise DeployError("incident directory could not be reconciled")
            return reconciled
        temporary = self.store.directory / "incident.partial"
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(mode=0o700, exist_ok=True)
        database = Path(state.database)
        shutil.copy2(database, temporary / database.name)
        wal = database.with_name(f"{database.name}.wal")
        if wal.is_file():
            shutil.copy2(wal, temporary / wal.name)
        for name in ("data", "logs"):
            source = Path(state.repo_root) / name
            if source.is_dir():
                shutil.copytree(
                    source,
                    temporary / name,
                    ignore=shutil.ignore_patterns("*.lock"),
                    dirs_exist_ok=True,
                    symlinks=True,
                )
        snapshots = database.parent / "snapshots"
        if snapshots.is_dir():
            shutil.copytree(
                snapshots,
                temporary / "snapshot-identity",
                symlinks=True,
                dirs_exist_ok=True,
            )
        os.replace(temporary, incident)
        result = {
            "path": str(incident),
            "database_sha256": _sha256(incident / database.name),
            "tree": self._tree_manifest(incident),
        }
        _atomic_json(self.store.directory / "incident.json", result)
        return result

    def reconcile_incident(self, _state: ReleaseState) -> dict[str, Any] | None:
        incident = self.store.directory / "incident"
        if not incident.is_dir():
            return None
        databases = sorted(
            path for path in incident.iterdir() if path.is_file() and path.name.endswith(".duckdb")
        )
        if len(databases) != 1:
            raise DeployError("existing incident has no unique database image")
        result = {
            "path": str(incident),
            "database_sha256": _sha256(databases[0]),
            "tree": self._tree_manifest(incident),
        }
        manifest_path = self.store.directory / "incident.json"
        if manifest_path.exists() and _regular_json(manifest_path) != result:
            raise DeployError("existing incident identity changed")
        if not manifest_path.exists():
            _atomic_json(manifest_path, result)
        return result

    def restore_source(self, state: ReleaseState) -> dict[str, Any]:
        root = Path(state.repo_root)
        current = self._head(root)
        if current not in {state.approved_sha, state.original_sha}:
            raise DeployError("cannot roll back an unrecognized source SHA")
        if current != state.original_sha:
            if (root / "data").exists():
                self.runner.run([self._tool("git"), "checkout", "HEAD", "--", "data"], cwd=root)
            self.runner.run(
                [self._tool("git"), "checkout", "--detach", state.original_sha], cwd=root
            )
        return {"git_sha": self._head(root)}

    def restore_artifacts(self, state: ReleaseState) -> dict[str, Any]:
        root = Path(state.repo_root)
        saved_root = Path(state.inventory["artifacts"])
        expected = state.inventory.get("artifact_manifest")
        if not isinstance(expected, dict):
            expected = _regular_json(self.store.directory / "inventory/artifacts.json")
        self._verified_tree_manifest(saved_root, expected)
        current = self._artifact_manifest(root)
        extras = sorted(set(current["entries"]) - set(expected["entries"]))
        for relative in sorted(current["entries"], reverse=True):
            target = root / relative
            if target.is_file() or target.is_symlink():
                target.unlink()
        for name in ("data", "logs"):
            tree = root / name
            if tree.is_symlink() or (tree.exists() and not tree.is_dir()):
                raise DeployError(f"artifact root is unsafe: {name}")
            tree.mkdir(parents=True, exist_ok=True)
            for directory, _children, _files in os.walk(tree, topdown=False):
                path = Path(directory)
                if path != tree:
                    try:
                        path.rmdir()
                    except OSError:
                        pass
        for relative, identity in expected["entries"].items():
            source = saved_root / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if identity["kind"] == "symlink":
                os.symlink(identity["target"], target)
            else:
                shutil.copy2(source, target)
        if self._artifact_manifest(root) != expected:
            raise DeployError("restored artifact tree identity mismatch")
        return {"restored_sha256": expected["sha256"], "quarantined_extra_paths": extras}

    def verify_artifacts(self, state: ReleaseState) -> dict[str, Any]:
        expected = state.inventory.get("artifact_manifest")
        if not isinstance(expected, dict):
            expected = _regular_json(self.store.directory / "inventory/artifacts.json")
        if self._artifact_manifest(Path(state.repo_root)) != expected:
            raise DeployError("restored artifact tree identity changed")
        return {"sha256": expected["sha256"]}

    def restore_runtimes(self, state: ReleaseState) -> dict[str, Any]:
        self._hydrate_prior_runtimes(state)
        root = Path(state.repo_root)
        for relative, prior in state.prior_runtimes.items():
            live = root / relative
            prepared_key = RUNTIME_LINKS[relative]
            selected = (
                live.is_symlink()
                and Path(os.path.realpath(live)) == Path(state.prepared[prepared_key]).resolve()
            )
            if prior["kind"] == "absent":
                if selected:
                    live.unlink()
                elif os.path.lexists(live):
                    raise DeployError(f"selected runtime changed before rollback: {relative}")
            elif prior["kind"] == "symlink":
                if live.is_symlink() and os.readlink(live) == prior["target"]:
                    continue
                if not selected:
                    raise DeployError(f"selected runtime changed before rollback: {relative}")
                live.unlink()
                os.symlink(prior["target"], live)
            elif prior["kind"] == "directory":
                saved = Path(prior["saved"])
                if live.is_dir() and not live.is_symlink() and not saved.exists():
                    continue
                if not selected or not saved.is_dir():
                    raise DeployError(f"selected runtime changed before rollback: {relative}")
                live.unlink()
                os.replace(saved, live)
        return {"restored": sorted(state.prior_runtimes)}

    def restore_database(self, state: ReleaseState) -> dict[str, Any]:
        bundle = self.store.directory / "recovery"
        verified = backup_database.verify_backup(bundle)
        if verified["manifest_sha256"] != state.backup.get("manifest_sha256"):
            raise DeployError("recovery bundle no longer matches release state")
        manifest = _regular_json(bundle / backup_database.MANIFEST_FILENAME)
        if manifest.get("release_identity", {}).get("git_sha") != state.original_sha:
            raise DeployError("recovery bundle source identity changed")
        source = bundle / backup_database.DATABASE_FILENAME
        target = Path(state.database)
        temporary = target.with_name(f".{target.name}.restore-{secrets.token_hex(6)}")
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o600)
        if _sha256(temporary) != manifest["database"]["sha256"]:
            temporary.unlink(missing_ok=True)
            raise DeployError("restored database copy does not match the recovery bundle")
        target.with_name(f"{target.name}.wal").unlink(missing_ok=True)
        os.replace(temporary, target)
        for section in ("prospective_evidence", "operational_artifacts", "operational_controls"):
            for relative, record in manifest.get(section, {}).items():
                relative_path = Path(relative)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise DeployError("recovery bundle contains an unsafe evidence path")
                root = Path(state.repo_root).resolve()
                parent = root
                for part in relative_path.parts[:-1]:
                    parent /= part
                    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                        raise DeployError("recovery evidence destination is unsafe")
                parent.mkdir(parents=True, exist_ok=True)
                destination = root / relative_path
                if destination.is_symlink():
                    raise DeployError("recovery evidence destination is unsafe")
                shutil.copyfile(bundle / record["bundle_path"], destination)
                if _sha256(destination) != record["sha256"]:
                    raise DeployError(f"restored evidence identity mismatch: {relative}")
        snapshots = target.parent / "snapshots"
        quarantine = self.store.directory / "incident" / "quarantined-snapshots"
        if snapshots.exists() and not quarantine.exists():
            os.replace(snapshots, quarantine)
        return {"database_sha256": _sha256(target), "manifest_sha256": verified["manifest_sha256"]}

    def restore_units(self, state: ReleaseState) -> dict[str, Any]:
        unit_root = self.home / ".config/systemd/user"
        unit_root.mkdir(parents=True, exist_ok=True)
        installed = set(state.automation.get("installed_unit_files", []))
        if not installed <= set(state.inventory["unit_files"]):
            raise DeployError("automation recorded a unit outside saved inventory")
        for name in sorted(installed):
            saved = state.inventory["unit_files"][name]
            if UNIT_NAME.fullmatch(name) is None:
                raise DeployError("saved unit inventory is invalid")
            target = unit_root / name
            if target.exists() or target.is_symlink():
                if target.is_dir() and not target.is_symlink():
                    raise DeployError(f"installed unit became a directory: {name}")
                target.unlink()
            if saved["kind"] == "file":
                source = Path(saved["saved"])
                if _sha256(source) != saved["sha256"]:
                    raise DeployError(f"saved unit changed: {name}")
                shutil.copy2(source, target)
            elif saved["kind"] == "symlink":
                os.symlink(saved["target"], target)
        self._systemctl("daemon-reload")
        enablement = installed | set(state.automation.get("enablement_units", []))
        if not enablement <= set(state.inventory["units"]):
            raise DeployError("automation recorded enablement outside saved inventory")
        for name in sorted(enablement):
            values = state.inventory["units"][name]
            prior = values.get("UnitFileState")
            if (
                values.get("LoadState") == "not-found"
                and state.inventory["unit_files"][name]["kind"] == "absent"
            ):
                continue
            if prior == "enabled":
                self._systemctl("enable", name)
            elif prior == "disabled":
                self._systemctl("disable", name)
        return {"restored": sorted(installed), "enablement_restored": sorted(enablement)}


class ReleaseDeployment:
    def __init__(
        self,
        store: StateStore,
        operations: ReleaseOperations,
        *,
        fail_after: str | None = None,
    ):
        self.store = store
        self.operations = operations
        self.journal = ReceiptJournal(store)
        self.fail_after = fail_after

    def _fault(self, step: str) -> None:
        if self.fail_after == step:
            raise DeployError(f"injected failure after {step}")

    def _save_failure(self, state: ReleaseState, exc: BaseException) -> None:
        state.last_failure = {"at": _utc_now(), "phase": state.phase, "reason": str(exc)}
        self.store.save(state)

    def _load_prepared(self, *, recovery: bool = False) -> ReleaseState:
        state = self.store.load()
        expected_keys = {
            "source",
            "python_environment",
            "node_environment",
            "node_modules",
            "ui_build",
            "lock_sha256",
            "tools",
            "unit_policy",
            "semantic",
            "release_manifest_sha256",
            "release_tool_sha256",
            "versions",
            "migrations",
        }
        if set(state.prepared) != expected_keys:
            raise DeployError("prepared release has unknown or missing fields")
        policy = state.prepared["unit_policy"]
        if (
            not isinstance(policy, dict)
            or set(policy) != set(install_automation.UNIT_SOURCES)
            or any(value not in {"required", "optional"} for value in policy.values())
        ):
            raise DeployError("prepared unit policy is invalid")
        semantic = state.prepared["semantic"]
        if (
            not isinstance(semantic, dict)
            or set(semantic)
            != {
                "registration_revision",
                "registration_source_commit",
                "registration_sha256",
                "runtime_versions",
            }
            or type(semantic["registration_revision"]) is not int
            or not FULL_SHA.fullmatch(semantic["registration_source_commit"])
            or not SHA256.fullmatch(semantic["registration_sha256"])
            or set(semantic["runtime_versions"])
            != {"forward_review", "xs_forward_review", "e1_forward"}
            or any(type(value) is not int for value in semantic["runtime_versions"].values())
        ):
            raise DeployError("prepared semantic contract is invalid")
        locks = state.prepared["lock_sha256"]
        if not isinstance(locks, dict) or set(locks) != {"uv.lock", "ui/package-lock.json"}:
            raise DeployError("prepared dependency identity is incomplete")
        identities = [
            *locks.values(),
            state.prepared["release_manifest_sha256"],
            state.prepared["release_tool_sha256"],
        ]
        if any(
            not isinstance(value, str) or SHA256.fullmatch(value) is None for value in identities
        ):
            raise DeployError("prepared dependency or source identity is invalid")
        if state.prepared["migrations"] != [
            asdict(item) for item in ADAPTERS.get(state.adapter_set, ())
        ]:
            raise DeployError("unknown or changed migration registry")
        if recovery:
            self.operations.validate_recovery_tools(state)
            return state
        state_root = self.store.directory.resolve()
        path_keys = ("source", "python_environment", "node_environment", "node_modules", "ui_build")
        if any(not isinstance(state.prepared[key], str) for key in path_keys):
            raise DeployError("prepared environment path has the wrong type")
        for key in path_keys:
            path = Path(state.prepared[key])
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise DeployError(f"prepared environment is unavailable: {key}") from exc
            if state_root not in resolved.parents or not resolved.is_dir():
                raise DeployError(f"prepared environment is outside release state: {key}")
        python = Path(state.prepared["python_environment"]) / "bin/python"
        if not python.is_file() or not os.access(python, os.X_OK):
            raise DeployError("prepared dependency hash has no executable environment")
        self.operations.validate_prepared(state)
        return state

    def prepare(
        self,
        *,
        repo_root: Path,
        database: Path,
        approved_sha: str,
        adapter_set: str,
        d0: str | None,
        execute: bool,
    ) -> dict[str, Any]:
        preflight = self.operations.preflight_prepare(
            repo_root=repo_root,
            database=database,
            approved_sha=approved_sha,
            adapter_set=adapter_set,
            d0=d0,
        )
        actions = ["create-private-state", "prepare-source", "build-python", "build-ui", "smoke"]
        if not execute:
            return {"status": "planned", "phase": "prepare", "actions": actions, **preflight}
        now = _utc_now()
        state = ReleaseState(
            schema_version=STATE_SCHEMA_VERSION,
            transaction_id=secrets.token_hex(16),
            created_at=now,
            updated_at=now,
            phase="preparing",
            repo_root=str(repo_root.resolve()),
            database=str(database.resolve()),
            approved_sha=approved_sha,
            original_sha=preflight["original_sha"],
            source_branch=preflight["source_branch"],
            source_upstream=preflight["source_upstream"],
            adapter_set=adapter_set,
            d0=d0,
        )
        self.store.create(state)
        try:
            state.prepared = self.journal.run(
                "prepare-release",
                {"approved_sha": approved_sha, "preflight": preflight},
                lambda: self.operations.prepare_release(state, preflight),
            )
            state.phase = "prepared"
            state.last_failure = None
            self.store.save(state)
            return {"status": "prepared", "state": asdict(state)}
        except BaseException as exc:
            self._save_failure(state, exc)
            raise

    def _plan_existing(self, state: ReleaseState, phase: str, actions: list[str]) -> dict[str, Any]:
        return {
            "status": "planned",
            "phase": phase,
            "current_phase": state.phase,
            "approved_sha": state.approved_sha,
            "actions": actions,
            "migration_approval": state.migration_approval,
        }

    def apply(
        self,
        *,
        execute: bool,
        approve_plan: str | None,
        approve_optional: str | None = None,
    ) -> dict[str, Any]:
        state = self._load_prepared()
        actions = [
            "capture-inventory",
            "quiesce",
            "predeploy-adapter-check",
            "create-backup",
            "capture-artifacts",
            "source-switch",
            "runtime-switch",
            *[f"migration-{item.migration_id}" for item in ADAPTERS[state.adapter_set]],
            "install-automation",
            "requiesce",
            "publish-snapshot",
        ]
        if not execute:
            return self._plan_existing(state, "apply", actions)
        if state.phase not in {
            "prepared",
            "applying",
            "awaiting-migration-approval",
            "awaiting-optional-units",
        }:
            raise DeployError(f"apply is not allowed from phase {state.phase}")
        source_receipt = self.journal.read("source-switch")
        if source_receipt is None:
            expected = state.original_sha
        elif source_receipt.get("status") == "complete":
            expected = state.approved_sha
        else:
            current = self.operations._head(Path(state.repo_root))
            if current not in {state.original_sha, state.approved_sha}:
                raise DeployError("release checkout source changed during source-switch")
            expected = current
        self.operations.validate_state_source(state, expected)
        state.phase = "applying"
        self.store.save(state)
        try:
            state.inventory = self.journal.run(
                "capture-inventory",
                {"original_sha": state.original_sha},
                lambda: self.operations.capture_inventory(state),
            )
            self.store.save(state)
            if self.journal.completed("quiesce") is None:
                self.journal.run(
                    "quiesce",
                    {"inventory": _digest(state.inventory)},
                    lambda: self.operations.quiesce(state),
                )
            else:
                self.operations.quiesce(state)
            self.journal.run(
                "predeploy-adapter-check",
                {"adapter_set": state.adapter_set, "d0": state.d0},
                lambda: self.operations.predeploy_adapter_check(state),
            )
            state.backup = self.journal.run(
                "create-backup",
                {"original_sha": state.original_sha, "database": state.database},
                lambda: self.operations.create_backup(state),
            )
            self.store.save(state)
            with self.operations.producer_locks(state) as held_locks:
                state.inventory["artifact_manifest"] = self.journal.run(
                    "capture-artifacts",
                    {"original_sha": state.original_sha},
                    lambda: self.operations.capture_artifacts(state),
                    reconcile=lambda: self.operations.reconcile_artifacts(state),
                )
                self.store.save(state)
                self.journal.run(
                    "source-switch",
                    {"from": state.original_sha, "to": state.approved_sha},
                    lambda: self.operations.switch_source(state),
                    reconcile=lambda: self.operations.reconcile_source_switch(state),
                )
                self._fault("source-switch")
                state.prior_runtimes = self.journal.run(
                    "runtime-switch",
                    {"approved_sha": state.approved_sha, "locks": state.prepared["lock_sha256"]},
                    lambda: self.operations.switch_runtimes(state),
                    reconcile=lambda: self.operations.reconcile_runtime_switch(state),
                )
                self.store.save(state)
                self._fault("runtime-switch")
                for migration in ADAPTERS[state.adapter_set]:
                    step = f"migration-{migration.migration_id}"
                    plan = None
                    if migration.approval_required:
                        plan_step = f"plan-{migration.migration_id}"
                        plan = self.journal.run(
                            plan_step,
                            {"migration": asdict(migration), "approved_sha": state.approved_sha},
                            lambda migration=migration: self.operations.plan_migration(
                                state, migration
                            ),
                        )
                        digest = _digest({"migration": asdict(migration), "plan": plan})
                        state.migration_approval = {
                            "migration": migration.migration_id,
                            "plan_sha256": digest,
                            "plan": plan,
                        }
                        self.store.save(state)
                        if self.journal.completed(step) is None and approve_plan != digest:
                            state.phase = "awaiting-migration-approval"
                            self.store.save(state)
                            raise ApprovalRequired(digest, migration.migration_id, plan)
                    intent = self.operations.migration_intent(state, migration, plan)
                    self.journal.run(
                        step,
                        {
                            "migration": asdict(migration),
                            "approved_sha": state.approved_sha,
                            "plan": plan,
                            "intent": intent,
                        },
                        lambda migration=migration, plan=plan: self.operations.apply_migration(
                            state, migration, plan
                        ),
                        reconcile=lambda migration=migration, plan=plan, intent=intent: (
                            self.operations.reconcile_migration(state, migration, plan, intent)
                        ),
                    )
                    self._fault(step)
                state.automation = self.journal.run(
                    "install-automation",
                    {"approved_sha": state.approved_sha},
                    lambda: self.operations.install_automation(state),
                    reconcile=lambda: self.operations.reconcile_automation(state),
                )
                self.store.save(state)
                self._fault("install-automation")
                self.journal.run(
                    "requiesce",
                    {"approved_sha": state.approved_sha},
                    lambda: self.operations.quiesce(state),
                )
                optional_failures = state.automation.get("optional_failures", [])
                if optional_failures:
                    digest = _digest(
                        {
                            "approved_sha": state.approved_sha,
                            "policy": state.prepared["unit_policy"],
                            "optional_failures": optional_failures,
                            "automation": state.automation,
                        }
                    )
                    state.optional_unit_pause = {
                        "plan_sha256": digest,
                        "units": optional_failures,
                    }
                    self.store.save(state)
                    if approve_optional != digest:
                        state.phase = "awaiting-optional-units"
                        self.store.save(state)
                        raise OptionalUnitsPaused(digest, optional_failures)
                self.journal.run(
                    "publish-snapshot",
                    {"approved_sha": state.approved_sha, "database": state.database},
                    lambda: self.operations.publish_snapshot(state, held_locks, purpose="apply"),
                    reconcile=lambda: self.operations.reconcile_snapshot(state, purpose="apply"),
                )
                self._fault("publish-snapshot")
            state.phase = "applied"
            state.last_failure = None
            self.store.save(state)
            return {"status": "applied", "state": asdict(state)}
        except (ApprovalRequired, OptionalUnitsPaused):
            raise
        except BaseException as exc:
            self._save_failure(state, exc)
            raise

    def verify(self, *, execute: bool) -> dict[str, Any]:
        state = self._load_prepared()
        actions = ["semantic-verify", "release-producers"]
        if not execute:
            return self._plan_existing(state, "verify", actions)
        if state.phase not in {"applied", "verifying"}:
            raise DeployError(f"verify is not allowed from phase {state.phase}")
        self.operations.validate_state_source(state, state.approved_sha)
        state.phase = "verifying"
        self.store.save(state)
        try:
            self.journal.run(
                "semantic-verify",
                {"approved_sha": state.approved_sha, "backup": _digest(state.backup)},
                lambda: self.operations.semantic_verify(state, rolled_back=False),
            )
            self._fault("semantic-verify")
            self.journal.run(
                "release-producers",
                {"inventory": _digest(state.inventory), "include_autopush": True},
                lambda: self.operations.release_producers(state, include_autopush=True),
            )
            self._fault("release-producers")
            state.phase = "verified"
            state.last_failure = None
            self.store.save(state)
            return {"status": "verified", "state": asdict(state)}
        except BaseException as exc:
            self._save_failure(state, exc)
            raise

    def abort(self, *, execute: bool) -> dict[str, Any]:
        state = self._load_prepared(recovery=True)
        actions = ["restore-captured-activation"]
        if not execute:
            return self._plan_existing(state, "abort", actions)
        if state.phase == "aborted":
            return {"status": "aborted", "idempotent": True, "state": asdict(state)}
        if not state.inventory or self.journal.completed("capture-inventory") is None:
            raise DeployError("abort has no completed activation inventory")
        if self.journal.read("create-backup") is not None:
            raise DeployError("recovery bundle work started; use rollback instead of abort")
        mutating = [
            "source-switch",
            "runtime-switch",
            "install-automation",
            "publish-snapshot",
            *[f"migration-{item.migration_id}" for item in ADAPTERS[state.adapter_set]],
        ]
        if any(self.journal.read(step) is not None for step in mutating):
            raise DeployError("release mutation started; activation-only abort is unsafe")
        state.phase = "aborting"
        self.store.save(state)
        try:
            self.journal.run(
                "abort-release-producers",
                {"inventory": _digest(state.inventory)},
                lambda: self.operations.release_producers(state, include_autopush=True),
            )
            state.phase = "aborted"
            state.last_failure = None
            self.store.save(state)
            return {"status": "aborted", "state": asdict(state)}
        except BaseException as exc:
            self._save_failure(state, exc)
            raise

    def rollback(self, *, execute: bool) -> dict[str, Any]:
        state = self._load_prepared(recovery=True)
        actions = [
            "rollback-quiesce",
            "capture-incident",
            "restore-source",
            "restore-artifacts",
            "restore-runtimes",
            "restore-database",
            "verify-restored-artifacts",
            "restore-units",
            "rollback-snapshot",
            "rollback-semantic-verify",
            "rollback-release-producers",
        ]
        if not execute:
            return self._plan_existing(state, "rollback", actions)
        if not self.journal.completed("create-backup"):
            raise DeployError("rollback has no completed recovery bundle")
        if state.phase == "resumed":
            raise DeployError(f"rollback is not allowed from phase {state.phase}")
        if state.phase == "rolled-back":
            return {"status": "rolled-back", "idempotent": True, "state": asdict(state)}
        state.phase = "rolling-back"
        self.store.save(state)
        try:
            if self.journal.completed("rollback-quiesce") is None:
                self.journal.run(
                    "rollback-quiesce",
                    {"inventory": _digest(state.inventory)},
                    lambda: self.operations.quiesce(state),
                )
            else:
                self.operations.quiesce(state)
            with self.operations.producer_locks(state) as held_locks:
                self.journal.run(
                    "capture-incident",
                    {"approved_sha": state.approved_sha, "database": state.database},
                    lambda: self.operations.capture_incident(state),
                    reconcile=lambda: self.operations.reconcile_incident(state),
                )
                self.journal.run(
                    "restore-source",
                    {"original_sha": state.original_sha},
                    lambda: self.operations.restore_source(state),
                )
                self.journal.run(
                    "restore-artifacts",
                    {"artifact_manifest": state.inventory.get("artifact_manifest")},
                    lambda: self.operations.restore_artifacts(state),
                )
                self.journal.run(
                    "restore-runtimes",
                    {"prior": state.prior_runtimes},
                    lambda: self.operations.restore_runtimes(state),
                )
                self.journal.run(
                    "restore-database",
                    {"backup": _digest(state.backup)},
                    lambda: self.operations.restore_database(state),
                )
                self.journal.run(
                    "verify-restored-artifacts",
                    {"artifact_manifest": state.inventory.get("artifact_manifest")},
                    lambda: self.operations.verify_artifacts(state),
                )
                self.journal.run(
                    "restore-units",
                    {
                        "unit_files": state.inventory["unit_files"],
                        "automation": state.automation,
                    },
                    lambda: self.operations.restore_units(state),
                )
                self.journal.run(
                    "rollback-snapshot",
                    {"original_sha": state.original_sha, "database": state.database},
                    lambda: self.operations.publish_snapshot(state, held_locks, purpose="rollback"),
                    reconcile=lambda: self.operations.reconcile_snapshot(state, purpose="rollback"),
                )
            self.journal.run(
                "rollback-semantic-verify",
                {"original_sha": state.original_sha, "backup": _digest(state.backup)},
                lambda: self.operations.semantic_verify(state, rolled_back=True),
            )
            self.journal.run(
                "rollback-release-producers",
                {"inventory": _digest(state.inventory), "include_autopush": False},
                lambda: self.operations.release_producers(state, include_autopush=False),
            )
            state.phase = "rolled-back"
            state.last_failure = None
            self.store.save(state)
            return {"status": "rolled-back", "state": asdict(state)}
        except BaseException as exc:
            self._save_failure(state, exc)
            raise

    def resume(self, *, reconciled_sha: str, execute: bool) -> dict[str, Any]:
        state = self._load_prepared(recovery=True)
        if FULL_SHA.fullmatch(reconciled_sha) is None:
            raise DeployError("reconciled SHA must be 40 lowercase hexadecimal characters")
        actions = ["validate-reconciled-source", "resume-autopush"]
        if not execute:
            return self._plan_existing(state, "resume", actions)
        if state.phase not in {"rolled-back", "resuming"}:
            raise DeployError(f"resume is not allowed from phase {state.phase}")
        self.operations.validate_reconciled_source(state, reconciled_sha)
        state.phase = "resuming"
        self.store.save(state)
        try:
            self.journal.run(
                "resume-autopush",
                {"reconciled_sha": reconciled_sha, "inventory": _digest(state.inventory)},
                lambda: self.operations.release_producers(state, include_autopush=True),
            )
            state.phase = "resumed"
            state.last_failure = None
            self.store.save(state)
            return {"status": "resumed", "reconciled_sha": reconciled_sha, "state": asdict(state)}
        except BaseException as exc:
            self._save_failure(state, exc)
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--database", type=Path, default=Path("store/market.duckdb"))
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--host-command-dir", type=Path)
    parser.add_argument("--git-path", type=Path)
    parser.add_argument("--uv-path", type=Path)
    parser.add_argument("--node-path", type=Path)
    parser.add_argument("--npm-path", type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ui-url", default="http://127.0.0.1:3000")
    parser.add_argument(
        "--minimum-free-bytes",
        type=int,
        default=70 * 1024**3,
        help="free bytes that must remain after reserved database copies",
    )
    parser.add_argument(
        "--fail-after",
        help="test-only fault injection; requires RELEASE_DEPLOY_FAULT_INJECTION=1",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("state_dir", type=Path)
    prepare.add_argument("--approved-sha", required=True)
    prepare.add_argument("--adapter-set", choices=sorted(ADAPTERS), default="none")
    prepare.add_argument("--d0")
    prepare.add_argument("--execute", action="store_true")
    apply = subparsers.add_parser("apply")
    apply.add_argument("state_dir", type=Path)
    apply.add_argument("--approve-plan")
    apply.add_argument("--approve-optional")
    apply.add_argument("--execute", action="store_true")
    for name in ("verify", "abort", "rollback"):
        command = subparsers.add_parser(name)
        command.add_argument("state_dir", type=Path)
        command.add_argument("--execute", action="store_true")
    resume = subparsers.add_parser("resume")
    resume.add_argument("state_dir", type=Path)
    resume.add_argument("--reconciled-sha", required=True)
    resume.add_argument("--execute", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.minimum_free_bytes < 0:
        print(json.dumps({"status": "failed", "reason": "minimum free bytes must be non-negative"}))
        return 1
    if args.fail_after and os.environ.get("RELEASE_DEPLOY_FAULT_INJECTION") != "1":
        print(json.dumps({"status": "failed", "reason": "fault injection is not enabled"}))
        return 1
    store = StateStore(args.state_dir)
    runner = CommandRunner(args.host_command_dir)
    operations = ReleaseOperations(
        store,
        home=args.home,
        command_runner=runner,
        api_url=args.api_url,
        ui_url=args.ui_url,
        minimum_free_bytes=args.minimum_free_bytes,
        tool_paths={
            "git": args.git_path,
            "uv": args.uv_path,
            "node": args.node_path,
            "npm": args.npm_path,
        },
    )
    deployment = ReleaseDeployment(store, operations, fail_after=args.fail_after)
    repo_root = args.repo_root.resolve()
    database = args.database if args.database.is_absolute() else repo_root / args.database
    try:
        if args.command == "prepare":
            result = deployment.prepare(
                repo_root=repo_root,
                database=database,
                approved_sha=args.approved_sha,
                adapter_set=args.adapter_set,
                d0=args.d0,
                execute=args.execute,
            )
        elif args.command == "apply":
            result = deployment.apply(
                execute=args.execute,
                approve_plan=args.approve_plan,
                approve_optional=args.approve_optional,
            )
        elif args.command == "verify":
            result = deployment.verify(execute=args.execute)
        elif args.command == "abort":
            result = deployment.abort(execute=args.execute)
        elif args.command == "rollback":
            result = deployment.rollback(execute=args.execute)
        else:
            result = deployment.resume(reconciled_sha=args.reconciled_sha, execute=args.execute)
    except ApprovalRequired as exc:
        print(
            json.dumps(
                {
                    "status": "awaiting-migration-approval",
                    "migration": exc.migration,
                    "plan_sha256": exc.digest,
                    "plan": exc.plan,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except OptionalUnitsPaused as exc:
        print(
            json.dumps(
                {
                    "status": "awaiting-optional-units",
                    "units": exc.units,
                    "plan_sha256": exc.digest,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (DeployError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
