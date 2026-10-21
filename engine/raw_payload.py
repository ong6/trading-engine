"""Durable zstd storage for sealed, content-addressed raw payloads."""
from __future__ import annotations

import ctypes
import hashlib
import io
import os
import stat
import tempfile
from functools import lru_cache
from pathlib import Path

from engine.free_sources import FreeSourceError

ZSTD_LEVEL = 6
ZSTD_LIBRARY = "libzstd.so.1"
MIN_ZSTD_VERSION_NUMBER = 10308
ZSTD_CONTENTSIZE_UNKNOWN = (1 << 64) - 1
ZSTD_CONTENTSIZE_ERROR = (1 << 64) - 2
MAX_DECODED_BYTES = 512_000_000
MAX_COMPRESSED_BYTES = 512_000_000
STREAM_INPUT_BYTES = 128 * 1024
FRAME_HEADER_BYTES = 18


class _ZSTDInBuffer(ctypes.Structure):
    _fields_ = [
        ("src", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


class _ZSTDOutBuffer(ctypes.Structure):
    _fields_ = [
        ("dst", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


def compressed_path(path: Path) -> Path:
    """Return the zstd encoding path for one logical plain payload path."""
    path = Path(path)
    return path.with_name(f"{path.name}.zst")


@lru_cache(maxsize=1)
def _codec():
    try:
        library = ctypes.CDLL(ZSTD_LIBRARY)
    except OSError as exc:
        raise FreeSourceError("pinned zstd runtime library is unavailable") from exc
    size_t = ctypes.c_size_t
    library.ZSTD_versionNumber.argtypes = []
    library.ZSTD_versionNumber.restype = ctypes.c_uint
    library.ZSTD_compressBound.argtypes = [size_t]
    library.ZSTD_compressBound.restype = size_t
    library.ZSTD_compress.argtypes = [
        ctypes.c_void_p, size_t, ctypes.c_void_p, size_t, ctypes.c_int,
    ]
    library.ZSTD_compress.restype = size_t
    library.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, size_t]
    library.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
    library.ZSTD_createDStream.argtypes = []
    library.ZSTD_createDStream.restype = ctypes.c_void_p
    library.ZSTD_freeDStream.argtypes = [ctypes.c_void_p]
    library.ZSTD_freeDStream.restype = size_t
    library.ZSTD_initDStream.argtypes = [ctypes.c_void_p]
    library.ZSTD_initDStream.restype = size_t
    library.ZSTD_DStreamOutSize.argtypes = []
    library.ZSTD_DStreamOutSize.restype = size_t
    library.ZSTD_decompressStream.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_ZSTDOutBuffer), ctypes.POINTER(_ZSTDInBuffer),
    ]
    library.ZSTD_decompressStream.restype = size_t
    library.ZSTD_isError.argtypes = [size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    library.ZSTD_getErrorName.argtypes = [size_t]
    library.ZSTD_getErrorName.restype = ctypes.c_char_p
    if library.ZSTD_versionNumber() < MIN_ZSTD_VERSION_NUMBER:
        raise FreeSourceError("pinned zstd runtime library is too old")
    return library


def codec_version_number() -> int:
    """Verify and return the scheduler-independent zstd runtime version."""
    return int(_codec().ZSTD_versionNumber())


def _checked_result(library, result: int) -> int:
    if library.ZSTD_isError(result):
        detail = library.ZSTD_getErrorName(result).decode("utf-8", errors="replace")
        raise FreeSourceError(f"zstd codec rejected the payload: {detail[:200]}")
    return int(result)


def encode(body: bytes, *, level: int = ZSTD_LEVEL) -> bytes:
    if not isinstance(body, bytes):
        raise FreeSourceError("sealed raw payload must be bytes")
    if not 1 <= level <= 19:
        raise FreeSourceError("zstd level must be between 1 and 19")
    library = _codec()
    source = ctypes.create_string_buffer(body)
    capacity = int(library.ZSTD_compressBound(len(body)))
    destination = ctypes.create_string_buffer(capacity)
    written = _checked_result(library, library.ZSTD_compress(
        destination, capacity, source, len(body), level,
    ))
    return destination.raw[:written]


def _decode_stream(source, *, compressed_size: int, max_output_size: int) -> bytes:
    if not 0 < compressed_size <= MAX_COMPRESSED_BYTES:
        raise FreeSourceError("compressed raw payload size is invalid")
    if (not isinstance(max_output_size, int) or isinstance(max_output_size, bool)
            or not 0 <= max_output_size <= MAX_DECODED_BYTES):
        raise FreeSourceError("zstd decoded-size limit is invalid")
    library = _codec()
    header = source.read(min(FRAME_HEADER_BYTES, compressed_size))
    source.seek(0)
    header_buffer = ctypes.create_string_buffer(header)
    declared = int(library.ZSTD_getFrameContentSize(header_buffer, len(header)))
    if declared == ZSTD_CONTENTSIZE_ERROR:
        raise FreeSourceError("zstd payload has an invalid frame header")
    if declared != ZSTD_CONTENTSIZE_UNKNOWN and declared > max_output_size:
        raise FreeSourceError("zstd payload exceeds the allowed decoded size")
    stream = library.ZSTD_createDStream()
    if not stream:
        raise FreeSourceError("zstd decoder allocation failed")
    try:
        _checked_result(library, library.ZSTD_initDStream(stream))
        output = bytearray()
        chunk_size = int(library.ZSTD_DStreamOutSize())
        remaining_hint = 1
        consumed = 0
        while consumed < compressed_size:
            chunk = source.read(min(STREAM_INPUT_BYTES, compressed_size - consumed))
            if not chunk:
                raise FreeSourceError("compressed raw payload changed while reading")
            consumed += len(chunk)
            input_storage = ctypes.create_string_buffer(chunk)
            input_buffer = _ZSTDInBuffer(
                ctypes.cast(input_storage, ctypes.c_void_p), len(chunk), 0,
            )
            while input_buffer.pos < input_buffer.size:
                allowed = max_output_size - len(output)
                capacity = min(chunk_size, allowed + 1)
                destination = ctypes.create_string_buffer(max(1, capacity))
                output_buffer = _ZSTDOutBuffer(
                    ctypes.cast(destination, ctypes.c_void_p), capacity, 0,
                )
                prior_input = input_buffer.pos
                remaining_hint = _checked_result(
                    library,
                    library.ZSTD_decompressStream(
                        stream, ctypes.byref(output_buffer), ctypes.byref(input_buffer),
                    ),
                )
                produced = int(output_buffer.pos)
                if produced > allowed:
                    raise FreeSourceError("zstd payload exceeds the allowed decoded size")
                output.extend(destination.raw[:produced])
                if input_buffer.pos == prior_input and produced == 0:
                    raise FreeSourceError("zstd decoder made no progress")
        if remaining_hint != 0:
            raise FreeSourceError("zstd payload is truncated")
        return bytes(output)
    finally:
        library.ZSTD_freeDStream(stream)


def decode(body: bytes, *, max_output_size: int = MAX_DECODED_BYTES) -> bytes:
    if not isinstance(body, bytes) or not body:
        raise FreeSourceError("compressed raw payload must be non-empty bytes")
    return _decode_stream(
        io.BytesIO(body), compressed_size=len(body), max_output_size=max_output_size,
    )


class _DescriptorReader:
    def __init__(self, descriptor: int):
        self.descriptor = descriptor
        self.offset = 0

    def read(self, size: int) -> bytes:
        chunk = os.pread(self.descriptor, size, self.offset)
        self.offset += len(chunk)
        return chunk

    def seek(self, offset: int) -> None:
        self.offset = offset


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_plain_descriptor(
    descriptor: int, *, expected_sha256: str | None = None,
    expected_size: int | None = None,
) -> bytes:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise FreeSourceError("sealed raw payload path is unsafe")
    limit = expected_size if expected_size is not None else MAX_DECODED_BYTES
    if before.st_size > limit:
        raise FreeSourceError("sealed raw payload length is invalid")
    reader = _DescriptorReader(descriptor)
    body = bytearray()
    while len(body) < before.st_size:
        chunk = reader.read(min(STREAM_INPUT_BYTES, before.st_size - len(body)))
        if not chunk:
            raise FreeSourceError("sealed raw payload changed while reading")
        body.extend(chunk)
    after = os.fstat(descriptor)
    if _file_identity(before) != _file_identity(after):
        raise FreeSourceError("sealed raw payload changed while reading")
    return _verify(bytes(body), expected_sha256=expected_sha256, expected_size=expected_size)


def read_compressed_descriptor(
    descriptor: int, *, expected_sha256: str | None = None,
    expected_size: int | None = None,
) -> bytes:
    before = os.fstat(descriptor)
    if (not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_COMPRESSED_BYTES):
        raise FreeSourceError("compressed raw payload size is invalid")
    body = _decode_stream(
        _DescriptorReader(descriptor), compressed_size=before.st_size,
        max_output_size=(expected_size if expected_size is not None else MAX_DECODED_BYTES),
    )
    after = os.fstat(descriptor)
    if _file_identity(before) != _file_identity(after):
        raise FreeSourceError("compressed raw payload changed while reading")
    return _verify(body, expected_sha256=expected_sha256, expected_size=expected_size)


def descriptor_sha256(descriptor: int, *, expected_size: int | None = None) -> str:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise FreeSourceError("sealed raw payload path is unsafe")
    if expected_size is not None and before.st_size != expected_size:
        raise FreeSourceError("sealed raw payload length is invalid")
    digest = hashlib.sha256()
    offset = 0
    while offset < before.st_size:
        chunk = os.pread(descriptor, min(STREAM_INPUT_BYTES, before.st_size - offset), offset)
        if not chunk:
            raise FreeSourceError("sealed raw payload changed while hashing")
        digest.update(chunk)
        offset += len(chunk)
    after = os.fstat(descriptor)
    if _file_identity(before) != _file_identity(after):
        raise FreeSourceError("sealed raw payload changed while hashing")
    return digest.hexdigest()


def _read_regular(
    path: Path, *, compressed: bool, expected_size: int | None = None,
) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        if compressed:
            return read_compressed_descriptor(
                descriptor, expected_size=expected_size,
            )
        return read_plain_descriptor(descriptor, expected_size=expected_size)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise FreeSourceError("sealed raw payload is unreadable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


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
            versions.append(_read_regular(
                candidate, compressed=is_compressed,
                expected_size=expected_size,
            ))
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
        body = _read_regular(
            compressed_path(Path(path)), compressed=True,
            expected_size=expected_size,
        )
    except FileNotFoundError as exc:
        raise FreeSourceError("compressed raw payload is missing") from exc
    return _verify(body, expected_sha256=expected_sha256, expected_size=expected_size)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise FreeSourceError("sealed raw payload path is unsafe")
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
            if stat.S_IMODE(target.lstat().st_mode) != mode:
                target.chmod(mode)
                fsync_file(target)
                fsync_directory(target.parent)
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
        decoded = _read_regular(
            temporary, compressed=True, expected_size=len(body),
        )
        _verify(decoded, expected_sha256=digest, expected_size=len(body))
        os.replace(temporary, target)
        temporary = None
        fsync_directory(logical.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    read_compressed(logical, expected_sha256=digest, expected_size=len(body))
    if stat.S_IMODE(target.stat().st_mode) != mode:
        raise FreeSourceError("sealed raw payload permissions are invalid")
    return target
