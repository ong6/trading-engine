from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from engine import raw_payload
from engine.free_sources import FreeSourceError
from tools import convert_raw_payloads
from tools import free_sources as free_capture

# These writers are tested on a converted store; tests/test_raw_payload_legacy.py covers
# the legacy plain encoding they use until the conversion flag is set.
pytestmark = pytest.mark.usefixtures("zstd_raw_payloads")


def _producer_lock(base: Path) -> Path:
    return base / ".producer.lock"


def _plain(tmp_path: Path, body: bytes = b'{"fixture":true}\n') -> Path:
    digest = hashlib.sha256(body).hexdigest()
    path = tmp_path / "raw" / f"{digest}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(body)
    path.chmod(0o640)
    return path


def test_reader_accepts_plain_zstd_and_identical_both(tmp_path: Path):
    path = _plain(tmp_path)
    body = path.read_bytes()
    digest = path.stem

    assert raw_payload.read(path, expected_sha256=digest) == body
    target = raw_payload.seal(path, body, expected_sha256=digest, mode=0o640)
    assert target.name.endswith(".json.zst")
    assert raw_payload.read(path, expected_sha256=digest) == body
    path.unlink()
    assert raw_payload.read(path, expected_sha256=digest) == body
    assert target.stat().st_mode & 0o777 == 0o640


def test_reader_refuses_conflict_truncation_and_wrong_identity(tmp_path: Path):
    path = _plain(tmp_path)
    body = path.read_bytes()
    target = raw_payload.seal(path, body)
    path.write_bytes(body + b"conflict")
    with pytest.raises(FreeSourceError, match="conflict"):
        raw_payload.read(path)

    path.unlink()
    target.write_bytes(target.read_bytes()[:5])
    with pytest.raises(FreeSourceError, match="zstd"):
        raw_payload.read(path)

    other = _plain(tmp_path, b"other")
    with pytest.raises(FreeSourceError, match="hash"):
        raw_payload.read(other, expected_sha256="0" * 64)


