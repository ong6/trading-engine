from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from engine import raw_payload
from engine.free_sources import FreeSourceError
from tools import convert_raw_payloads


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
    with pytest.raises(FreeSourceError, match="zstd codec rejected"):
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

    applied = convert_raw_payloads.convert(
        [path.parent], base=tmp_path, apply=True, remove_originals=True,
        manifest_path=manifest_path,
    )
    assert not path.exists()
    assert raw_payload.read(path, expected_sha256=path.stem) == body
    assert json.loads(manifest_path.read_text()) == applied
    assert applied["manifest_sha256"] == convert_raw_payloads._manifest_identity(applied)
    assert before_mtime > 0


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


def test_codec_missing_fails_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(raw_payload.shutil, "which", lambda _name: None)
    with pytest.raises(FreeSourceError, match="unavailable"):
        raw_payload.encode(b"fixture")
