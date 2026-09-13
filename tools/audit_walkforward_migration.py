#!/usr/bin/env python3
"""Fail-closed comparison of a saved walk-forward cohort and its replacements.

The baseline directory defines the artifacts in scope. Additional JSON files in
the replacement directory are reported but do not weaken comparison of that
baseline cohort; this permits canonical result directories to retain historical
artifacts that were not part of the active cohort snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from server.json_utils import MAX_JSON_FILE_BYTES, loads_object

_MISSING = object()
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class Difference:
    path: str
    before: Any
    after: Any


def _stable_metadata(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _directory_chain(path: Path, *, label: str):
    absolute = Path(os.path.abspath(path))
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise ValueError("secure cohort-directory traversal is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    stack = ExitStack()
    try:
        current = os.open(absolute.anchor, flags)
        stack.callback(os.close, current)
        identities = [_identity(os.fstat(current))]
        for part in absolute.parts[1:]:
            current = os.open(part, flags, dir_fd=current)
            stack.callback(os.close, current)
            identities.append(_identity(os.fstat(current)))
    except OSError as exc:
        stack.close()
        raise ValueError(f"{label} directory is unsafe: {path}") from exc
    return stack, current, tuple(identities)


@contextmanager
def _stable_directory(path: Path, *, label: str):
    """Retain one no-follow directory path and require its identity to stay visible."""
    stack, descriptor, identities = _directory_chain(path, label=label)
    with stack:
        yield descriptor
        retained = _identity(os.fstat(descriptor))
        visible_stack, visible, visible_identities = _directory_chain(path, label=label)
        with visible_stack:
            visible_identity = _identity(os.fstat(visible))
        if visible_identities != identities or visible_identity != retained:
            raise ValueError(f"{label} directory path changed during audit: {path}")


def _json_inventory(
    directory_fd: int, directory: Path, *, label: str
) -> dict[str, tuple[int, int, int, int, int, int]]:
    """Return stable metadata for every immediate JSON artifact in one cohort."""
    try:
        names = sorted(name for name in os.listdir(directory_fd) if name.endswith(".json"))
        inventory = {}
        for name in names:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"{label} JSON artifact is not regular: {directory / name}")
            inventory[name] = _stable_metadata(metadata)
        return inventory
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError(f"cannot inventory {label} directory {directory}: {exc}") from exc


def _read_bounded(descriptor: int) -> bytes:
    chunks = []
    remaining = MAX_JSON_FILE_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_stable_payload(
    descriptor: int,
    directory_fd: int,
    name: str,
    path: Path,
    expected_metadata: tuple[int, int, int, int, int, int],
) -> bytes:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"JSON artifact is not regular: {path}")
    payload = _read_bounded(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)
    confirmed = _read_bounded(descriptor)
    after = os.fstat(descriptor)
    visible = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if len(payload) > MAX_JSON_FILE_BYTES:
        raise ValueError(f"cannot read {path}: JSON file exceeds {MAX_JSON_FILE_BYTES} bytes")
    if (
        payload != confirmed
        or _stable_metadata(before) != expected_metadata
        or _stable_metadata(before) != _stable_metadata(after)
        or _stable_metadata(after) != _stable_metadata(visible)
    ):
        raise ValueError(f"cannot read {path}: JSON path changed while reading")
    return payload


def _read_object_at(
    directory_fd: int,
    name: str,
    path: Path,
    expected_metadata: tuple[int, int, int, int, int, int],
) -> dict[str, Any]:
    """Read one bounded JSON object through its retained cohort directory."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ValueError("secure cohort-artifact reads are unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | nofollow
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        try:
            payload = _read_stable_payload(
                descriptor, directory_fd, name, path, expected_metadata
            )
        finally:
            os.close(descriptor)
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    try:
        return loads_object(payload)
    except ValueError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def _differences(before: Any, after: Any, path: str = "$") -> Iterator[Difference]:
    if type(before) is not type(after):
        yield Difference(path, before, after)
        return
    if isinstance(before, dict):
        for key in sorted(before.keys() | after.keys()):
            child = f"{path}.{key}"
            if key not in before:
                yield Difference(child, _MISSING, after[key])
            elif key not in after:
                yield Difference(child, before[key], _MISSING)
            else:
                yield from _differences(before[key], after[key], child)
        return
    if isinstance(before, list):
        if len(before) != len(after):
            yield Difference(f"{path}.length", len(before), len(after))
        for index, (old_value, new_value) in enumerate(zip(before, after, strict=False)):
            yield from _differences(old_value, new_value, f"{path}[{index}]")
        return
    if before != after:
        yield Difference(path, before, after)


