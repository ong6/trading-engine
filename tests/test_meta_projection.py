"""Tests for composing the operational metadata projection."""

import re
from datetime import datetime
from pathlib import Path

import pytest

from server import (
    driver_monitor,
    e1_forward_status,
    exposure_monitor,
    friday_postflight,
    liquidity_monitor,
    main,
    market_health,
    market_read_models,
    meta_projection,
    miner_monitor,
    nightly_monitor,
    queue_monitor,
    read_model_utils,
    scheduler_monitor,
    sector_forward_status,
    source_control,
    sweep_monitor,
    walkforward_evidence,
    walkforward_recovery,
    xs_forward_status,
)

OPTIONAL_PROJECTION_OWNERS = {
    "source_control": source_control,
    "miner_evidence": miner_monitor,
    "nightly_evidence": nightly_monitor,
    "liquidity_evidence": liquidity_monitor,
    "sweep_evidence": sweep_monitor,
    "walkforward_evidence": walkforward_evidence,
    "forward_review": sector_forward_status,
    "xs_forward_review": xs_forward_status,
    "e1_forward": e1_forward_status,
    "friday_postflight": friday_postflight,
}

EMPTY_QUARANTINES = {
    "price_quarantines": [],
    "price_quarantines_limit": meta_projection.PRICE_QUARANTINE_LIMIT,
    "price_quarantines_matching_count": 0,
    "price_quarantines_truncated": False,
}
REPO_ROOT = Path(__file__).resolve().parents[1]


def _javascript_string_fields(source: str, declaration: str) -> list[str]:
    match = re.search(
        rf"const {declaration} = (?:new Set\()?\[(?P<fields>.*?)\]\)?;",
        source,
        re.DOTALL,
    )
    assert match is not None
    return re.findall(r'^\s*"([a-z0-9_-]+)",?\s*$', match["fields"], re.MULTILINE)


def _javascript_constant(source: str, declaration: str) -> str:
    match = re.search(rf"^const {declaration} = (?P<value>.+);$", source, re.MULTILINE)
    assert match is not None
    return match["value"]


def test_public_driver_fields_match_browser_contract():
    source = (REPO_ROOT / "ui" / "app" / "lib" / "meta-job-contracts.js").read_text()
    browser_fields = _javascript_string_fields(source, "DRIVER_FIELDS")
    assert len(browser_fields) == len(set(browser_fields))
    assert tuple(browser_fields) == meta_projection.PUBLIC_DRIVER_FIELDS


def test_public_meta_fields_match_browser_contract():
    source = (REPO_ROOT / "ui" / "app" / "lib" / "meta-contracts.js").read_text()
    browser_fields = _javascript_string_fields(source, "META_FIELDS")
    assert len(browser_fields) == len(set(browser_fields))
    assert tuple(browser_fields) == meta_projection.PUBLIC_META_FIELDS


def test_postflight_browser_schedule_constants_match_backend():
    source = (REPO_ROOT / "ui" / "app" / "lib" / "meta-automation-contracts.js").read_text()

    assert _javascript_constant(source, "FIRST_POSTFLIGHT_AT") == (
        f'"{friday_postflight.FIRST_EXPECTED_AT.isoformat()}"'
    )
    assert int(_javascript_constant(source, "POSTFLIGHT_EXPECTED_UTC_DAY")) == (
        friday_postflight.SCHEDULE_WEEKDAY
    )
    assert int(_javascript_constant(source, "POSTFLIGHT_SCHEDULE_HOUR")) == (
        friday_postflight.SCHEDULE_TIME.hour
    )
    assert int(_javascript_constant(source, "POSTFLIGHT_SCHEDULE_MINUTE")) == (
        friday_postflight.SCHEDULE_TIME.minute
    )


