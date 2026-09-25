"""Tests for the read-only Friday evidence postflight."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

import pytest

from server import friday_postflight, read_model_utils
from tools import verify_friday_postflight


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.read_size = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, size: int) -> bytes:
        self.read_size = size
        return self.payload[:size]


def _payload() -> dict:
    miners = {}
    for job_id, kind in enumerate(("intraday", "signals", "earnings", "fundamentals"), start=476):
        miners[kind] = {
            "status": "current",
            "job_id": job_id,
            "job_state": "done",
            "job_updated_at": "2026-09-12T00:30:00",
            "evidence_at": "2026-09-12T00:29:59+00:00",
        }
    miners["tradingview_history"] = {
        "status": "current",
        "job_id": 480,
        "job_state": "done",
        "job_updated_at": "2026-09-12T03:42:00",
        "evidence_at": "2026-09-12T03:41:59+00:00",
    }
    return {
        "nightly": {
            "status": "ok",
            "started_at": "2026-09-11T22:30:01Z",
            "finished_at": "2026-09-12T00:30:01Z",
        },
        "nightly_evidence": {"status": "current", "as_of": "2026-09-11"},
        "miner_evidence": {
            "status": "current",
            "current": 5,
            "expected": 5,
            "miners": miners,
        },
    }


def _deeply_nested_json() -> bytes:
    depth = max(10_000, sys.getrecursionlimit() * 10)
    return b'{"nested":' + (b"[" * depth) + b"0" + (b"]" * depth) + b"}"


def test_verify_accepts_real_same_run_friday_evidence():
    result = verify_friday_postflight.verify(_payload(), date(2026, 9, 11))

    assert result["status"] == "current"
    assert result["expected_date"] == "2026-09-11"
    assert result["market_date"] == "2026-09-11"
    assert result["miner_job_ids"]["fundamentals"] == 479
    assert "tradingview_history" not in result["miner_job_ids"]


def test_verify_ignores_independently_running_non_nightly_miner():
    payload = _payload()
    payload["miner_evidence"].update(status="updating", current=4)
    payload["miner_evidence"]["miners"]["tradingview_history"].update(
        status="running", job_state="running", evidence_at=None
    )

    result = verify_friday_postflight.verify(payload, date(2026, 9, 11))

    assert set(result["miner_job_ids"]) == friday_postflight.EXPECTED_MINERS


def test_receipt_validation_rejects_unsafe_miner_job_identifier():
    job_ids = {kind: index for index, kind in enumerate(friday_postflight.EXPECTED_MINERS, 1)}
    job_ids["fundamentals"] = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1

    with pytest.raises(ValueError, match="miner_job_ids are invalid"):
        friday_postflight._positive_job_ids(job_ids)


def test_verify_rejects_a_non_friday_expected_date():
    with pytest.raises(
        verify_friday_postflight.PostflightError, match="expected date must be a Friday"
    ):
        verify_friday_postflight.verify(_payload(), date(2026, 9, 10))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["nightly"].update(status="running"), "nightly status"),
        (
            lambda value: value["nightly"].update(started_at="2026-09-10T22:30:01Z"),
            "expected 2026-09-11",
        ),
        (
            lambda value: value["nightly_evidence"].update(as_of="2026-09-12"),
            "market date 2026-09-12 is after Friday",
        ),
        (
            lambda value: value["miner_evidence"]["miners"]["intraday"].update(
                status="issues"
            ),
            "intraday evidence is not current",
        ),
        (
            lambda value: value["miner_evidence"]["miners"]["fundamentals"].update(
                evidence_at="2026-09-05T00:33:22+00:00"
            ),
            "fundamentals evidence falls outside",
        ),
        (
            lambda value: value["miner_evidence"]["miners"]["fundamentals"].update(
                evidence_at="2026-09-12T00:31:00+00:00"
            ),
            "fundamentals evidence falls outside",
        ),
        (
            lambda value: value["miner_evidence"]["miners"]["fundamentals"].update(
                job_id=value["miner_evidence"]["miners"]["earnings"]["job_id"]
            ),
            "miner job IDs are not unique",
        ),
    ],
)
def test_verify_fails_closed_for_noncurrent_evidence(mutation, message):
    payload = _payload()
    mutation(payload)

    with pytest.raises(verify_friday_postflight.PostflightError, match=message):
        verify_friday_postflight.verify(payload, date(2026, 9, 11))


def test_most_recent_friday_uses_utc_date():
    assert verify_friday_postflight.most_recent_friday(
        datetime(2026, 9, 12, 3, 30, tzinfo=timezone.utc)
    ) == date(2026, 9, 11)


def test_verify_allows_prior_operational_date_on_a_friday_market_holiday():
    payload = _payload()
    payload["nightly_evidence"]["as_of"] = "2026-09-10"

    result = verify_friday_postflight.verify(payload, date(2026, 9, 11))

    assert result["market_date"] == "2026-09-10"


def test_fetch_meta_reads_through_limit_and_accepts_exact_limit(monkeypatch):
    padding = verify_friday_postflight.MAX_META_RESPONSE_BYTES - len('{"padding":""}')
    response = _Response(json.dumps({"padding": "x" * padding}, separators=(",", ":")).encode())
    assert len(response.payload) == verify_friday_postflight.MAX_META_RESPONSE_BYTES
    monkeypatch.setattr(verify_friday_postflight, "urlopen", lambda url, timeout: response)

    payload = verify_friday_postflight.fetch_meta("http://example.test/meta", timeout=2)

    assert len(payload["padding"]) == padding
    assert response.read_size == verify_friday_postflight.MAX_META_RESPONSE_BYTES + 1


def test_fetch_meta_rejects_one_byte_over_limit(monkeypatch):
    response = _Response(b"x" * (verify_friday_postflight.MAX_META_RESPONSE_BYTES + 1))
    monkeypatch.setattr(verify_friday_postflight, "urlopen", lambda url, timeout: response)

    with pytest.raises(
        verify_friday_postflight.PostflightError,
        match="response exceeds 1048576 bytes",
    ):
        verify_friday_postflight.fetch_meta("http://example.test/meta", timeout=2)

    assert response.read_size == verify_friday_postflight.MAX_META_RESPONSE_BYTES + 1


def test_fetch_meta_normalizes_json_decode_recursion_failure(monkeypatch):
    response = _Response(_deeply_nested_json())
    monkeypatch.setattr(verify_friday_postflight, "urlopen", lambda url, timeout: response)

    with pytest.raises(verify_friday_postflight.PostflightError) as exc_info:
        verify_friday_postflight.fetch_meta("http://example.test/meta", timeout=2)

    assert str(exc_info.value).startswith("unable to read http://example.test/meta:")
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert isinstance(exc_info.value.__cause__.__cause__, RecursionError)


def test_main_publishes_failure_receipt_for_json_decode_recursion(monkeypatch, capsys, tmp_path):
    response = _Response(_deeply_nested_json())
    monkeypatch.setattr(verify_friday_postflight, "urlopen", lambda url, timeout: response)
    receipt = tmp_path / "receipt.json"

    result = verify_friday_postflight.main(
        [
            "--publish",
            "--expected-date",
            "2026-09-11",
            "--receipt",
            str(receipt),
            "--url",
            "http://example.test/meta",
        ]
    )

    assert result == 1
    assert capsys.readouterr().out == receipt.read_text()
    payload = verify_friday_postflight.loads_object(receipt.read_text())
    assert payload["status"] == "failed"
    assert payload["reason"].startswith("unable to read http://example.test/meta:")
    assert len(payload["reason"]) <= verify_friday_postflight.MAX_FAILURE_REASON_LENGTH


def test_main_publishes_a_bounded_failure_receipt(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        verify_friday_postflight,
        "fetch_meta",
        lambda url, timeout: (_ for _ in ()).throw(
            verify_friday_postflight.PostflightError("API unavailable")
        ),
    )

    receipt = tmp_path / "receipt.json"
    result = verify_friday_postflight.main(
        ["--publish", "--expected-date", "2026-09-11", "--receipt", str(receipt)]
    )

    assert result == 1
    rendered = capsys.readouterr().out
    assert rendered == receipt.read_text()
    payload = verify_friday_postflight.loads_object(rendered)
    assert payload["schema_version"] == 1
    assert payload["expected_date"] == "2026-09-11"
    assert payload["reason"] == "API unavailable"
    assert payload["status"] == "failed"


def test_main_truncates_failure_reason_to_consumer_limit(monkeypatch, capsys):
    reason = "x" * (verify_friday_postflight.MAX_FAILURE_REASON_LENGTH + 1)
    monkeypatch.setattr(
        verify_friday_postflight,
        "fetch_meta",
        lambda url, timeout: (_ for _ in ()).throw(
            verify_friday_postflight.PostflightError(reason)
        ),
    )

    result = verify_friday_postflight.main(["--dry-run", "--expected-date", "2026-09-11"])

    assert result == 1
    payload = verify_friday_postflight.loads_object(capsys.readouterr().out)
    assert payload["reason"] == "x" * verify_friday_postflight.MAX_FAILURE_REASON_LENGTH


def test_published_failure_round_trips_through_schedule_projection(monkeypatch, capsys, tmp_path):
    receipt = tmp_path / "receipt.json"
    observed_at = datetime(2026, 9, 12, 5, 15, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(verify_friday_postflight, "_utc_now", lambda: observed_at)
    monkeypatch.setattr(
        verify_friday_postflight,
        "fetch_meta",
        lambda url, timeout: (_ for _ in ()).throw(
            verify_friday_postflight.PostflightError("💥" * 1_001)
        ),
    )

    result = verify_friday_postflight.main(
        ["--publish", "--expected-date", "2026-09-11", "--receipt", str(receipt)]
    )

    assert result == 1
    projected = friday_postflight.status(
        receipt, now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc)
    )
    assert projected["status"] == "failed"
    assert projected["reason"] == "💥" * verify_friday_postflight.MAX_FAILURE_REASON_LENGTH
    assert capsys.readouterr().out == receipt.read_text()


def test_checked_at_records_completion_after_evidence_fetch(monkeypatch, capsys, tmp_path):
    receipt = tmp_path / "receipt.json"
    payload = _payload()
    payload["nightly"]["finished_at"] = "2026-09-12T05:15:04+00:00"
    for item in payload["miner_evidence"]["miners"].values():
        item["evidence_at"] = "2026-09-12T05:15:03+00:00"
    clock = iter(
        (
            datetime(2026, 9, 12, 5, 15, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 12, 5, 15, 5, tzinfo=timezone.utc),
        )
    )
    monkeypatch.setattr(verify_friday_postflight, "_utc_now", lambda: next(clock))
    monkeypatch.setattr(verify_friday_postflight, "fetch_meta", lambda url, timeout: payload)

    result = verify_friday_postflight.main(
        ["--publish", "--expected-date", "2026-09-11", "--receipt", str(receipt)]
    )

    assert result == 0
    published = verify_friday_postflight.loads_object(receipt.read_text())
    assert published["checked_at"] == "2026-09-12T05:15:05+00:00"
    assert (
        friday_postflight.status(receipt, now=datetime(2026, 9, 12, 5, 31, tzinfo=timezone.utc))
        == published
    )
    assert capsys.readouterr().out == receipt.read_text()


def test_main_publishes_current_receipt(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(verify_friday_postflight, "fetch_meta", lambda url, timeout: _payload())
    receipt = tmp_path / "receipt.json"

    result = verify_friday_postflight.main(
        ["--publish", "--expected-date", "2026-09-11", "--receipt", str(receipt)]
    )

    assert result == 0
    assert capsys.readouterr().out == receipt.read_text()
    assert verify_friday_postflight.loads_object(receipt.read_text())["status"] == "current"


def test_receipt_writer_preserves_mode_and_creates_regular_parent_chain(tmp_path):
    receipt = tmp_path / "nested" / "receipts" / "receipt.json"
    verify_friday_postflight._write_receipt_atomic(receipt, "first\n")
    receipt.chmod(0o600)

    verify_friday_postflight._write_receipt_atomic(receipt, "second\n")

    assert receipt.read_text() == "second\n"
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert [item.name for item in receipt.parent.iterdir()] == ["receipt.json"]


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory"])
def test_receipt_writer_rejects_nonregular_target_without_blocking(tmp_path, kind):
    receipt = tmp_path / "receipt.json"
    if kind == "symlink":
        target = tmp_path / "target.json"
        target.write_text("outside\n")
        receipt.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(receipt)
    else:
        receipt.mkdir()

    with pytest.raises(OSError, match="receipt target must be a regular file"):
        verify_friday_postflight._write_receipt_atomic(receipt, "new\n")

    if kind == "symlink":
        assert target.read_text() == "outside\n"


def test_receipt_writer_rejects_symlinked_parent(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(external, target_is_directory=True)

    with pytest.raises(OSError):
        verify_friday_postflight._write_receipt_atomic(alias / "receipt.json", "new\n")

    assert not (external / "receipt.json").exists()


def test_receipt_writer_rejects_target_replacement_before_publish(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    receipt.write_text("old\n")
    replacement = tmp_path / "replacement.json"
    replacement.write_text("replacement\n")
    original = verify_friday_postflight._same_target

    def replace_then_check(directory_fd, leaf, expected):
        replacement.replace(receipt)
        return original(directory_fd, leaf, expected)

    monkeypatch.setattr(verify_friday_postflight, "_same_target", replace_then_check)

    with pytest.raises(OSError, match="receipt target changed before publication"):
        verify_friday_postflight._write_receipt_atomic(receipt, "new\n")

    assert receipt.read_text() == "replacement\n"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["receipt.json"]


def test_receipt_writer_rejects_in_place_target_change_before_publish(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    receipt.write_text("old\n")
    original = verify_friday_postflight._same_target

    def mutate_then_check(directory_fd, leaf, expected):
        receipt.write_text("concurrent\n")
        return original(directory_fd, leaf, expected)

    monkeypatch.setattr(verify_friday_postflight, "_same_target", mutate_then_check)

    with pytest.raises(OSError, match="receipt target changed before publication"):
        verify_friday_postflight._write_receipt_atomic(receipt, "new\n")

    assert receipt.read_text() == "concurrent\n"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["receipt.json"]


def test_receipt_writer_restores_target_replaced_at_atomic_publish(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    receipt.write_text("old\n")
    replacement = tmp_path / "replacement.json"
    replacement.write_text("concurrent\n")
    original = verify_friday_postflight._rename_at2
    injected = False

    def replace_then_rename(parent_fd, source, destination, flags):
        nonlocal injected
        if not injected:
            injected = True
            replacement.replace(receipt)
        return original(parent_fd, source, destination, flags)

    monkeypatch.setattr(verify_friday_postflight, "_rename_at2", replace_then_rename)

    with pytest.raises(OSError, match="receipt target changed during publication"):
        verify_friday_postflight._write_receipt_atomic(receipt, "new\n")

    assert receipt.read_text() == "concurrent\n"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["receipt.json"]


def test_receipt_writer_rejects_target_created_at_atomic_publish(tmp_path, monkeypatch):
    receipt = tmp_path / "receipt.json"
    original = verify_friday_postflight._rename_at2
    injected = False

    def create_then_rename(parent_fd, source, destination, flags):
        nonlocal injected
        if not injected:
            injected = True
            receipt.write_text("concurrent\n")
        return original(parent_fd, source, destination, flags)

    monkeypatch.setattr(verify_friday_postflight, "_rename_at2", create_then_rename)

    with pytest.raises(OSError, match="receipt target changed before publication"):
        verify_friday_postflight._write_receipt_atomic(receipt, "new\n")

    assert receipt.read_text() == "concurrent\n"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["receipt.json"]


def test_receipt_writer_rejects_parent_replacement_before_publish(tmp_path, monkeypatch):
    parent = tmp_path / "receipts"
    parent.mkdir()
    receipt = parent / "receipt.json"
    receipt.write_text("old\n")
    displaced = tmp_path / "displaced"
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    original = verify_friday_postflight._directory_chain_matches
    calls = 0

    def replace_then_check(path, expected):
        nonlocal calls
        calls += 1
        if calls == 1:
            parent.rename(displaced)
            replacement.rename(parent)
        return original(path, expected)

    monkeypatch.setattr(
        verify_friday_postflight, "_directory_chain_matches", replace_then_check
    )

    with pytest.raises(OSError, match="receipt parent changed before publication"):
        verify_friday_postflight._write_receipt_atomic(receipt, "new\n")

    assert not receipt.exists()
    assert (displaced / "receipt.json").read_text() == "old\n"
    assert sorted(item.name for item in displaced.iterdir()) == ["receipt.json"]


def test_receipt_writer_reports_parent_replacement_after_publish(tmp_path, monkeypatch):
    parent = tmp_path / "receipts"
    parent.mkdir()
    receipt = parent / "receipt.json"
    receipt.write_text("old\n")
    displaced = tmp_path / "displaced"
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    original = verify_friday_postflight._directory_chain_matches
    calls = 0

    def replace_after_first_check(path, expected):
        nonlocal calls
        calls += 1
        result = original(path, expected)
        if calls == 1:
            parent.rename(displaced)
            replacement.rename(parent)
        return result

    monkeypatch.setattr(
        verify_friday_postflight, "_directory_chain_matches", replace_after_first_check
    )

    with pytest.raises(OSError, match="receipt parent changed during publication"):
        verify_friday_postflight._write_receipt_atomic(receipt, "new\n")

    assert not receipt.exists()
    assert (displaced / "receipt.json").read_text() == "new\n"


def test_authoritative_path_comparison_does_not_follow_symlink_alias(tmp_path):
    canonical = tmp_path / "logs" / "receipt.json"
    canonical.parent.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(canonical.parent, target_is_directory=True)

    assert verify_friday_postflight._same_publication_path(
        canonical.parent / ".." / "logs" / canonical.name, canonical
    )
    assert not verify_friday_postflight._same_publication_path(alias / canonical.name, canonical)


def test_main_reports_unsafe_receipt_publication_as_bounded_failure(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(verify_friday_postflight, "fetch_meta", lambda url, timeout: _payload())
    target = tmp_path / "target.json"
    target.write_text("outside\n")
    receipt = tmp_path / "receipt.json"
    receipt.symlink_to(target)

    result = verify_friday_postflight.main(
        ["--publish", "--expected-date", "2026-09-11", "--receipt", str(receipt)]
    )

    assert result == 1
    payload = verify_friday_postflight.loads_object(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["expected_date"] == "2026-09-11"
    assert payload["reason"].startswith("unable to publish postflight receipt:")
    assert len(payload["reason"]) <= verify_friday_postflight.MAX_FAILURE_REASON_LENGTH
    assert target.read_text() == "outside\n"


def test_main_dry_run_never_publishes(monkeypatch, capsys):
    monkeypatch.setattr(verify_friday_postflight, "fetch_meta", lambda url, timeout: _payload())

    def fail_if_called(path, text):
        raise AssertionError(f"dry-run attempted to publish {path}: {text}")

    monkeypatch.setattr(verify_friday_postflight, "_write_receipt_atomic", fail_if_called)

    result = verify_friday_postflight.main(["--dry-run", "--expected-date", "2026-09-11"])

    assert result == 0
    payload = verify_friday_postflight.loads_object(capsys.readouterr().out)
    assert payload["status"] == "current"
    assert payload["expected_date"] == "2026-09-11"


def test_main_dry_run_failure_never_publishes(monkeypatch, capsys):
    monkeypatch.setattr(
        verify_friday_postflight,
        "fetch_meta",
        lambda url, timeout: (_ for _ in ()).throw(
            verify_friday_postflight.PostflightError("API unavailable")
        ),
    )

    def fail_if_called(path, text):
        raise AssertionError(f"dry-run attempted to publish {path}: {text}")

    monkeypatch.setattr(verify_friday_postflight, "_write_receipt_atomic", fail_if_called)

    result = verify_friday_postflight.main(["--dry-run", "--expected-date", "2026-09-11"])

    assert result == 1
    payload = verify_friday_postflight.loads_object(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["reason"] == "API unavailable"


def test_main_defaults_to_nonpublishing(monkeypatch, capsys):
    monkeypatch.setattr(verify_friday_postflight, "fetch_meta", lambda url, timeout: _payload())

    def fail_if_called(path, text):
        raise AssertionError(f"default invocation attempted to publish {path}: {text}")

    monkeypatch.setattr(verify_friday_postflight, "_write_receipt_atomic", fail_if_called)

    result = verify_friday_postflight.main(["--expected-date", "2026-09-11"])

    assert result == 0
    assert verify_friday_postflight.loads_object(capsys.readouterr().out)["status"] == "current"


def test_main_requires_publish_for_alternate_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_friday_postflight, "fetch_meta", lambda url, timeout: _payload())

    with pytest.raises(SystemExit, match="2"):
        verify_friday_postflight.main(["--receipt", str(tmp_path / "receipt.json")])


def test_main_publish_uses_authoritative_receipt_by_default(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(verify_friday_postflight, "fetch_meta", lambda url, timeout: _payload())
    expected = tmp_path / "friday-postflight.json"
    monkeypatch.setattr(verify_friday_postflight, "DEFAULT_RECEIPT_PATH", expected)
    monkeypatch.setattr(
        verify_friday_postflight,
        "_utc_now",
        lambda: datetime(2026, 9, 12, 5, 15, 5, tzinfo=timezone.utc),
    )

    result = verify_friday_postflight.main(["--publish", "--expected-date", "2026-09-11"])

    assert result == 0
    assert capsys.readouterr().out == expected.read_text()
    assert verify_friday_postflight.loads_object(expected.read_text())["status"] == "current"


def test_main_refuses_authoritative_publish_before_slot(monkeypatch, capsys, tmp_path):
    expected = tmp_path / "friday-postflight.json"
    monkeypatch.setattr(verify_friday_postflight, "DEFAULT_RECEIPT_PATH", expected)
    monkeypatch.setattr(
        verify_friday_postflight,
        "_utc_now",
        lambda: datetime(2026, 9, 12, 5, 14, 59, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        verify_friday_postflight,
        "fetch_meta",
        lambda url, timeout: (_ for _ in ()).throw(AssertionError("API should not be read")),
    )

    result = verify_friday_postflight.main(["--publish", "--expected-date", "2026-09-11"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "not due before 2026-09-12T05:15:00+00:00" in captured.err
    assert not expected.exists()


def test_main_refuses_authoritative_publish_for_an_old_friday(monkeypatch, capsys, tmp_path):
    expected = tmp_path / "friday-postflight.json"
    monkeypatch.setattr(verify_friday_postflight, "DEFAULT_RECEIPT_PATH", expected)
    monkeypatch.setattr(
        verify_friday_postflight,
        "_utc_now",
        lambda: datetime(2026, 9, 19, 5, 16, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        verify_friday_postflight,
        "fetch_meta",
        lambda url, timeout: (_ for _ in ()).throw(AssertionError("API should not be read")),
    )

    result = verify_friday_postflight.main(["--publish", "--expected-date", "2026-09-11"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "requires current Friday 2026-09-18" in captured.err
    assert not expected.exists()


def test_authoritative_publication_rejects_slots_before_monitor_epoch():
    with pytest.raises(
        verify_friday_postflight.PostflightError,
        match="authoritative publication starts at 2026-09-12T05:15:00\\+00:00",
    ):
        verify_friday_postflight.validate_authoritative_publication(
            date(2026, 9, 4),
            datetime(2026, 9, 5, 5, 16, tzinfo=timezone.utc),
        )