def test_seal_replace_failure_leaves_plain_and_no_partial_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    path = _plain(tmp_path)
    body = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(raw_payload.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        raw_payload.seal(path, body)
    assert path.read_bytes() == body
    assert not raw_payload.compressed_path(path).exists()
    assert not list(path.parent.glob(".*.zst.*"))


def test_converter_dry_run_apply_manifest_and_verified_removal(tmp_path: Path):
    path = _plain(tmp_path)
    body = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    manifest_path = tmp_path / "conversion-manifest.json"

    planned = convert_raw_payloads.convert([path.parent], base=tmp_path)
    assert path.exists() and not raw_payload.compressed_path(path).exists()
    assert planned["entries"][0]["path"] == f"raw/{path.name}"
    assert "mtime" not in json.dumps(planned)
    os.utime(path, ns=(before_mtime + 1_000_000, before_mtime + 1_000_000))
    assert convert_raw_payloads.convert([path.parent], base=tmp_path) == planned

    applied = convert_raw_payloads.convert(
        [path.parent], base=tmp_path, apply=True, remove_originals=True,
        manifest_path=manifest_path, producer_lock=_producer_lock(tmp_path),
    )
    assert not path.exists()
    assert raw_payload.read(path, expected_sha256=path.stem) == body
    assert json.loads(manifest_path.read_text()) == applied
    assert applied["manifest_sha256"] == convert_raw_payloads._manifest_identity(applied)
    assert before_mtime > 0

    repeated = convert_raw_payloads.convert(
        [path.parent], base=tmp_path, apply=True, remove_originals=True,
        manifest_path=manifest_path, producer_lock=_producer_lock(tmp_path),
    )
    assert repeated == applied
    assert json.loads(manifest_path.read_text()) == applied


def test_converter_does_not_remove_original_when_manifest_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    path = _plain(tmp_path)

    def fail_manifest(_path, _body):
        raise OSError("injected manifest failure")

    monkeypatch.setattr(convert_raw_payloads, "write_text_atomic", fail_manifest)
    with pytest.raises(OSError, match="injected"):
        convert_raw_payloads.convert(
            [path], base=tmp_path, apply=True, remove_originals=True,
            manifest_path=tmp_path / "manifest.json", producer_lock=_producer_lock(tmp_path),
        )
    assert path.exists()
    assert raw_payload.read_compressed(path, expected_sha256=path.stem) == path.read_bytes()


def test_converter_resumes_after_crash_during_original_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    first = _plain(tmp_path, b"first")
    second = _plain(tmp_path, b"second")
    manifest_path = tmp_path / "manifest.json"
    original_remove = convert_raw_payloads._remove_original_at
    calls = 0

    def interrupt_second(entry, base_descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected unlink interruption")
        original_remove(entry, base_descriptor)

    monkeypatch.setattr(convert_raw_payloads, "_remove_original_at", interrupt_second)
    with pytest.raises(OSError, match="injected unlink"):
        convert_raw_payloads.convert(
            [first.parent], base=tmp_path, apply=True, remove_originals=True,
            manifest_path=manifest_path, producer_lock=_producer_lock(tmp_path),
        )
    persisted = json.loads(manifest_path.read_text())
    assert len(persisted["entries"]) == 2
    assert sum(path.exists() for path in (first, second)) == 1

    monkeypatch.setattr(convert_raw_payloads, "_remove_original_at", original_remove)
    resumed = convert_raw_payloads.convert(
        [first.parent], base=tmp_path, apply=True, remove_originals=True,
        manifest_path=manifest_path, producer_lock=_producer_lock(tmp_path),
    )
    assert resumed == persisted
    assert not first.exists() and not second.exists()


def test_converter_refuses_validly_hashed_manifest_that_differs_from_payload(tmp_path: Path):
    path = _plain(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    convert_raw_payloads.convert(
        [path], base=tmp_path, apply=True, manifest_path=manifest_path,
        producer_lock=_producer_lock(tmp_path),
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["compressed_size"] += 1
    manifest["manifest_sha256"] = convert_raw_payloads._manifest_identity(manifest)
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(FreeSourceError, match="differs from conversion manifest"):
        convert_raw_payloads.convert(
            [path], base=tmp_path, apply=True, manifest_path=manifest_path,
            producer_lock=_producer_lock(tmp_path),
        )


def test_converter_repairs_existing_compressed_mode_before_removing_original(tmp_path: Path):
    path = _plain(tmp_path)
    path.chmod(0o600)
    body = path.read_bytes()
    target = raw_payload.seal(path, body, mode=0o600)
    target.chmod(0o666)
    manifest_path = tmp_path / "manifest.json"

    manifest = convert_raw_payloads.convert(
        [path], base=tmp_path, apply=True, remove_originals=True,
        manifest_path=manifest_path, producer_lock=_producer_lock(tmp_path),
    )
    assert not path.exists()
    assert target.stat().st_mode & 0o777 == 0o600
    assert manifest["entries"][0]["mode"] == "0600"
    assert convert_raw_payloads.verify_manifest(manifest_path, base=tmp_path) == manifest


def test_manifest_refuses_path_hash_that_differs_from_source_identity(tmp_path: Path):
    body = b"source-b"
    source_sha = hashlib.sha256(body).hexdigest()
    wrong_name_sha = hashlib.sha256(b"source-a").hexdigest()
    logical = tmp_path / f"{wrong_name_sha}.raw"
    target = raw_payload.seal(logical, body, expected_sha256=source_sha)
    compressed = target.read_bytes()
    manifest = {
        "schema_version": 1,
        "zstd_level": raw_payload.ZSTD_LEVEL,
        "remove_originals": False,
        "entries": [{
            "path": logical.name,
            "source_sha256": source_sha,
            "source_size": len(body),
            "compressed_path": target.name,
            "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
            "compressed_size": len(compressed),
            "mode": "0600",
        }],
    }
    manifest["manifest_sha256"] = convert_raw_payloads._manifest_identity(manifest)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(FreeSourceError, match="existing conversion manifest is invalid"):
        convert_raw_payloads.verify_manifest(manifest_path, base=tmp_path)


def test_manifest_parent_symlink_cannot_verify_or_remove_outside_base(tmp_path: Path):
    base = tmp_path / "checkpoint"
    member = base / "member"
    member.mkdir(parents=True)
    body = b"outside-original"
    digest = hashlib.sha256(body).hexdigest()
    logical = member / f"{digest}.json"
    logical.write_bytes(body)
    logical.chmod(0o600)
    manifest_path = base / "manifest.json"
    convert_raw_payloads.convert(
        [member], base=base, apply=True, manifest_path=manifest_path,
        producer_lock=_producer_lock(base),
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["remove_originals"] = True
    manifest["manifest_sha256"] = convert_raw_payloads._manifest_identity(manifest)
    manifest_path.write_text(json.dumps(manifest))

    outside = tmp_path / "outside-member"
    member.rename(outside)
    member.symlink_to(outside, target_is_directory=True)
    empty = base / "empty"
    empty.mkdir()
    with pytest.raises(FreeSourceError, match="parent is unsafe"):
        convert_raw_payloads.convert(
            [empty], base=base, apply=True, remove_originals=True,
            manifest_path=manifest_path, producer_lock=_producer_lock(base),
        )
    assert (outside / logical.name).read_bytes() == body
    assert raw_payload.compressed_path(outside / logical.name).exists()


def test_parent_swap_cannot_redirect_unlink_from_opened_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    base = tmp_path / "checkpoint"
    member = base / "member"
    member.mkdir(parents=True)
    body = b"parent-swap"
    digest = hashlib.sha256(body).hexdigest()
    logical = member / f"{digest}.raw"
    logical.write_bytes(body)
    logical.chmod(0o600)
    manifest_path = base / "manifest.json"
    convert_raw_payloads.convert(
        [member], base=base, apply=True, manifest_path=manifest_path,
        producer_lock=_producer_lock(base),
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["remove_originals"] = True
    manifest["manifest_sha256"] = convert_raw_payloads._manifest_identity(manifest)
    manifest_path.write_text(json.dumps(manifest))
    logical.unlink()

    replacement = tmp_path / "replacement-member"
    replacement.mkdir()
    replacement_original = replacement / logical.name
    replacement_original.write_bytes(body)
    replacement_original.chmod(0o600)
    verified_outside = tmp_path / "verified-outside"
    original_read = raw_payload.read_compressed_descriptor
    calls = 0

    def swap_after_removal_proof(*args, **kwargs):
        nonlocal calls
        result = original_read(*args, **kwargs)
        calls += 1
        if calls == 2:
            member.rename(verified_outside)
            replacement.rename(member)
        return result

    monkeypatch.setattr(raw_payload, "read_compressed_descriptor", swap_after_removal_proof)
    empty = base / "empty"
    empty.mkdir()
    convert_raw_payloads.convert(
        [empty], base=base, apply=True, remove_originals=True,
        manifest_path=manifest_path, producer_lock=_producer_lock(base),
    )
    assert (member / logical.name).read_bytes() == body
    assert raw_payload.compressed_path(verified_outside / logical.name).exists()


def test_compressed_leaf_removal_between_proof_and_unlink_retains_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    base = tmp_path / "checkpoint"
    member = base / "member"
    member.mkdir(parents=True)
    body = b"compressed-removal"
    digest = hashlib.sha256(body).hexdigest()
    logical = member / f"{digest}.raw"
    logical.write_bytes(body)
    logical.chmod(0o600)
    manifest_path = base / "manifest.json"
    convert_raw_payloads.convert(
        [member], base=base, apply=True, manifest_path=manifest_path,
        producer_lock=_producer_lock(base),
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["remove_originals"] = True
    manifest["manifest_sha256"] = convert_raw_payloads._manifest_identity(manifest)
    manifest_path.write_text(json.dumps(manifest))
    target = raw_payload.compressed_path(logical)
    original_read = raw_payload.read_plain_descriptor

    def remove_compressed_after_original_proof(*args, **kwargs):
        result = original_read(*args, **kwargs)
        target.unlink()
        return result

    monkeypatch.setattr(raw_payload, "read_plain_descriptor", remove_compressed_after_original_proof)
    empty = base / "empty"
    empty.mkdir()
    with pytest.raises(FreeSourceError, match="compressed payload changed"):
        convert_raw_payloads.convert(
            [empty], base=base, apply=True, remove_originals=True,
            manifest_path=manifest_path, producer_lock=_producer_lock(base),
        )
    assert logical.read_bytes() == body


def test_apply_refuses_held_producer_lock(tmp_path: Path):
    logical = _plain(tmp_path)
    lock_path = _producer_lock(tmp_path)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(FreeSourceError, match="producer lock is held"):
            convert_raw_payloads.convert(
                [logical], base=tmp_path, apply=True,
                manifest_path=tmp_path / "manifest.json", producer_lock=lock_path,
            )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    assert logical.exists()


def test_apply_refuses_symlinked_producer_lock(tmp_path: Path):
    logical = _plain(tmp_path)
    real_lock = tmp_path / "real.lock"
    real_lock.touch(mode=0o600)
    symlink = _producer_lock(tmp_path)
    symlink.symlink_to(real_lock)
    with pytest.raises(FreeSourceError, match="producer lock is unsafe"):
        convert_raw_payloads.convert(
            [logical], base=tmp_path, apply=True,
            manifest_path=tmp_path / "manifest.json", producer_lock=symlink,
        )
    assert logical.exists()


def test_apply_refuses_symlinked_base_component(tmp_path: Path):
    real_base = tmp_path / "real"
    real_base.mkdir()
    logical = _plain(real_base)
    linked_base = tmp_path / "linked"
    linked_base.symlink_to(real_base, target_is_directory=True)
    with pytest.raises(FreeSourceError, match="conversion base is unsafe"):
        convert_raw_payloads.convert(
            [logical], base=linked_base, apply=True,
            manifest_path=real_base / "manifest.json",
            producer_lock=real_base / ".producer.lock",
        )
    assert logical.exists()


def test_apply_refuses_other_process_holding_raw_store(tmp_path: Path):
    logical = _plain(tmp_path)
    root = Path(__file__).resolve().parents[1]
    process = subprocess.Popen(
        [sys.executable, "-c", (
            "import sys; handle=open(sys.argv[1], 'rb'); "
            "print('ready', flush=True); sys.stdin.readline()"
        ), str(logical)],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None and process.stdout.readline().strip() == "ready"
        with pytest.raises(FreeSourceError, match="raw store is held by another process"):
            convert_raw_payloads.convert(
                [logical], base=tmp_path, apply=True,
                manifest_path=tmp_path / "manifest.json",
                producer_lock=_producer_lock(tmp_path),
            )
    finally:
        if process.stdin is not None:
            process.stdin.write("\n")
            process.stdin.flush()
        process.communicate(timeout=5)
    assert process.returncode == 0
    assert logical.exists()


def test_codec_works_in_scheduler_minimal_path():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", (
            "from engine import raw_payload; "
            "body=b'scheduler'; "
            "assert raw_payload.decode(raw_payload.encode(body)) == body; "
            "print(raw_payload.codec_version_number())"
        )],
        cwd=root,
        env={**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
             "PYTHONPATH": str(root)},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) >= raw_payload.MIN_ZSTD_VERSION_NUMBER


def test_decoder_accepts_valid_unknown_size_streaming_frame():
    executable = shutil.which("zstd")
    assert executable is not None
    body = b"legacy-frame" * 100
    result = subprocess.run(
        [executable, "-q", "-6", "-c"], input=body,
        capture_output=True, check=False,
    )
    assert result.returncode == 0
    source = raw_payload.ctypes.create_string_buffer(result.stdout)
    declared = raw_payload._codec().ZSTD_getFrameContentSize(source, len(result.stdout))
    assert declared == raw_payload.ZSTD_CONTENTSIZE_UNKNOWN
    assert raw_payload.decode(result.stdout, max_output_size=len(body)) == body


def test_decoder_rejects_declared_size_above_receipt_before_output_allocation(
    monkeypatch: pytest.MonkeyPatch,
):
    encoded = raw_payload.encode(b"x" * 1024)
    original = raw_payload.ctypes.create_string_buffer
    allocations = []

    def record_allocation(value, size=None):
        allocations.append(len(value) if isinstance(value, bytes) else int(value))
        return original(value) if size is None else original(value, size)

    monkeypatch.setattr(raw_payload.ctypes, "create_string_buffer", record_allocation)
    with pytest.raises(FreeSourceError, match="exceeds the allowed decoded size"):
        raw_payload.decode(encoded, max_output_size=8)
    assert allocations == [min(raw_payload.FRAME_HEADER_BYTES, len(encoded))]


def test_compressed_file_size_is_bounded_before_stream_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    logical = tmp_path / f"{'a' * 64}.raw"
    raw_payload.compressed_path(logical).write_bytes(b"not-zstd!")
    monkeypatch.setattr(raw_payload, "MAX_COMPRESSED_BYTES", 8)
    with pytest.raises(FreeSourceError, match="compressed raw payload size is invalid"):
        raw_payload.read_compressed(logical)


def test_empty_payload_round_trips_and_converts(tmp_path: Path):
    body = b""
    digest = hashlib.sha256(body).hexdigest()
    logical = tmp_path / f"{digest}.raw"
    logical.write_bytes(body)
    target = raw_payload.seal(logical, body, expected_sha256=digest)
    assert raw_payload.read(logical, expected_sha256=digest, expected_size=0) == body
    assert target.stat().st_size > 0

    planned = convert_raw_payloads.convert([logical], base=tmp_path)
    assert planned["entries"][0]["source_size"] == 0


@pytest.mark.parametrize(
    "failure_point",
    ["encode", "file_fsync", "temp_chmod", "replace", "dir_fsync", "final_verify"],
)
def test_seal_atomic_failure_matrix_retains_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str,
):
    logical = _plain(tmp_path)
    body = logical.read_bytes()
    original_encode = raw_payload.encode
    original_fsync = raw_payload.os.fsync
    original_replace = raw_payload.os.replace
    original_dir_fsync = raw_payload.fsync_directory
    original_chmod = Path.chmod
    original_read_compressed = raw_payload.read_compressed

    if failure_point == "encode":
        monkeypatch.setattr(
            raw_payload, "encode",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("encode crash")),
        )
    elif failure_point == "file_fsync":
        monkeypatch.setattr(
            raw_payload.os, "fsync",
            lambda _fd: (_ for _ in ()).throw(OSError("file fsync crash")),
        )
    elif failure_point == "replace":
        monkeypatch.setattr(
            raw_payload.os, "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("replace crash")),
        )
    elif failure_point == "dir_fsync":
        monkeypatch.setattr(
            raw_payload, "fsync_directory",
            lambda _path: (_ for _ in ()).throw(OSError("directory fsync crash")),
        )
    elif failure_point == "temp_chmod":
        def fail_temp_chmod(chmod_path, mode):
            if chmod_path.name.startswith(".") and ".zst." in chmod_path.name:
                raise OSError("temporary chmod crash")
            return original_chmod(chmod_path, mode)

        monkeypatch.setattr(Path, "chmod", fail_temp_chmod)
    else:
        monkeypatch.setattr(
            raw_payload, "read_compressed",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("final verify crash")),
        )

    with pytest.raises(OSError, match="crash"):
        raw_payload.seal(logical, body)
    assert logical.read_bytes() == body
    assert not list(logical.parent.glob(".*.zst.*"))
    target = raw_payload.compressed_path(logical)
    if target.exists():
        assert raw_payload.read(logical, expected_sha256=logical.stem) == body

    monkeypatch.setattr(raw_payload, "encode", original_encode)
    monkeypatch.setattr(raw_payload.os, "fsync", original_fsync)
    monkeypatch.setattr(raw_payload.os, "replace", original_replace)
    monkeypatch.setattr(raw_payload, "fsync_directory", original_dir_fsync)
    monkeypatch.setattr(Path, "chmod", original_chmod)
    monkeypatch.setattr(raw_payload, "read_compressed", original_read_compressed)
    assert raw_payload.read(
        logical, expected_sha256=logical.stem,
    ) == body


def test_existing_target_permission_repair_failure_retains_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    logical = _plain(tmp_path)
    body = logical.read_bytes()
    target = raw_payload.seal(logical, body, mode=0o640)
    target.chmod(0o666)
    monkeypatch.setattr(
        raw_payload, "fsync_file",
        lambda _path: (_ for _ in ()).throw(OSError("permission fsync crash")),
    )
    with pytest.raises(OSError, match="permission fsync crash"):
        raw_payload.seal(logical, body, mode=0o640)
    assert logical.read_bytes() == body


@pytest.mark.parametrize("failure_point", ["chmod", "file_fsync", "directory_fsync"])
def test_manifest_durability_failure_retains_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str,
):
    logical = _plain(tmp_path)
    body = logical.read_bytes()
    raw_payload.seal(logical, body, mode=0o640)
    manifest_path = tmp_path / "manifest.json"
    original_chmod = Path.chmod
    original_fsync = convert_raw_payloads.os.fsync
    original_directory_fsync = raw_payload.fsync_directory

    if failure_point == "chmod":
        def fail_manifest_chmod(chmod_path, mode):
            if chmod_path == manifest_path:
                raise OSError("manifest chmod crash")
            return original_chmod(chmod_path, mode)

        monkeypatch.setattr(Path, "chmod", fail_manifest_chmod)
    elif failure_point == "file_fsync":
        monkeypatch.setattr(
            convert_raw_payloads.os, "fsync",
            lambda _fd: (_ for _ in ()).throw(OSError("manifest file fsync crash")),
        )
    else:
        monkeypatch.setattr(
            raw_payload, "fsync_directory",
            lambda _path: (_ for _ in ()).throw(OSError("manifest directory fsync crash")),
        )

    with pytest.raises(OSError, match="manifest .* crash"):
        convert_raw_payloads.convert(
            [logical], base=tmp_path, apply=True, remove_originals=True,
            manifest_path=manifest_path, producer_lock=_producer_lock(tmp_path),
        )
    assert logical.read_bytes() == body
    monkeypatch.setattr(Path, "chmod", original_chmod)
    monkeypatch.setattr(convert_raw_payloads.os, "fsync", original_fsync)
    monkeypatch.setattr(raw_payload, "fsync_directory", original_directory_fsync)


def test_fetched_checkpoint_restores_through_manifest_and_real_loader(tmp_path: Path):
    session_date = date(2026, 9, 29)
    timestamp = int(datetime(2026, 9, 29, tzinfo=timezone.utc).timestamp() * 1000)
    body = json.dumps({
        "status": "OK", "adjusted": True, "resultsCount": 1,
        "results": [{
            "T": "ABC", "t": timestamp, "o": 10, "h": 11,
            "l": 9, "c": 10.5, "v": 1000, "vw": 10.2,
        }],
    }, separators=(",", ":")).encode()
    digest = hashlib.sha256(body).hexdigest()
    checkpoint = tmp_path / "off-host-checkpoint"
    raw_dir = checkpoint / "massive" / session_date.isoformat()
    raw_dir.mkdir(parents=True)
    logical = raw_dir / f"{digest}.json"
    logical.write_bytes(body)
    logical.chmod(0o640)
    (raw_dir / "receipt.json").write_text(json.dumps({
        "date": session_date.isoformat(), "fetched_at": "2026-10-01T07:00:00+00:00",
        "raw_file": logical.name, "source_sha256": digest,
    }))
    manifest_path = checkpoint / "raw-conversion-manifest.json"
    converted = convert_raw_payloads.convert(
        [checkpoint / "massive"], base=checkpoint, apply=True, remove_originals=True,
        manifest_path=manifest_path, producer_lock=_producer_lock(checkpoint),
    )
    assert len(converted["entries"]) == 1 and not logical.exists()

    fetched = tmp_path / "fetched-checkpoint"
    shutil.copytree(checkpoint, fetched)
    verified = convert_raw_payloads.verify_manifest(
        fetched / manifest_path.name, base=fetched,
    )
    assert verified == converted
    restored = free_capture._massive_cache(fetched, session_date)
    assert restored is not None and restored[0] == body
    database = tmp_path / "restored.duckdb"
    loaded = free_capture._load_massive_response(
        database, session_date, restored[0], restored[1],
    )
    assert loaded["inserted"] == 1
    import duckdb
    con = duckdb.connect(str(database), read_only=True)
    try:
        assert con.execute(
            "SELECT ticker,source_sha256 FROM free_daily_bars"
        ).fetchall() == [("ABC", digest)]
    finally:
        con.close()