def test_browser_host_vocabularies_match_backend_producers():
    source = (REPO_ROOT / "ui" / "app" / "lib" / "meta-automation-contracts.js").read_text()

    assert set(_javascript_string_fields(source, "PRODUCTION_DRIVERS")) == {
        schedule[1] for schedule in driver_monitor.DRIVER_SCHEDULES
    }
    assert set(_javascript_string_fields(source, "AUXILIARY_JOBS")) == set(
        scheduler_monitor.expected_auxiliary_cron_entries()
    )
    assert set(_javascript_string_fields(source, "SCHEDULER_SERVICE_UNITS")) == set(
        scheduler_monitor.scheduler_host.CRON_SERVICE_UNITS
    )
    assert set(_javascript_string_fields(source, "SCHEDULER_SERVICE_STATES")) == (
        scheduler_monitor.scheduler_host.CRON_SERVICE_STATES | {"unknown"}
    )
    assert set(_javascript_string_fields(source, "SCHEDULER_ENABLEMENT_STATES")) == (
        scheduler_monitor.scheduler_host.CRON_SERVICE_ENABLEMENT_STATES | {"unknown"}
    )
    assert set(_javascript_string_fields(source, "SCHEDULER_STATUSES")) == (
        scheduler_monitor.PUBLIC_STATUSES
    )
    assert set(_javascript_string_fields(source, "FRIDAY_POSTFLIGHT_STATUSES")) == (
        friday_postflight.PUBLIC_STATUSES
    )
    assert set(_javascript_string_fields(source, "SCHEDULER_INVALID_REASONS")) == (
        scheduler_monitor.PUBLIC_INVALID_REASONS
    )
    assert set(_javascript_string_fields(source, "POSTFLIGHT_INVALID_REASONS")) == (
        friday_postflight.PUBLIC_INVALID_REASONS
    )
    assert set(_javascript_string_fields(source, "SOURCE_CONTROL_INVALID_REASONS")) == (
        source_control.PUBLIC_INVALID_REASONS
    )
    assert (
        set(_javascript_string_fields(source, "SOURCE_CONTROL_LOCAL_ONLY_REASONS"))
        == source_control.PUBLIC_LOCAL_ONLY_REASONS
    )
    assert set(_javascript_string_fields(source, "SOURCE_CONTROL_STATUSES")) == (
        source_control.PUBLIC_STATUSES
    )
    assert int(_javascript_constant(source, "SCHEDULER_TIMEZONE_MAX_CHARS")) == (
        scheduler_monitor.scheduler_host.PUBLIC_TIMEZONE_MAX_CHARS
    )
    assert int(_javascript_constant(source, "SOURCE_CONTROL_IDENTITY_MAX_CHARS")) == (
        source_control.PUBLIC_IDENTITY_MAX_CHARS
    )
    assert _javascript_constant(source, "SOURCE_CONTROL_TRACKING_COUNT_MAX") == (
        "PUBLIC_SAFE_INTEGER_MAX"
    )
    assert source_control.PUBLIC_TRACKING_COUNT_MAX == read_model_utils.PUBLIC_SAFE_INTEGER_MAX


def test_browser_liquidity_vocabularies_match_backend_producer():
    source = (REPO_ROOT / "ui" / "app" / "lib" / "meta-evidence-contracts.js").read_text()

    assert set(_javascript_string_fields(source, "LIQUIDITY_EVIDENCE_STATUSES")) == (
        liquidity_monitor.PUBLIC_STATUSES
    )
    assert set(_javascript_string_fields(source, "LIQUIDITY_EVIDENCE_REASONS")) == (
        liquidity_monitor.PUBLIC_REASONS
    )


def test_public_meta_allowlists_fields_without_mutating_internal_payload():
    internal = dict.fromkeys(meta_projection.PUBLIC_META_FIELDS)
    internal["meta"] = {"regime": "risk-off"}
    internal["internal"] = {"path": "/private/repository", "command": ["private"]}

    public = meta_projection._public_meta(internal)

    assert tuple(public) == meta_projection.PUBLIC_META_FIELDS
    assert public["meta"] == {"regime": "risk-off"}
    assert "internal" not in public
    assert internal["internal"] == {
        "path": "/private/repository",
        "command": ["private"],
    }
    assert public is not internal


