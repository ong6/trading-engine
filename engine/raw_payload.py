"""Durable zstd storage for sealed, content-addressed raw payloads."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from engine.free_sources import FreeSourceError

ZSTD_LEVEL = 6
ZSTD_BINARY = "zstd"


def compressed_path(path: Path) -> Path:
    """Return the zstd encoding path for one logical plain payload path."""
    path = Path(path)
    return path.with_name(f"{path.name}.zst")


def _codec() -> str:
    executable = shutil.which(ZSTD_BINARY)
    if executable is None:
        raise FreeSourceError("zstd executable is unavailable")
    return executable


def _run_zstd(arguments: list[str], body: bytes) -> bytes:
    try:
        result = subprocess.run(
            [_codec(), "-q", *arguments], input=body, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
    except OSError as exc:
        raise FreeSourceError("zstd codec could not be started") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[:200]
        suffix = f": {detail}" if detail else ""
        raise FreeSourceError(f"zstd codec rejected the payload{suffix}")
    return result.stdout


def encode(body: bytes, *, level: int = ZSTD_LEVEL) -> bytes:
    if not isinstance(body, bytes) or not body:
        raise FreeSourceError("sealed raw payload must be non-empty bytes")
    if not 1 <= level <= 19:
        raise FreeSourceError("zstd level must be between 1 and 19")
    return _run_zstd([f"-{level}", "-c"], body)


def decode(body: bytes) -> bytes:
    if not isinstance(body, bytes) or not body:
        raise FreeSourceError("compressed raw payload must be non-empty bytes")
    return _run_zstd(["-d", "-c"], body)


def _read_regular(path: Path, *, compressed: bool) -> bytes:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise FreeSourceError("sealed raw payload path is unsafe")
        body = path.read_bytes()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise FreeSourceError("sealed raw payload is unreadable") from exc
    return decode(body) if compressed else body


def _verify(body: bytes, *, expected_sha256: str | None, expected_size: int | None) -> bytes:
    if expected_size is not None and len(body) != expected_size:
        raise FreeSourceError("sealed raw payload length is invalid")
    if expected_sha256 is not None and hashlib.sha256(body).hexdigest() != expected_sha256:
        raise FreeSourceError("sealed raw payload hash is invalid")
    return body


def read(
    path: Path, *, expected_sha256: str | None = None, expected_size: int | None = None,
) -> bytes:
    """Read a logical payload from plain bytes, zstd bytes, or identical copies of both."""
    plain, compressed = Path(path), compressed_path(Path(path))
    versions: list[bytes] = []
    for candidate, is_compressed in ((plain, False), (compressed, True)):
        try:
            versions.append(_read_regular(candidate, compressed=is_compressed))
        except FileNotFoundError:
            pass
    if not versions:
        raise FreeSourceError("sealed raw payload is missing")
    if len(versions) == 2 and versions[0] != versions[1]:
        raise FreeSourceError("plain and compressed raw payloads conflict")
    return _verify(
        versions[0], expected_sha256=expected_sha256, expected_size=expected_size,
    )


def read_compressed(
    path: Path, *, expected_sha256: str | None = None, expected_size: int | None = None,
) -> bytes:
    """Read and verify only the compressed encoding of a logical payload."""
    try:
        body = _read_regular(compressed_path(Path(path)), compressed=True)
    except FileNotFoundError as exc:
        raise FreeSourceError("compressed raw payload is missing") from exc
    return _verify(body, expected_sha256=expected_sha256, expected_size=expected_size)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def seal(
    path: Path, body: bytes, *, expected_sha256: str | None = None,
    level: int = ZSTD_LEVEL, mode: int = 0o600,
) -> Path:
    """Atomically install and verify one zstd encoding, retaining any plain copy."""
    logical = Path(path)
    digest = hashlib.sha256(body).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise FreeSourceError("raw payload differs from its content identity")
    target = compressed_path(logical)
    logical.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    logical.parent.chmod(0o700)
    if logical.is_symlink() or target.is_symlink():
        raise FreeSourceError("sealed raw payload path is unsafe")
    if logical.exists() or target.exists():
        existing = read(logical, expected_sha256=digest, expected_size=len(body))
        if existing != body:
            raise FreeSourceError("raw payload differs from its content identity")
        if target.exists():
            return target
    encoded = encode(body, level=level)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=logical.parent, prefix=f".{target.name}.", delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        decoded = _read_regular(temporary, compressed=True)
        _verify(decoded, expected_sha256=digest, expected_size=len(body))
        os.replace(temporary, target)
        temporary = None
        fsync_directory(logical.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    read_compressed(logical, expected_sha256=digest, expected_size=len(body))
    return target