def _is_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def _is_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _valid_snapshot(value: Any) -> bool:
    sha256 = value.get("sha256") if isinstance(value, dict) else None
    tables = value.get("tables") if isinstance(value, dict) else None
    if (
        not isinstance(sha256, str)
        or _SHA256.fullmatch(sha256) is None
        or not isinstance(tables, dict)
    ):
        return False
    payload = json.dumps(tables, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest() == sha256


def _metadata_validation_differences(
    before: dict[str, Any], after: dict[str, Any]
) -> Iterator[Difference]:
    """Report malformed values in fields whose drift may otherwise be allowed."""
    validators = {
        "source_sha256": lambda value: (
            isinstance(value, str) and _SHA256.fullmatch(value) is not None
        ),
        "git_sha": lambda value: isinstance(value, str) and _GIT_SHA.fullmatch(value) is not None,
        "generated_utc": _is_timestamp,
        "runtime_s": _is_number,
        "scratch_s": _is_number,
        "data_snapshot": _valid_snapshot,
    }
    for key, validator in validators.items():
        old_value = before.get(key, _MISSING)
        new_value = after.get(key, _MISSING)
        if not validator(old_value) or not validator(new_value):
            yield Difference(f"$.{key}", old_value, new_value)

    old_folds = before.get("folds")
    new_folds = after.get("folds")
    if not isinstance(old_folds, list) or not isinstance(new_folds, list):
        return
    for index in range(max(len(old_folds), len(new_folds))):
        old_fold = old_folds[index] if index < len(old_folds) else _MISSING
        new_fold = new_folds[index] if index < len(new_folds) else _MISSING
        old_runtime = (
            old_fold.get("runtime_s", _MISSING) if isinstance(old_fold, dict) else _MISSING
        )
        new_runtime = (
            new_fold.get("runtime_s", _MISSING) if isinstance(new_fold, dict) else _MISSING
        )
        if not _is_number(old_runtime) or not _is_number(new_runtime):
            yield Difference(f"$.folds[{index}].runtime_s", old_runtime, new_runtime)


def _allowed(difference: Difference) -> bool:
    path = difference.path
    if path.startswith("$.data_snapshot."):
        return True
    if path == "$.source_sha256":
        return all(
            _SHA256.fullmatch(value) is not None
            for value in (difference.before, difference.after)
            if isinstance(value, str)
        ) and all(isinstance(value, str) for value in (difference.before, difference.after))
    if path == "$.git_sha":
        return all(
            _GIT_SHA.fullmatch(value) is not None
            for value in (difference.before, difference.after)
            if isinstance(value, str)
        ) and all(isinstance(value, str) for value in (difference.before, difference.after))
    if path == "$.generated_utc":
        return _is_timestamp(difference.before) and _is_timestamp(difference.after)
    if path in {"$.runtime_s", "$.scratch_s"} or (
        path.startswith("$.folds[") and path.endswith(".runtime_s")
    ):
        return _is_number(difference.before) and _is_number(difference.after)
    return False


def _render_value(value: Any) -> Any:
    return "<MISSING>" if value is _MISSING else value


def _audit_artifact(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    differences = list(_differences(before, after))
    unexpected = [difference for difference in differences if not _allowed(difference)]
    unexpected.extend(_metadata_validation_differences(before, after))
    unexpected = sorted(
        {difference.path: difference for difference in unexpected}.values(),
        key=lambda difference: difference.path,
    )
    return {
        "difference_count": len(differences),
        "unexpected": [
            {
                "path": difference.path,
                "before": _render_value(difference.before),
                "after": _render_value(difference.after),
            }
            for difference in unexpected
        ],
    }


def _audit_result(
    expected_names: set[str],
    replacement_names: set[str],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    missing = sorted(expected_names - replacement_names)
    unexpected_count = sum(len(item["unexpected"]) for item in artifacts.values())
    return {
        "status": "equivalent" if not missing and unexpected_count == 0 else "changed",
        "baseline_artifacts": len(expected_names),
        "compared_artifacts": len(artifacts),
        "missing_artifacts": missing,
        "additional_replacement_artifacts": sorted(replacement_names - expected_names),
        "unexpected_difference_count": unexpected_count,
        "artifacts": artifacts,
    }


def audit(before_dir: Path, after_dir: Path) -> dict[str, Any]:
    """Compare one stable baseline/replacement JSON cohort snapshot."""
    with _stable_directory(before_dir, label="baseline") as before_fd, _stable_directory(
        after_dir, label="replacement"
    ) as after_fd:
        before_inventory = _json_inventory(before_fd, before_dir, label="baseline")
        after_inventory = _json_inventory(after_fd, after_dir, label="replacement")
        if not before_inventory:
            raise ValueError(f"no baseline JSON artifacts in {before_dir}")

        expected_names = set(before_inventory)
        replacement_names = set(after_inventory)
        artifacts: dict[str, dict[str, Any]] = {}
        for name in sorted(expected_names & replacement_names):
            before = _read_object_at(
                before_fd, name, before_dir / name, before_inventory[name]
            )
            after = _read_object_at(
                after_fd, name, after_dir / name, after_inventory[name]
            )
            artifacts[name] = _audit_artifact(before, after)

        if _json_inventory(before_fd, before_dir, label="baseline") != before_inventory:
            raise ValueError(f"baseline JSON inventory changed during audit: {before_dir}")
        if _json_inventory(after_fd, after_dir, label="replacement") != after_inventory:
            raise ValueError(f"replacement JSON inventory changed during audit: {after_dir}")

    return _audit_result(expected_names, replacement_names, artifacts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare a saved walk-forward cohort with replacement artifacts."
    )
    parser.add_argument("before", type=Path, help="directory containing the saved baseline JSON")
    parser.add_argument("after", type=Path, help="directory containing replacement JSON")
    args = parser.parse_args(argv)

    try:
        result = audit(args.before, args.after)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "equivalent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