def test_public_meta_requires_every_documented_field():
    internal = dict.fromkeys(meta_projection.PUBLIC_META_FIELDS)
    del internal["e1_forward"]

    with pytest.raises(KeyError, match="e1_forward"):
        meta_projection._public_meta(internal)


def test_public_driver_allowlists_fields_without_mutating_internal_status():
    internal = {
        "name": "run_daily",
        "status": "ok",
        "log": "/private/logs/cron.log",
        "finished_at": "2026-09-12T00:52:18Z",
        "internal": "not public",
        "command": ["python", "-m", "private.worker"],
        "path": "/private/repository",
    }

    public = meta_projection._public_driver(internal)

    assert public == {
        "name": "run_daily",
        "status": "ok",
        "finished_at": "2026-09-12T00:52:18Z",
    }
    assert internal["log"] == "/private/logs/cron.log"
    assert internal["internal"] == "not public"
    assert internal["command"] == ["python", "-m", "private.worker"]
    assert internal["path"] == "/private/repository"
    assert public is not internal
    assert meta_projection._public_driver(None) is None


def test_public_walkforward_status_sanitizes_driver_and_preserves_sparse_fallback():
    status = {
        "weekly_walkforward": {"status": "recovered", "log": "/private/wf.log"},
        "walkforward_evidence": {"status": "current"},
    }

    assert meta_projection._public_walkforward_status(status) == {
        "weekly_walkforward": {"status": "recovered"},
        "walkforward_evidence": {"status": "current"},
    }
    assert status["weekly_walkforward"]["log"] == "/private/wf.log"
    assert meta_projection._public_walkforward_status({}) == {}


def test_public_snapshot_omits_raw_bookkeeping_and_local_path():
    raw = {
        "regime": "risk-off",
        "last_run": "2026-09-12T12:00:00+00:00",
        "screen_date": "2026-09-11",
        "price_verify": {"disagreements": ["producer-only detail"]},
    }

    summary, status = meta_projection._public_snapshot(
        raw, {"status": "ok", "path": "/private/data/_meta.json"}
    )

    assert summary == {
        "regime": "risk-off",
        "last_run": "2026-09-12T12:00:00+00:00",
        "screen_date": "2026-09-11",
    }
    assert status == {"status": "ok"}


def test_public_snapshot_fails_malformed_summary_closed_without_path():
    summary, status = meta_projection._public_snapshot(
        {"regime": "invented"},
        {"status": "ok", "path": "/private/data/_meta.json"},
    )

    assert summary == {}
    assert status == {"status": "invalid", "reason": "malformed-summary"}


def test_meta_uses_complete_snapshot_internally_but_returns_only_summary(
    con, tmp_path, monkeypatch
):
    snapshot = tmp_path / "_meta.json"
    snapshot.write_text(
        '{"regime":"risk-on","last_run":"2026-09-12T12:00:00+00:00",'
        '"screen_date":"2026-09-11","private_marker":{"rows":[1,2,3]}}'
    )
    observed = []
    drivers = {
        "nightly": None,
        "weekly_verify": None,
        "weekly_sweeps": None,
        "weekly_liquidity": None,
        "weekly_walkforward": None,
    }

    def observe(meta, *_args):
        observed.append(meta)
        return {"status": "missing"}

    monkeypatch.setattr(driver_monitor, "driver_statuses", lambda: drivers)
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda actual: None)
    monkeypatch.setattr(market_health, "price_verification", observe)
    monkeypatch.setattr(nightly_monitor, "evidence_status", observe)
    monkeypatch.setattr(miner_monitor, "evidence_status", observe)
    monkeypatch.setattr(liquidity_monitor, "evidence_status", observe)
    monkeypatch.setattr(queue_monitor, "status", lambda actual: {})
    monkeypatch.setattr(exposure_monitor, "status", lambda *args: {})
    monkeypatch.setattr(meta_projection, "_price_quarantines", lambda actual: EMPTY_QUARANTINES)
    monkeypatch.setattr(
        meta_projection,
        "_host_status",
        lambda data_dir: {
            "scheduler": {},
            "friday_postflight": {},
            "source_control": {},
        },
    )
    monkeypatch.setattr(
        meta_projection,
        "_walkforward_status",
        lambda *args: {"weekly_walkforward": None, "walkforward_evidence": {}},
    )
    monkeypatch.setattr(
        meta_projection,
        "_forward_status",
        lambda *args: {"forward_review": {}, "xs_forward_review": {}, "e1_forward": {}},
    )

    result = meta_projection.project(con, meta_path=snapshot, data_dir=tmp_path)

    assert result["meta"] == {
        "regime": "risk-on",
        "last_run": "2026-09-12T12:00:00+00:00",
        "screen_date": "2026-09-11",
    }
    assert result["meta_file"] == {"status": "ok"}
    assert tuple(result) == meta_projection.PUBLIC_META_FIELDS
    assert len(observed) == 4
    assert all(meta["private_marker"] == {"rows": [1, 2, 3]} for meta in observed)


