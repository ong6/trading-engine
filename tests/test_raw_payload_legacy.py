"""Until the conversion flag is set, everything the branch writes stays readable by main.

Storage review finding 6: zstd-sealed payloads are unreadable by the previous code, so a
rollback after release would lose them. Writers seal the legacy plain encoding until
``tools.convert_raw_payloads --apply`` records the store flag.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from engine import raw_payload
from tools import convert_raw_payloads
from tools import free_sources as free_sources_tool

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import main_1fae615d_raw_reader as main_reader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 10, 23)
BODY = json.dumps({"status": "OK", "adjusted": True, "resultsCount": 0, "results": []}).encode()


def test_without_the_flag_seal_writes_the_plain_file_main_reads(tmp_path):
    sha = hashlib.sha256(BODY).hexdigest()

    sealed = raw_payload.seal(tmp_path / f"{sha}.json", BODY, expected_sha256=sha)

    assert sealed.name == f"{sha}.json"
    assert not list(tmp_path.glob("*.zst"))
    assert main_reader.hash_named_payload(tmp_path, sha) == BODY
    assert raw_payload.read(sealed, expected_sha256=sha) == BODY


def test_main_reads_a_massive_cache_the_branch_wrote_before_conversion(tmp_path):
    fetched_at = datetime(2026, 10, 23, 22, tzinfo=timezone.utc)

    free_sources_tool._cache_massive(tmp_path, DAY, BODY, fetched_at)

    assert main_reader.massive_cache(tmp_path, DAY) == (BODY, fetched_at)


def test_after_the_flag_writers_seal_zstd_and_the_branch_reads_both(
    tmp_path, raw_payload_encoding_flag,
):
    plain = tmp_path / "plain"
    free_sources_tool._cache_massive(plain, DAY, BODY, datetime(2026, 10, 23, tzinfo=timezone.utc))
    manifest = convert_raw_payloads.convert(
        [plain], base=tmp_path, apply=True, manifest_path=tmp_path / "manifest.json",
        producer_lock=tmp_path / ".producer.lock",
    )
    assert raw_payload.zstd_writes_enabled()
    assert json.loads(raw_payload_encoding_flag.read_text())["conversion_manifest_sha256"] == (
        manifest["manifest_sha256"]
    )
    later = tmp_path / "later"
    free_sources_tool._cache_massive(later, DAY, BODY, datetime(2026, 10, 24, tzinfo=timezone.utc))

    assert [path.suffix for path in (later / "massive" / DAY.isoformat()).glob("*.json*")
            if path.name != "receipt.json"] == [".zst"]
    for directory in (plain, later):
        assert free_sources_tool._massive_cache(directory, DAY)[0] == BODY


def test_only_the_conversion_tool_forces_zstd():
    forced = []
    for path in [*ROOT.glob("engine/**/*.py"), *ROOT.glob("tools/**/*.py"),
                 *ROOT.glob("server/**/*.py"), *ROOT.glob("farm/**/*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "seal"
                    and any(keyword.arg == "compressed" for keyword in node.keywords)):
                forced.append(path.relative_to(ROOT).as_posix())
    assert forced == ["tools/convert_raw_payloads.py"]


def test_an_invalid_flag_refuses_instead_of_guessing(raw_payload_encoding_flag, tmp_path):
    raw_payload_encoding_flag.write_text('{"encoding": "lz4"}')
    with pytest.raises(raw_payload.FreeSourceError, match="flag is invalid"):
        raw_payload.seal(tmp_path / "x.json", b"{}")
