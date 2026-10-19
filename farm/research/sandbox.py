"""Content-addressed callback packaging and OS-enforced research execution."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from engine.lib.resources import write_text_atomic

from .canonical import (
    canonical_bytes,
    canonical_sha256,
    distribution_sha256,
    file_sha256,
    fsync_tree,
)
from .spec import ContractError, ResolvedStudy


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class CallbackPackage:
    digest: str
    path: Path
    reference: Mapping[str, Any]


def _module_target(root: Path, reference: Mapping[str, Any]) -> Path:
    parts = reference["module"].split(".")
    if not parts or any(not part.isidentifier() for part in parts):
        raise ContractError(f"callback module name is invalid: {reference['module']!r}")
    path = root.joinpath(*parts)
    return path / "__init__.py" if reference["kind"] == "package" else path.with_suffix(".py")


def build_callback_package(
    resolved: ResolvedStudy,
    reference: Mapping[str, Any],
    root: str | Path,
) -> CallbackPackage:
    """Rehash and copy the declared callback closure into an immutable object."""
    refs = [
        {key: reference[key] for key in ("module", "source", "kind", "sha256")},
        *reference["dependencies"],
    ]
    if len({item["module"] for item in refs}) != len(refs):
        raise ContractError("callback closure contains duplicate modules")
    identity = {
        "schema_version": 1,
        "entrypoint": {"module": reference["module"], "function": reference["function"]},
        "modules": sorted(refs, key=lambda item: item["module"]),
    }
    digest = canonical_sha256(identity)
    objects = Path(root).resolve() / "callbacks" / "sha256"
    target = objects / digest
    if target.exists():
        manifest = json.loads((target / "manifest.json").read_text())
        if manifest != identity:
            raise SandboxError("callback package manifest differs")
        for item in refs:
            path = (resolved.callback_paths[item["module"]] if item["kind"] == "runtime"
                    else _module_target(target / "src", item))
            observed = (distribution_sha256(item["source"])
                        if item["kind"] == "runtime" else file_sha256(path))
            if observed != item["sha256"]:
                raise SandboxError("callback package bytes differ")
        return CallbackPackage(digest, target, reference)
    temporary = objects.parent / "builds" / f"{digest}.{uuid.uuid4().hex}"
    source_root = temporary / "src"
    source_root.mkdir(parents=True)
    try:
        for item in refs:
            source = resolved.callback_paths.get(item["module"])
            if item["kind"] == "runtime":
                if distribution_sha256(item["source"]) != item["sha256"]:
                    raise ContractError(
                        f"callback dependency changed after resolution: {item['module']}"
                    )
                distribution = importlib.metadata.distribution(item["source"])
                distribution_root = Path(distribution.locate_file("")).resolve()
                runtime_root = temporary / "runtime" / item["source"]
                for entry in distribution.files or ():
                    runtime_source = Path(distribution.locate_file(entry)).resolve()
                    if (not runtime_source.is_file()
                            or not runtime_source.is_relative_to(distribution_root)
                            or "__pycache__" in runtime_source.parts):
                        continue
                    runtime_target = runtime_root / runtime_source.relative_to(distribution_root)
                    runtime_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(runtime_source, runtime_target)
                continue
            if source is None or not source.is_file() or file_sha256(source) != item["sha256"]:
                raise ContractError(f"callback dependency changed after resolution: {item['module']}")
            destination = _module_target(source_root, item)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if file_sha256(destination) != item["sha256"]:
                raise SandboxError("callback copy differs")
        write_text_atomic(temporary / "manifest.json", canonical_bytes(identity, newline=True).decode())
        fsync_tree(temporary)
        for path in temporary.rglob("*"):
            path.chmod(0o555 if path.is_dir() else 0o444)
        objects.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(temporary, target)
        except OSError:
            if not target.exists():
                raise
            for path in temporary.rglob("*"):
                if path.is_dir():
                    path.chmod(0o755)
            temporary.chmod(0o755)
            shutil.rmtree(temporary)
        return build_callback_package(resolved, reference, root)
    except Exception:
        if temporary.exists():
            for path in temporary.rglob("*"):
                if path.is_dir():
                    path.chmod(0o755)
            temporary.chmod(0o755)
            shutil.rmtree(temporary)
        raise


def _build_harness(root: Path) -> Path:
    sources = ("worker.py", "canonical.py", "mounts.py")
    module_root = Path(__file__).resolve().parent
    identity = {name: file_sha256(module_root / name) for name in sources}
    digest = canonical_sha256(identity)
    target = root / "runtime" / "sha256" / digest
    if target.exists():
        return target
    target.mkdir(parents=True)
    package = target / "farm" / "research"
    package.mkdir(parents=True)
    for name in sources:
        shutil.copyfile(module_root / name, package / name)
    write_text_atomic(target / "manifest.json", canonical_bytes(identity, newline=True).decode())
    for path in target.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    return target


def prepare_sandbox_runtime(root: str | Path) -> Path:
    return _build_harness(Path(root).resolve())


def _bind(command: list[str], source: Path, destination: str) -> None:
    command.extend(("--ro-bind", str(source.resolve()), destination))


def run_sandboxed(
    package: CallbackPackage,
    request: Mapping[str, Any],
    *,
    feature_root: Path | None,
    label_root: Path | None,
    runtime_root: Path,
    timeout: float,
) -> dict[str, Any]:
    """Run one callback with no host filesystem, network, or process authority."""
    executable = shutil.which("bwrap")
    if executable is None:
        raise SandboxError("bubblewrap is required for outcome-isolated studies")
    harness = _build_harness(runtime_root)
    python_root = Path(sys.base_prefix).resolve()
    command = [
        executable,
        "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL",
        "--clearenv", "--tmpfs", "/", "--dir", "/runtime", "--dir", "/study",
        "--dev", "/dev", "--tmpfs", "/tmp", "--chdir", "/tmp",
    ]
    _bind(command, python_root, "/runtime/python")
    _bind(command, harness, "/runtime/harness")
    _bind(command, package.path, "/study/package")
    for system in (Path("/usr"), Path("/lib"), Path("/lib64")):
        if system.exists():
            _bind(command, system, system.as_posix())
    python_paths = ["/runtime/harness", "/study/package/src"]
    packaged_runtime = package.path / "runtime"
    if packaged_runtime.is_dir():
        python_paths.extend(
            f"/study/package/runtime/{path.name}"
            for path in sorted(packaged_runtime.iterdir()) if path.is_dir()
        )
    if feature_root is not None:
        _bind(command, feature_root, "/features")
    if label_root is not None:
        _bind(command, label_root, "/labels")
    command.extend((
        "--setenv", "PATH", "/runtime/python/bin:/usr/bin",
        "--setenv", "PYTHONPATH", os.pathsep.join(python_paths),
        "--setenv", "PYTHONNOUSERSITE", "1",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "OMP_NUM_THREADS", "1",
        "--setenv", "OPENBLAS_NUM_THREADS", "1",
        "--setenv", "MKL_NUM_THREADS", "1",
        "--", "/runtime/python/bin/python3", "-S", "-m", "farm.research.worker", "--stdio",
    ))
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = process.communicate(canonical_bytes(request, newline=True), timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    if process.returncode != 0:
        diagnostic = stderr.decode("utf-8", errors="replace")[-2_000:]
        raise SandboxError(f"sandboxed callback failed ({process.returncode}): {diagnostic}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SandboxError("sandboxed callback did not return canonical JSON") from exc
    if stdout != canonical_bytes(payload, newline=True):
        raise SandboxError("sandboxed callback output is not canonical JSON")
    if not isinstance(payload, dict) or set(payload) != {
        "payload", "worker_pid", "started_ns", "finished_ns",
    }:
        raise SandboxError("sandboxed callback envelope differs")
    return {**payload, "host_pid": process.pid}