def test_price_quarantine_projection_bounds_rows_and_text(con):
    limit = meta_projection.PRICE_QUARANTINE_LIMIT
    oversized = "x" * (meta_projection.PRICE_QUARANTINE_DETAIL_MAX_CHARS + 1)
    con.executemany(
        "INSERT INTO price_quarantine "
        "(ticker, status, reason, evidence, confirmed_at) "
        "VALUES (?, 'active', ?, ?, ?)",
        [
            (f"Q{index:03}", oversized, oversized, datetime(2026, 9, 12, 1, 2, 3))
            for index in range(limit + 2)
        ],
    )

    result = meta_projection._price_quarantines(con)

    assert result["price_quarantines_limit"] == limit
    assert result["price_quarantines_matching_count"] == limit + 2
    assert result["price_quarantines_truncated"] is True
    assert len(result["price_quarantines"]) == limit
    assert [row["ticker"] for row in result["price_quarantines"]] == [
        f"Q{index:03}" for index in range(limit)
    ]
    assert all(row["detail_truncated"] is True for row in result["price_quarantines"])
    assert all(
        len(row["reason"]) == meta_projection.PRICE_QUARANTINE_DETAIL_MAX_CHARS
        and len(row["evidence"]) == meta_projection.PRICE_QUARANTINE_DETAIL_MAX_CHARS
        and row["confirmed_at"] == "2026-09-12T01:02:03+00:00"
        for row in result["price_quarantines"]
    )


def test_price_quarantine_projection_is_explicit_without_table(monkeypatch):
    class MissingTableConnection:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("missing-table projection should not query rows")

    monkeypatch.setattr(meta_projection, "table_exists", lambda *_args: False)
    assert meta_projection._price_quarantines(MissingTableConnection()) == EMPTY_QUARANTINES


def test_price_quarantine_rejects_malformed_ticker_without_truncating_or_rewriting(con):
    ticker = "Q" * 33
    con.execute(
        "INSERT INTO price_quarantine "
        "(ticker, status, reason, evidence, confirmed_at) "
        "VALUES (?, 'active', 'reason', 'evidence', now())",
        [ticker],
    )

    with pytest.raises(ValueError, match="ticker is invalid"):
        meta_projection._price_quarantines(con)
    assert con.execute("SELECT ticker FROM price_quarantine").fetchone()[0] == ticker


@pytest.mark.parametrize(
    ("reason", "evidence", "confirmed_at", "message"),
    [
        (None, "evidence", datetime(2026, 9, 12), "reason is invalid"),
        ("   ", "evidence", datetime(2026, 9, 12), "reason is invalid"),
        ("reason", None, datetime(2026, 9, 12), "evidence is invalid"),
        ("reason", "\t", datetime(2026, 9, 12), "evidence is invalid"),
        ("reason", "evidence", None, "confirmation time is invalid"),
    ],
)
def test_price_quarantine_rejects_incomplete_active_rows_without_rewriting(
    con, reason, evidence, confirmed_at, message
):
    con.execute(
        "INSERT INTO price_quarantine "
        "(ticker, status, reason, evidence, confirmed_at) "
        "VALUES ('AAA', 'active', ?, ?, ?)",
        [reason, evidence, confirmed_at],
    )

    with pytest.raises(ValueError, match=message):
        meta_projection._price_quarantines(con)

    assert con.execute(
        "SELECT reason, evidence, confirmed_at FROM price_quarantine WHERE ticker = 'AAA'"
    ).fetchone() == (reason, evidence, confirmed_at)


