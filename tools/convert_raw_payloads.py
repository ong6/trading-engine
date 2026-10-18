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

CANDIDATE = re.compile(r"^(?P<sha>[0-9a-f]{64})\.(?:json|raw)$")


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
                candidates.add(path)
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
    try:
        info = path.lstat()
    except OSError as exc:
        raise FreeSourceError(f"conversion candidate is unreadable: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise FreeSourceError(f"conversion candidate is unsafe: {path}")
    body = raw_payload.read(path, expected_sha256=match.group("sha"))
    if apply:
        target = raw_payload.seal(
            path, body, expected_sha256=match.group("sha"), mode=stat.S_IMODE(info.st_mode),
        )
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


def convert(
    roots: list[Path], *, base: Path, apply: bool = False,
    remove_originals: bool = False, manifest_path: Path | None = None,
) -> dict:
    if remove_originals and not apply:
        raise FreeSourceError("--remove-originals requires --apply")
    if apply and manifest_path is None:
        raise FreeSourceError("--apply requires --manifest")
    entries = [_entry(path, base=base, apply=apply) for path in _discover(roots)]
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
                path = base / entry["path"]
                raw_payload.read_compressed(
                    path, expected_sha256=entry["source_sha256"],
                    expected_size=entry["source_size"],
                )
                path.unlink()
                raw_payload.fsync_directory(path.parent)
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
