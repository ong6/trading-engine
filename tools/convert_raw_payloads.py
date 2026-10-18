#!/usr/bin/env python3
"""Convert hash-named JSON/raw payloads to zstd; dry-run unless --apply is given."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
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
        compressed = target.read_bytes()
        raw_payload.read_compressed(
            path, expected_sha256=match.group("sha"), expected_size=len(body),
        )
    else:
        compressed = raw_payload.encode(body)
        if raw_payload.decode(compressed) != body:
            raise FreeSourceError("dry-run zstd round trip changed the payload")
    return {
        "path": _relative(path, base),
        "source_sha256": match.group("sha"),
        "source_size": len(body),
        "compressed_path": _relative(raw_payload.compressed_path(path), base),
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "compressed_size": len(compressed),
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
            if (not isinstance(entry, dict) or set(entry) != required
                    or not isinstance(entry["path"], str) or entry["path"] in seen
                    or entry_path.is_absolute() or ".." in entry_path.parts
                    or not CANDIDATE.fullmatch(Path(entry["path"]).name)
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


def _verify_manifest_entry(entry: dict, base: Path) -> None:
    logical = base / entry["path"]
    body = raw_payload.read_compressed(
        logical, expected_sha256=entry["source_sha256"],
        expected_size=entry["source_size"],
    )
    target = raw_payload.compressed_path(logical)
    if target.is_symlink() or not target.is_file():
        raise FreeSourceError("manifest compressed payload is unsafe")
    compressed = target.read_bytes()
    if (len(body) != entry["source_size"]
            or len(compressed) != entry["compressed_size"]
            or hashlib.sha256(compressed).hexdigest() != entry["compressed_sha256"]):
        raise FreeSourceError("compressed payload differs from conversion manifest")


def _remove_original(entry: dict, base: Path) -> None:
    path = base / entry["path"]
    _verify_manifest_entry(entry, base)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise FreeSourceError("conversion original is unsafe")
        path.unlink()
        raw_payload.fsync_directory(path.parent)


def convert(
    roots: list[Path], *, base: Path, apply: bool = False,
    remove_originals: bool = False, manifest_path: Path | None = None,
) -> dict:
    if remove_originals and not apply:
        raise FreeSourceError("--remove-originals requires --apply")
    if apply and manifest_path is None:
        raise FreeSourceError("--apply requires --manifest")
    existing = _load_manifest(manifest_path) if apply and manifest_path is not None else None
    if existing is not None and existing["remove_originals"] != remove_originals:
        raise FreeSourceError("existing conversion manifest removal policy differs")
    entries_by_path = {
        entry["path"]: entry for entry in ([] if existing is None else existing["entries"])
    }
    for entry in entries_by_path.values():
        _verify_manifest_entry(entry, base)
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
        if persisted != manifest or _manifest_identity(persisted) != manifest["manifest_sha256"]:
            raise FreeSourceError("conversion manifest verification failed")
        if remove_originals:
            for entry in entries:
                _remove_original(entry, base)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--base", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--remove-originals", action="store_true")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = convert(
            args.paths, base=args.base, apply=args.apply,
            remove_originals=args.remove_originals, manifest_path=args.manifest,
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