def test_nightly_projection_isolates_unsafe_public_count(monkeypatch):
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1
    monkeypatch.setattr(
        nightly_monitor,
        "evidence_status",
        lambda *_args: {"status": "current", "screened": unsafe},
    )
    monkeypatch.setattr(miner_monitor, "evidence_status", lambda *_args: {})
    monkeypatch.setattr(sweep_monitor, "evidence_status", lambda *_args: {})
    monkeypatch.setattr(liquidity_monitor, "evidence_status", lambda *_args: {})

    result = meta_projection._nightly_evidence(
        object(), {}, {"nightly": None, "weekly_liquidity": None}, None
    )

    assert result["nightly_evidence"] == {
        "status": "invalid",
        "reason": "projection-error",
    }


def test_meta_keeps_live_status_when_snapshot_is_invalid(tmp_path, monkeypatch):
    malformed = tmp_path / "_meta.json"
    malformed.write_text("not json")

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    monkeypatch.setattr(main, "META_PATH", malformed)
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda actual: None)
    monkeypatch.setattr(queue_monitor, "status", lambda actual: {"counts": {}})
    monkeypatch.setattr(
        exposure_monitor,
        "status",
        lambda actual, latest: {"ticker_count": 0},
    )
    monkeypatch.setattr(
        driver_monitor,
        "driver_statuses",
        lambda: {
            "nightly": None,
            "weekly_verify": None,
            "weekly_sweeps": None,
            "weekly_liquidity": None,
            "weekly_walkforward": None,
        },
    )
    monkeypatch.setattr(
        scheduler_monitor,
        "status",
        lambda: {"status": "ok", "expected_entries": 5, "matched_entries": 5},
    )
    monkeypatch.setattr(source_control, "status", lambda: {"status": "local-only"})
    monkeypatch.setattr(
        walkforward_recovery, "reconcile_driver_status", lambda status, actual: None
    )
    monkeypatch.setattr(
        walkforward_evidence,
        "evidence_status",
        lambda actual: {"status": "current"},
    )
    monkeypatch.setattr(
        liquidity_monitor,
        "evidence_status",
        lambda *args: {"status": "not-yet-run"},
    )
    monkeypatch.setattr(meta_projection, "_price_quarantines", lambda actual: EMPTY_QUARANTINES)
    monkeypatch.setattr(sector_forward_status, "status", lambda *args: {"status": "X"})
    monkeypatch.setattr(xs_forward_status, "status", lambda *args: {"status": "Y"})
    monkeypatch.setattr(e1_forward_status, "status", lambda *args: {"status": "Z"})

    result = main.meta()

    assert result["meta"] == {}
    assert result["meta_file"] == {
        "status": "invalid",
        "reason": "unreadable-or-malformed",
    }
    assert result["market_freshness"]["status"] == "unknown"
    assert result["price_verification"] == {"status": "missing"}
    assert result["queue"] == {"counts": {}}
    assert result["scheduler"]["status"] == "ok"
    assert result["source_control"]["status"] == "local-only"
    assert result["weekly_liquidity"] is None
    assert result["forward_review"] == {"status": "X"}
    assert con.closed is True


