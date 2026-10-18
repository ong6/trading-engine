from __future__ import annotations

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
        manifest_path=manifest_path,
    )
    assert not path.exists()
    assert raw_payload.read(path, expected_sha256=path.stem) == body
    assert json.loads(manifest_path.read_text()) == applied
    assert applied["manifest_sha256"] == convert_raw_payloads._manifest_identity(applied)
    assert before_mtime > 0

    repeated = convert_raw_payloads.convert(
        [path.parent], base=tmp_path, apply=True, remove_originals=True,
        manifest_path=manifest_path,
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
            manifest_path=tmp_path / "manifest.json",
        )
    assert path.exists()
    assert raw_payload.read_compressed(path, expected_sha256=path.stem) == path.read_bytes()


def test_converter_resumes_after_crash_during_original_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    first = _plain(tmp_path, b"first")
    second = _plain(tmp_path, b"second")
    manifest_path = tmp_path / "manifest.json"
    original_remove = convert_raw_payloads._remove_original
    calls = 0

    def interrupt_second(entry, base):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected unlink interruption")
        original_remove(entry, base)

    monkeypatch.setattr(convert_raw_payloads, "_remove_original", interrupt_second)
    with pytest.raises(OSError, match="injected unlink"):
        convert_raw_payloads.convert(
            [first.parent], base=tmp_path, apply=True, remove_originals=True,
            manifest_path=manifest_path,
        )
    persisted = json.loads(manifest_path.read_text())
    assert len(persisted["entries"]) == 2
    assert sum(path.exists() for path in (first, second)) == 1

    monkeypatch.setattr(convert_raw_payloads, "_remove_original", original_remove)
    resumed = convert_raw_payloads.convert(
        [first.parent], base=tmp_path, apply=True, remove_originals=True,
        manifest_path=manifest_path,
    )
    assert resumed == persisted
    assert not first.exists() and not second.exists()


def test_converter_refuses_validly_hashed_manifest_that_differs_from_payload(tmp_path: Path):
    path = _plain(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    convert_raw_payloads.convert(
        [path], base=tmp_path, apply=True, manifest_path=manifest_path,
    )
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["compressed_size"] += 1
    manifest["manifest_sha256"] = convert_raw_payloads._manifest_identity(manifest)
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(FreeSourceError, match="differs from conversion manifest"):
        convert_raw_payloads.convert(
            [path], base=tmp_path, apply=True, manifest_path=manifest_path,
        )


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


@pytest.mark.parametrize("failure_point", ["encode", "file_fsync", "replace", "dir_fsync"])
def test_seal_atomic_failure_matrix_retains_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str,
):
    logical = _plain(tmp_path)
    body = logical.read_bytes()
    original_encode = raw_payload.encode
    original_fsync = raw_payload.os.fsync
    original_replace = raw_payload.os.replace
    original_dir_fsync = raw_payload.fsync_directory

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
    else:
        monkeypatch.setattr(
            raw_payload, "fsync_directory",
            lambda _path: (_ for _ in ()).throw(OSError("directory fsync crash")),
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
    assert raw_payload.read(
        logical, expected_sha256=logical.stem,
    ) == body


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
        manifest_path=manifest_path,
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
