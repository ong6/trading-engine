#!/usr/bin/env python3
"""Convert hash-named JSON/raw payloads to zstd; dry-run unless --apply is given.

Applying is an orchestrator-run one-off on a quiesced raw store. The converter
holds the producer lock, checks other same-user process descriptors/maps, and
uses one no-follow parent descriptor for proof and unlink. Residual races from
an uncooperative hostile writer that ignores the producer lock are out of scope.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

from engine import raw_payload
from engine.free_sources import FreeSourceError
from engine.lib.resources import write_text_atomic

CANDIDATE = re.compile(r"^(?P<sha>[0-9a-f]{64})\.(?:json|raw)(?:\.zst)?$")


def _manifest_identity(payload: dict) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    return hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _discover(roots: list[Path]) -> list[Path]:
    candidates: set[Path] = set()
    for root in roots:
        if root.is_file() or root.is_symlink():
            paths = [root]
        elif root.is_dir():
            paths = root.rglob("*")
        else:
            raise FreeSourceError(f"conversion root does not exist: {root}")
        for path in paths:
            if CANDIDATE.fullmatch(path.name):
                candidates.add(path.with_suffix("") if path.suffix == ".zst" else path)
    return sorted(candidates)


def _relative(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError as exc:
        raise FreeSourceError("conversion candidate is outside --base") from exc


def _entry(path: Path, *, base: Path, apply: bool) -> dict:
    match = CANDIDATE.fullmatch(path.name)
    if match is None:
        raise FreeSourceError(f"conversion candidate is not hash-named: {path}")
    stored = path if path.exists() or path.is_symlink() else raw_payload.compressed_path(path)
    try:
        info = stored.lstat()
    except OSError as exc:
        raise FreeSourceError(f"conversion candidate is unreadable: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise FreeSourceError(f"conversion candidate is unsafe: {path}")
    body = raw_payload.read(path, expected_sha256=match.group("sha"))
    target = raw_payload.compressed_path(path)
    if apply and path.exists():
        target = raw_payload.seal(
            path, body, expected_sha256=match.group("sha"), mode=stat.S_IMODE(info.st_mode),
        )
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise FreeSourceError(f"compressed conversion candidate is unsafe: {target}")
        descriptor = os.open(
            target,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            compressed_size = os.fstat(descriptor).st_size
            raw_payload.read_compressed_descriptor(
                descriptor, expected_sha256=match.group("sha"), expected_size=len(body),
            )
            compressed_sha256 = raw_payload.descriptor_sha256(
                descriptor, expected_size=compressed_size,
            )
        finally:
            os.close(descriptor)
    else:
        compressed = raw_payload.encode(body)
        if raw_payload.decode(compressed) != body:
            raise FreeSourceError("dry-run zstd round trip changed the payload")
        compressed_size = len(compressed)
        compressed_sha256 = hashlib.sha256(compressed).hexdigest()
    return {
        "path": _relative(path, base),
        "source_sha256": match.group("sha"),
        "source_size": len(body),
        "compressed_path": _relative(raw_payload.compressed_path(path), base),
        "compressed_sha256": compressed_sha256,
        "compressed_size": compressed_size,
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
    }


def _load_manifest(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        if (set(payload) != {
                "schema_version", "zstd_level", "remove_originals", "entries",
                "manifest_sha256",
        } or payload["schema_version"] != 1
                or payload["zstd_level"] != raw_payload.ZSTD_LEVEL
                or not isinstance(payload["remove_originals"], bool)
                or not isinstance(payload["entries"], list)
                or payload["manifest_sha256"] != _manifest_identity(payload)):
            raise ValueError
        seen = set()
        for entry in payload["entries"]:
            required = {
                "path", "source_sha256", "source_size", "compressed_path",
                "compressed_sha256", "compressed_size", "mode",
            }
            entry_path = Path(entry.get("path", "")) if isinstance(entry, dict) else Path()
            identity = CANDIDATE.fullmatch(entry_path.name)
            if (not isinstance(entry, dict) or set(entry) != required
                    or not isinstance(entry["path"], str) or entry["path"] in seen
                    or entry_path.is_absolute() or ".." in entry_path.parts
                    or identity is None or entry_path.suffix not in {".json", ".raw"}
                    or identity.group("sha") != entry["source_sha256"]
                    or not re.fullmatch(r"[0-9a-f]{64}", entry["source_sha256"])
                    or not re.fullmatch(r"[0-9a-f]{64}", entry["compressed_sha256"])
                    or not isinstance(entry["source_size"], int) or entry["source_size"] < 0
                    or not isinstance(entry["compressed_size"], int)
                    or entry["compressed_size"] <= 0
                    or entry["compressed_path"] != f"{entry['path']}.zst"
                    or re.fullmatch(r"0[0-7]{3}", entry["mode"]) is None):
                raise ValueError
            seen.add(entry["path"])
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FreeSourceError("existing conversion manifest is invalid") from exc
    return payload


@contextmanager
def _opened_base(base: Path):
    absolute = base.absolute()
    descriptor = os.open(
        "/", os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        for component in absolute.parts[1:]:
            child = os.open(
                component,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
    except OSError as exc:
        os.close(descriptor)
        raise FreeSourceError("conversion base is unsafe or unreadable") from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise FreeSourceError("conversion base is unsafe")
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _opened_member_parent(base_descriptor: int, relative: str):
    path = Path(relative)
    descriptor = os.dup(base_descriptor)
    try:
        for component in path.parts[:-1]:
            child = os.open(
                component,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            if not stat.S_ISDIR(os.fstat(child).st_mode):
                os.close(child)
                raise FreeSourceError("conversion member parent is unsafe")
            os.close(descriptor)
            descriptor = child
    except OSError as exc:
        os.close(descriptor)
        raise FreeSourceError("conversion member parent is unsafe or unreadable") from exc
    try:
        yield descriptor, path.name
    finally:
        os.close(descriptor)


def _target_is_within(target: str, base: Path, producer_lock: Path) -> bool:
    suffix = " (deleted)"
    if target.endswith(suffix):
        target = target[:-len(suffix)]
    candidate = Path(target)
    if not candidate.is_absolute():
        return False
    resolved = candidate.resolve(strict=False)
    if resolved == producer_lock:
        return True
    try:
        resolved.relative_to(base)
        return True
    except ValueError:
        return False


def _other_process_holds_store(base: Path, producer_lock: Path) -> bool:
    current_pid = os.getpid()
    current_uid = os.getuid()
    for process in Path("/proc").iterdir():
        if not process.name.isdigit() or int(process.name) == current_pid:
            continue
        try:
            if process.stat().st_uid != current_uid:
                continue
            links = [process / "cwd", *(process / "fd").iterdir()]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        for link in links:
            try:
                target = os.readlink(link)
            except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
                continue
            if _target_is_within(target, base, producer_lock):
                return True
        try:
            mappings = (process / "maps").read_text(errors="replace").splitlines()
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        for line in mappings:
            fields = line.split(maxsplit=5)
            if len(fields) == 6 and _target_is_within(fields[5], base, producer_lock):
                return True
    return False


@contextmanager
def _quiesced_store(base: Path, producer_lock: Path):
    base = base.absolute()
    producer_lock = producer_lock.absolute()
    lock_descriptor = None
    try:
        lock_descriptor = os.open(
            producer_lock,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise FreeSourceError("producer lock is unsafe or unreadable") from exc
    if not stat.S_ISREG(os.fstat(lock_descriptor).st_mode):
        os.close(lock_descriptor)
        raise FreeSourceError("producer lock is unsafe")
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(lock_descriptor)
        raise FreeSourceError("producer lock is held") from exc
    try:
        with _opened_base(base) as base_descriptor:
            if _other_process_holds_store(base, producer_lock):
                raise FreeSourceError("raw store is held by another process")
            yield base_descriptor
    finally:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(lock_descriptor)


def _open_verified_compressed(entry: dict, parent: int, leaf: str) -> tuple[int, os.stat_result]:
    descriptor = None
    try:
        descriptor = os.open(
            f"{leaf}.zst",
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
        info = os.fstat(descriptor)
        body = raw_payload.read_compressed_descriptor(
            descriptor, expected_sha256=entry["source_sha256"],
            expected_size=entry["source_size"],
        )
        compressed_sha = raw_payload.descriptor_sha256(
            descriptor, expected_size=entry["compressed_size"],
        )
        if (len(body) != entry["source_size"]
                or compressed_sha != entry["compressed_sha256"]
                or stat.S_IMODE(info.st_mode) != int(entry["mode"], 8)):
            raise FreeSourceError("compressed payload differs from conversion manifest")
        return descriptor, info
    except FreeSourceError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise FreeSourceError("compressed payload differs from conversion manifest") from exc
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise FreeSourceError("manifest compressed payload is unsafe or unreadable") from exc


def _verify_manifest_entry_at(entry: dict, base_descriptor: int) -> None:
    with _opened_member_parent(base_descriptor, entry["path"]) as (parent, leaf):
        descriptor, _info = _open_verified_compressed(entry, parent, leaf)
        os.close(descriptor)


def _require_current_compressed(
    entry: dict, parent: int, leaf: str, descriptor: int,
) -> None:
    verified = os.fstat(descriptor)
    try:
        current = os.stat(f"{leaf}.zst", dir_fd=parent, follow_symlinks=False)
    except OSError as exc:
        raise FreeSourceError("compressed payload changed before original removal") from exc
    if ((verified.st_dev, verified.st_ino, verified.st_size)
            != (current.st_dev, current.st_ino, current.st_size)
            or not stat.S_ISREG(current.st_mode) or current.st_nlink < 1
            or verified.st_nlink < 1
            or stat.S_IMODE(current.st_mode) != int(entry["mode"], 8)):
        raise FreeSourceError("compressed payload changed before original removal")


def _verify_manifest_entry(
    entry: dict, base: Path, *, base_descriptor: int | None = None,
) -> None:
    if base_descriptor is not None:
        _verify_manifest_entry_at(entry, base_descriptor)
        return
    with _opened_base(base) as descriptor:
        _verify_manifest_entry_at(entry, descriptor)


def _remove_original_at(entry: dict, base_descriptor: int) -> None:
    with _opened_member_parent(base_descriptor, entry["path"]) as (parent, leaf):
        compressed, _compressed_info = _open_verified_compressed(entry, parent, leaf)
        original = None
        try:
            try:
                original = os.open(
                    leaf,
                    os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent,
                )
            except FileNotFoundError:
                _require_current_compressed(entry, parent, leaf, compressed)
                return
            except OSError as exc:
                raise FreeSourceError("conversion original is unsafe or unreadable") from exc
            info = os.fstat(original)
            raw_payload.read_plain_descriptor(
                original, expected_sha256=entry["source_sha256"],
                expected_size=entry["source_size"],
            )
            _require_current_compressed(entry, parent, leaf, compressed)
            current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            if ((info.st_dev, info.st_ino, info.st_size)
                    != (current.st_dev, current.st_ino, current.st_size)
                    or not stat.S_ISREG(current.st_mode)
                    or stat.S_IMODE(current.st_mode) != int(entry["mode"], 8)):
                raise FreeSourceError("conversion original changed before removal")
            os.unlink(leaf, dir_fd=parent)
            os.fsync(parent)
        finally:
            if original is not None:
                os.close(original)
            os.close(compressed)


def _remove_original(entry: dict, base: Path) -> None:
    with _opened_base(base) as descriptor:
        _remove_original_at(entry, descriptor)


def verify_manifest(manifest_path: Path, *, base: Path) -> dict:
    """Verify every compressed member named by a durable conversion manifest."""
    manifest = _load_manifest(manifest_path)
    if manifest is None:
        raise FreeSourceError("conversion manifest is missing")
    with _opened_base(base) as descriptor:
        for entry in manifest["entries"]:
            _verify_manifest_entry(entry, base, base_descriptor=descriptor)
    return manifest


def convert(
    roots: list[Path], *, base: Path, apply: bool = False,
    remove_originals: bool = False, manifest_path: Path | None = None,
    producer_lock: Path | None = None,
) -> dict:
    if remove_originals and not apply:
        raise FreeSourceError("--remove-originals requires --apply")
    if apply and manifest_path is None:
        raise FreeSourceError("--apply requires --manifest")
    if apply and producer_lock is None:
        raise FreeSourceError("--apply requires --producer-lock")
    existing = _load_manifest(manifest_path) if apply and manifest_path is not None else None
    if existing is not None and existing["remove_originals"] != remove_originals:
        raise FreeSourceError("existing conversion manifest removal policy differs")
    context = (_quiesced_store(base, producer_lock) if apply
               else _opened_base(base))
    with context as base_descriptor:
        entries_by_path = {
            entry["path"]: entry for entry in ([] if existing is None else existing["entries"])
        }
        for entry in entries_by_path.values():
            _verify_manifest_entry(entry, base, base_descriptor=base_descriptor)
        for candidate in _discover(roots):
            entry = _entry(candidate, base=base, apply=apply)
            prior = entries_by_path.get(entry["path"])
            if prior is not None and prior != entry:
                raise FreeSourceError("converted payload differs from existing manifest")
            entries_by_path[entry["path"]] = entry
        entries = [entries_by_path[key] for key in sorted(entries_by_path)]
        manifest = {
            "schema_version": 1,
            "zstd_level": raw_payload.ZSTD_LEVEL,
            "remove_originals": remove_originals,
            "entries": entries,
        }
        manifest["manifest_sha256"] = _manifest_identity(manifest)
        if apply:
            assert manifest_path is not None
            write_text_atomic(
                manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            )
            manifest_path.chmod(0o600)
            with manifest_path.open("rb") as manifest_file:
                os.fsync(manifest_file.fileno())
            raw_payload.fsync_directory(manifest_path.parent)
            persisted = json.loads(manifest_path.read_text())
            if (persisted != manifest
                    or _manifest_identity(persisted) != manifest["manifest_sha256"]):
                raise FreeSourceError("conversion manifest verification failed")
            if remove_originals:
                for entry in entries:
                    _remove_original_at(entry, base_descriptor)
        return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--base", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--remove-originals", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--producer-lock", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = convert(
            args.paths, base=args.base, apply=args.apply,
            remove_originals=args.remove_originals, manifest_path=args.manifest,
            producer_lock=args.producer_lock,
        )
    except (OSError, FreeSourceError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({
        "status": "converted" if args.apply else "dry-run",
        "files": len(manifest["entries"]),
        "source_bytes": sum(item["source_size"] for item in manifest["entries"]),
        "compressed_bytes": sum(item["compressed_size"] for item in manifest["entries"]),
        "manifest_sha256": manifest["manifest_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