@pytest.mark.parametrize(
    ("broken_projection", "result_key", "expected"),
    [
        (
            "evidence_status",
            "miner_evidence",
            {"status": "invalid", "reason": "projection-error"},
        ),
        (
            "evidence_status",
            "sweep_evidence",
            {"status": "invalid", "reason": "projection-error"},
        ),
        (
            "evidence_status",
            "liquidity_evidence",
            {"status": "invalid", "reason": "projection-error"},
        ),
        (
            "evidence_status",
            "nightly_evidence",
            {"status": "invalid", "reason": "projection-error"},
        ),
        (
            "evidence_status",
            "walkforward_evidence",
            {"status": "invalid", "reason": "projection-error"},
        ),
        (
            "status",
            "forward_review",
            {"status": "INVALID", "paper_only": True, "automatic_action": "none"},
        ),
        (
            "status",
            "xs_forward_review",
            {"status": "INVALID", "paper_only": True, "automatic_action": "none"},
        ),
        (
            "status",
            "e1_forward",
            {"status": "INVALID", "paper_only": True, "automatic_action": "none"},
        ),
        (
            "status",
            "source_control",
            {
                "status": "invalid",
                "reason": "projection-error",
                "branch": None,
                "remote": None,
                "upstream": None,
                "ahead": None,
                "behind": None,
                "network_checked": False,
            },
        ),
        (
            "status",
            "friday_postflight",
            {"status": "invalid", "reason": "projection-error"},
        ),
    ],
)
def test_meta_isolates_unexpected_optional_projection_failures(
    tmp_path, monkeypatch, broken_projection, result_key, expected
):
    snapshot = tmp_path / "_meta.json"
    snapshot.write_text("{}")

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    drivers = {
        "nightly": {"status": "ok"},
        "weekly_verify": {"status": "ok"},
        "weekly_sweeps": {"status": "ok"},
        "weekly_liquidity": None,
        "weekly_walkforward": {"status": "ok"},
    }
    monkeypatch.setattr(main, "META_PATH", snapshot)
    monkeypatch.setattr(main, "read_con", lambda: con)
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda actual: None)
    monkeypatch.setattr(queue_monitor, "status", lambda actual: {"counts": {}})
    monkeypatch.setattr(
        exposure_monitor,
        "status",
        lambda actual, latest: {"ticker_count": 0},
    )
    monkeypatch.setattr(driver_monitor, "driver_statuses", lambda: drivers)
    monkeypatch.setattr(
        scheduler_monitor,
        "status",
        lambda: {"status": "ok", "expected_entries": 5, "matched_entries": 5},
    )
    monkeypatch.setattr(source_control, "status", lambda: {"status": "current"})
    monkeypatch.setattr(
        walkforward_recovery,
        "reconcile_driver_status",
        lambda status, actual: {**status, "checked": True},
    )
    monkeypatch.setattr(
        walkforward_evidence,
        "evidence_status",
        lambda actual: {"status": "current"},
    )
    monkeypatch.setattr(
        liquidity_monitor,
        "evidence_status",
        lambda *args: {"status": "not-yet-run"},
    )
    monkeypatch.setattr(meta_projection, "_price_quarantines", lambda actual: EMPTY_QUARANTINES)
    monkeypatch.setattr(sector_forward_status, "status", lambda *args: {"status": "SECTOR"})
    monkeypatch.setattr(xs_forward_status, "status", lambda *args: {"status": "XS"})
    monkeypatch.setattr(e1_forward_status, "status", lambda *args: {"status": "E1"})

    def broken(*_args):
        raise RuntimeError("sensitive optional projection detail")

    monkeypatch.setattr(OPTIONAL_PROJECTION_OWNERS[result_key], broken_projection, broken)

    result = main.meta()

    assert result[result_key] == expected
    assert result["queue"] == {"counts": {}}
    assert result["nightly"] == {"status": "ok"}
    assert result["weekly_walkforward"] == {"status": "ok"}
    assert con.closed is True


