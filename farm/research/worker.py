"""Feature-only strategy child for :mod:`farm.research.runner`."""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import resource
from pathlib import Path

from .canonical import canonical_bytes, file_sha256
from .mounts import ReadOnlyMount


def _callback(reference: dict):
    module = importlib.import_module(reference["module"])
    path = Path(module.__file__ or "").resolve()
    if not path.is_file() or file_sha256(path) != reference["sha256"]:
        raise ValueError("strategy callback module hash differs in child")
    function = getattr(module, reference["function"], None)
    if (not inspect.isfunction(function) or function.__closure__
            or "<locals>" in function.__qualname__):
        raise ValueError("strategy callback must be an importable function without a closure")
    return function


def execute(request_path: Path, output_path: Path) -> None:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    required = {"callback", "feature_root", "parameters", "seed", "mode", "memory_mb"}
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError("strategy worker request fields differ")
    memory_bytes = int(request["memory_mb"]) * 1024 * 1024
    if memory_bytes > 0:
        # Scientific runtimes map large shared libraries before the strategy starts. Limit
        # additional address space from this point instead of setting a nominal ceiling below
        # the already mapped interpreter, which would make the first small allocation abort.
        pages = int(Path("/proc/self/statm").read_text().split()[0])
        memory_bytes += pages * os.sysconf("SC_PAGE_SIZE")
        _, current_hard = resource.getrlimit(resource.RLIMIT_AS)
        hard = memory_bytes if current_hard == resource.RLIM_INFINITY else min(current_hard, memory_bytes)
        resource.setrlimit(resource.RLIMIT_AS, (min(memory_bytes, hard), hard))
    feature_root = Path(request["feature_root"]).resolve()
    cwd = Path.cwd().resolve()
    if not feature_root.is_relative_to(cwd):
        raise ValueError("feature mount must be staged inside the child working directory")
    callback = _callback(request["callback"])
    predictions = callback(
        ReadOnlyMount(feature_root),
        request["parameters"],
        request["seed"],
        request["mode"],
    )
    encoded = canonical_bytes(predictions, newline=True)
    descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    execute(args.request, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
