"""Sandboxed callback worker for :mod:`farm.research.runner`."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import importlib
import importlib.abc
import importlib.metadata
import inspect
import io
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

from .canonical import canonical_bytes, canonical_sha256, file_sha256
from .mounts import ReadOnlyMount

_DENIED_SYSCALLS = (
    "clone", "clone3", "fork", "vfork", "execve", "execveat",
    "socket", "socketpair", "connect", "bind", "listen", "accept", "accept4",
    "ptrace", "mount", "umount2", "open_by_handle_at",
)


def _limit(memory_mb: object) -> None:
    if type(memory_mb) is not int or memory_mb < 1:
        raise ValueError("worker memory limit must be a positive integer")
    limit = memory_mb * 1024 * 1024
    _, hard = resource.getrlimit(resource.RLIMIT_DATA)
    selected = limit if hard == resource.RLIM_INFINITY else min(hard, limit)
    resource.setrlimit(resource.RLIMIT_DATA, (selected, selected))


def _install_seccomp() -> None:
    try:
        library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    except OSError as exc:
        raise RuntimeError("libseccomp is required for research workers") from exc
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    # fixed parameters of the variadic call; untyped, a context above 4 GiB is truncated
    library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                         ctypes.c_uint]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_load.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("seccomp filter allocation failed")
    try:
        deny = 0x00050000 | errno.EPERM  # SCMP_ACT_ERRNO(EPERM)
        for name in _DENIED_SYSCALLS:
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and library.seccomp_rule_add(context, deny, number, 0) != 0:
                raise RuntimeError(f"seccomp rule failed: {name}")
        if library.seccomp_load(context) != 0:
            raise RuntimeError("seccomp filter load failed")
    finally:
        library.seccomp_release(context)


def _callback(reference: dict, package_sha256: str):
    refs = [
        {key: reference[key] for key in ("module", "source", "kind", "sha256")},
        *reference["dependencies"],
    ]
    identity = {
        "schema_version": 1,
        "entrypoint": {"module": reference["module"], "function": reference["function"]},
        "modules": sorted(refs, key=lambda item: item["module"]),
        "runtime": reference["runtime_identity"],
    }
    manifest_path = Path("/study/package/manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest != identity or canonical_sha256(identity) != package_sha256:
        raise ValueError("callback package identity differs")
    source_root = Path("/study/package/src").resolve()
    for item in refs:
        if item["kind"] == "runtime":
            observed = importlib.metadata.version(item["distribution"])
            if observed != item["version"]:
                raise ValueError(
                    f"callback dependency differs in sandbox: {item['module']} "
                    f"{observed} != {item['version']}"
                )
            continue
        else:
            module_path = source_root.joinpath(*item["module"].split("."))
            path = ((module_path / "__init__.py") if item["kind"] == "package"
                    else module_path.with_suffix(".py"))
        if not path.is_file() or file_sha256(path) != item["sha256"]:
            raise ValueError(f"callback dependency differs in sandbox: {item['module']}")
    module = importlib.import_module(reference["module"])
    function = getattr(module, reference["function"], None)
    if (not inspect.isfunction(function) or function.__closure__
            or "<locals>" in function.__qualname__):
        raise ValueError("callback must be an importable function without a closure")
    return function


def _runtime(reference: dict) -> None:
    runtime = reference["runtime_identity"]
    if platform.python_version() != runtime["python_version"]:
        raise ValueError("sandbox Python version differs")
    if file_sha256("/study/package/uv.lock") != runtime["uv_lock"]["sha256"]:
        raise ValueError("sandbox uv.lock differs")
    if any(importlib.metadata.version(item["name"]) != item["version"]
           for item in runtime["packages"]):
        raise ValueError("sandbox package versions differ")


class _DeclaredImportGuard(importlib.abc.MetaPathFinder):
    def __init__(self, reference: dict):
        modules = [reference["module"], *(item["module"] for item in reference["dependencies"])]
        self.allowed = {
            ".".join(module.split(".")[:index])
            for module in modules
            for index in range(1, len(module.split(".")) + 1)
        }
        self.allowed.add("farm.research")

    def find_spec(self, fullname, path=None, target=None):
        if (fullname.split(".", 1)[0] in sys.stdlib_module_names or fullname in sys.modules
                or any(fullname == name or fullname.startswith(name + ".")
                       for name in self.allowed)):
            return None
        raise ImportError(f"undeclared callback import: {fullname}")


def execute(request: dict) -> dict:
    common = {"callback", "package_sha256", "mode", "memory_mb"}
    required = {
        "strategy": common | {"parameters", "seed", "phase"},
        "recipe": common | {"parameters"},
    }
    if (not isinstance(request, dict) or request.get("mode") not in required
            or set(request) != required[request["mode"]]):
        raise ValueError("sandbox worker request fields differ")
    _limit(request["memory_mb"])
    _install_seccomp()
    sys.meta_path.insert(0, _DeclaredImportGuard(request["callback"]))
    _runtime(request["callback"])
    callback = _callback(request["callback"], request["package_sha256"])
    started_ns = time.monotonic_ns()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if request["mode"] == "strategy":
            payload = callback(
                ReadOnlyMount("/features"),
                request["parameters"],
                request["seed"],
                request["phase"],
            )
        else:
            payload = callback(ReadOnlyMount("/features"), request["parameters"])
    return {
        "payload": payload,
        "worker_pid": os.getpid(),
        "started_ns": started_ns,
        "finished_ns": time.monotonic_ns(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args(argv)
    if not args.stdio:
        parser.error("--stdio is required")
    request = json.loads(sys.stdin.buffer.read())
    sys.stdout.buffer.write(canonical_bytes(execute(request), newline=True))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