def test_meta_projects_walkforward_driver_if_reconciliation_crashes(tmp_path, monkeypatch):
    snapshot = tmp_path / "_meta.json"
    snapshot.write_text("{}")

    class Connection:
        def close(self):
            pass

    raw_walkforward = {
        "status": "failed",
        "stage": "drain",
        "internal": "not public",
    }
    drivers = {
        "nightly": None,
        "weekly_verify": None,
        "weekly_sweeps": None,
        "weekly_liquidity": None,
        "weekly_walkforward": raw_walkforward,
    }
    monkeypatch.setattr(main, "META_PATH", snapshot)
    monkeypatch.setattr(main, "read_con", Connection)
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda actual: None)
    monkeypatch.setattr(queue_monitor, "status", lambda actual: {"counts": {}})
    monkeypatch.setattr(exposure_monitor, "status", lambda *args: {})
    monkeypatch.setattr(driver_monitor, "driver_statuses", lambda: drivers)
    monkeypatch.setattr(
        scheduler_monitor,
        "status",
        lambda: {"status": "ok", "expected_entries": 5, "matched_entries": 5},
    )
    monkeypatch.setattr(source_control, "status", lambda: {"status": "current"})
    monkeypatch.setattr(
        walkforward_recovery,
        "reconcile_driver_status",
        lambda *args: (_ for _ in ()).throw(RuntimeError("broken reconciliation")),
    )
    monkeypatch.setattr(
        walkforward_evidence, "evidence_status", lambda actual: {"status": "current"}
    )
    monkeypatch.setattr(meta_projection, "_price_quarantines", lambda actual: EMPTY_QUARANTINES)
    monkeypatch.setattr(sector_forward_status, "status", lambda *args: {})
    monkeypatch.setattr(xs_forward_status, "status", lambda *args: {})
    monkeypatch.setattr(e1_forward_status, "status", lambda *args: {})

    result = main.meta()

    assert result["weekly_walkforward"] == {"status": "failed", "stage": "drain"}
    assert result["weekly_walkforward"] is not raw_walkforward
    assert raw_walkforward["internal"] == "not public"


def test_meta_isolates_scheduler_projection_failure(tmp_path, monkeypatch):
    snapshot = tmp_path / "_meta.json"
    snapshot.write_text("{}")

    class Connection:
        def close(self):
            pass

    drivers = {
        "nightly": None,
        "weekly_verify": None,
        "weekly_sweeps": None,
        "weekly_liquidity": None,
        "weekly_walkforward": None,
    }
    monkeypatch.setattr(main, "META_PATH", snapshot)
    monkeypatch.setattr(main, "read_con", Connection)
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda actual: None)
    monkeypatch.setattr(queue_monitor, "status", lambda actual: {"counts": {}})
    monkeypatch.setattr(exposure_monitor, "status", lambda *args: {})
    monkeypatch.setattr(driver_monitor, "driver_statuses", lambda: drivers)
    monkeypatch.setattr(
        scheduler_monitor,
        "status",
        lambda: (_ for _ in ()).throw(RuntimeError("sensitive scheduler detail")),
    )
    monkeypatch.setattr(walkforward_recovery, "reconcile_driver_status", lambda *args: None)
    monkeypatch.setattr(walkforward_evidence, "evidence_status", lambda *args, **kwargs: {})
    monkeypatch.setattr(meta_projection, "_price_quarantines", lambda actual: EMPTY_QUARANTINES)
    monkeypatch.setattr(sector_forward_status, "status", lambda *args: {})
    monkeypatch.setattr(xs_forward_status, "status", lambda *args: {})
    monkeypatch.setattr(e1_forward_status, "status", lambda *args: {})

    result = main.meta()

    assert result["scheduler"] == {
        "status": "invalid",
        "reason": "projection-error",
        "cron_service": "unknown",
        "cron_service_unit": None,
        "cron_service_enabled": "unknown",
        "timezone": "unknown",
        "expected_timezone": "UTC",
        "timezone_ok": False,
        "expected_entries": 5,
        "matched_entries": 0,
        "missing_drivers": [],
        "duplicate_drivers": [],
        "auxiliary_expected_entries": 1,
        "auxiliary_matched_entries": 0,
        "missing_auxiliary_entries": [],
        "duplicate_auxiliary_entries": [],
        "unlaunchable_auxiliary_entries": [],
        "unexecutable_drivers": [],
        "unsafe_log_targets": [],
        "log_directory_writable": False,
    }
    assert result["queue"] == {"counts": {}}
