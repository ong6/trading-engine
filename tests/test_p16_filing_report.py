"""Tests for W3 price labels and filing IC reporting."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.p15_event_sources import session_close
from farm import p16_filing_report as report
from server import p15_price_fetch_attempts
from sim import nyse


def _at(day, hour=22, minute=0):
    return datetime.combine(day, time(hour, minute), timezone.utc)


def _daily(security, day, opening, close, *, source="fixture", basis="split_adjusted"):
    closed = datetime.combine(day, session_close(day), report.ET).astimezone(timezone.utc)
    row = {"security_id": security, "session_date": day.isoformat(), "open": opening,
           "close": close, "source": source, "price_basis": basis,
           "corporate_action_status": "adjusted", "session_close_at": closed.isoformat(),
           "available_at": (closed + timedelta(minutes=1)).isoformat(),
           "ingested_at": (closed + timedelta(minutes=1)).isoformat(),
           "source_sha256": ("a" if security == "SPY" else "b") * 64}
    return {**row, "row_sha256": canonical_sha256(row)}


def _intraday(security, at, opening, *, source="fixture", basis="split_adjusted"):
    row = {"security_id": security, "event_at": at.isoformat(), "open": opening,
           "source": source, "price_basis": basis, "corporate_action_status": "adjusted",
           "interval": "5m", "fact_type": "intraday.ohlcv.5m",
           "available_at": (at + timedelta(minutes=1)).isoformat(),
           "ingested_at": (at + timedelta(minutes=1)).isoformat(),
           "source_sha256": ("c" if security == "SPY" else "d") * 64}
    return {**row, "row_sha256": canonical_sha256(row)}


def _session_days(start, count):
    result = [start]
    while len(result) < count:
        result.append(nyse.next_session(result[-1]))
    return result


def _confirmation(through, *, method="recorded_fetch_attempt"):
    observed = through
    for _ in range(3):
        observed = nyse.next_session(observed)
    return {"method": method, "observed_through": observed.isoformat()}, observed


def _missing_db(path, missing_day, observed, *, attempted=None):
    con = db.connect(path)
    db.init_schema(con)
    p15_price_fetch_attempts.init_schema(con)
    con.executemany("INSERT INTO universe (ticker,liquid) VALUES (?,TRUE)", [("AAPL",), ("SPY",)])
    p15_price_fetch_attempts.record(
        con, market_date=missing_day, attempted_at=_at(attempted or observed, 22),
        requested_count=2, failed_count=0,
    )
    return con


def test_entry_targets_are_strict_and_exchange_calendar_aware():
    friday_preopen = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    assert report.entry_target(friday_preopen, "next_session_open") == datetime(
        2026, 11, 2, 14, 30, tzinfo=timezone.utc
    )
    monday = date(2026, 9, 28)
    assert report.entry_target(_at(monday, 13, 32), "next_bar") == _at(monday, 13, 35)
    assert report.entry_target(_at(monday, 13, 35), "next_bar") == _at(monday, 13, 40)
    assert report.entry_target(_at(monday, 12), "next_bar") == _at(monday, 13, 30)
    assert report.entry_target(_at(monday, 21), "next_bar") == _at(date(2026, 9, 29), 13, 30)


def test_next_session_label_uses_exact_entry_and_equal_costs():
    decision = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    entry = date(2026, 9, 28)
    rows = [_daily("AAPL", entry, 100, 110), _daily("SPY", entry, 200, 202)]
    value = report.make_label(
        decided_at=decision, labelled_at=_at(entry, 23), security_id="AAPL", horizon=1,
        entry_basis="next_session_open", daily_rows=rows,
    )
    assert value["status"] == "available"
    assert value["entry_at"] == "2026-09-28T13:30:00+00:00"
    assert value["asset_net_return"] == pytest.approx(110 * .999 / (100 * 1.001) - 1)
    assert value["spy_net_return"] == pytest.approx(202 * .999 / (200 * 1.001) - 1)
    assert value["net_excess_return"] == pytest.approx(0.09 * .999 / 1.001)
    assert len(value["price_series_sha256"]) == 64


def test_next_bar_requires_exact_common_slot_and_never_shifts(tmp_path):
    day = date(2026, 9, 28)
    decision, target = _at(day, 13, 32), _at(day, 13, 35)
    daily = [_daily("AAPL", day, 99, 110), _daily("SPY", day, 199, 202)]
    later = [_intraday("AAPL", target + timedelta(minutes=5), 101),
             _intraday("SPY", target + timedelta(minutes=5), 201)]
    pending = report.make_label(
        decided_at=decision, labelled_at=_at(day, 23), security_id="AAPL", horizon=1,
        entry_basis="next_bar", daily_rows=daily, intraday_rows=later,
    )
    assert pending["status"] == "pending"
    confirmation, observed = _confirmation(day)
    con = _missing_db(tmp_path / "bar.duckdb", day, observed)
    unavailable = report.make_label(
        decided_at=decision, labelled_at=_at(observed, 23), security_id="AAPL", horizon=1,
        entry_basis="next_bar", daily_rows=daily, intraday_rows=later,
        missing_confirmation=confirmation, verification_con=con,
    )
    assert unavailable["status"] == "unavailable"
    assert unavailable["reason"] == "missing_exact_entry"
    assert unavailable["entry_at"] == pending["entry_at"]
    con.close()
    exact = [_intraday("AAPL", target, 100), _intraday("SPY", target, 200)]
    available = report.make_label(
        decided_at=decision, labelled_at=_at(day, 23), security_id="AAPL", horizon=1,
        entry_basis="next_bar", daily_rows=daily, intraday_rows=exact,
    )
    assert available["status"] == "available"
    assert available["entry_at"] == target.isoformat()
    assert available["next_session_bar"] is False
    preopen = _at(day, 12)
    opening = _at(day, 13, 30)
    preopen_label = report.make_label(
        decided_at=preopen, labelled_at=_at(day, 23), security_id="AAPL", horizon=1,
        entry_basis="next_bar", daily_rows=daily,
        intraday_rows=[_intraday("AAPL", opening, 100), _intraday("SPY", opening, 200)],
    )
    assert preopen_label["next_session_bar"] is True

    invalid_interval = [{**exact[0], "interval": "1m"}, exact[1]]
    with pytest.raises(ValueError, match="intraday provenance"):
        report.make_label(
            decided_at=decision, labelled_at=_at(day, 23), security_id="AAPL", horizon=1,
            entry_basis="next_bar", daily_rows=daily, intraday_rows=invalid_interval,
        )
    tampered = [{**exact[0], "open": 1_000}, exact[1]]
    with pytest.raises(ValueError, match="identity"):
        report.make_label(
            decided_at=decision, labelled_at=_at(day, 23), security_id="AAPL", horizon=1,
            entry_basis="next_bar", daily_rows=daily, intraday_rows=tampered,
        )


@pytest.mark.parametrize("security_id", ["AAPL", "SPY"])
def test_next_bar_requires_compatible_entry_and_exit_basis_per_leg(security_id):
    day = date(2026, 9, 28)
    decision, target = _at(day, 13, 32), _at(day, 13, 35)
    daily = [_daily("AAPL", day, 99, 110), _daily("SPY", day, 199, 202)]
    intraday = [_intraday("AAPL", target, 100), _intraday("SPY", target, 200)]
    index = 0 if security_id == "AAPL" else 1
    changed = {key: value for key, value in daily[index].items() if key != "row_sha256"}
    changed.update(price_basis="raw", corporate_action_status="none")
    daily[index] = {**changed, "row_sha256": canonical_sha256(changed)}
    value = report.make_label(
        decided_at=decision, labelled_at=_at(day, 23), security_id="AAPL", horizon=1,
        entry_basis="next_bar", daily_rows=daily, intraday_rows=intraday,
    )
    assert value["status"] == "unavailable"
    assert value["reason"] == "incompatible_price_basis"


def test_missing_exit_waits_then_uses_last_common_real_close(tmp_path):
    decision = datetime(2026, 9, 25, 20, tzinfo=timezone.utc)
    days = _session_days(date(2026, 9, 28), 5)
    rows = []
    for index, day in enumerate(days[:-1]):
        rows.extend((_daily("AAPL", day, 100 + index, 101 + index),
                     _daily("SPY", day, 200 + index, 201 + index)))
    pending = report.make_label(
        decided_at=decision, labelled_at=_at(days[-1]), security_id="AAPL", horizon=5,
        entry_basis="next_session_open", daily_rows=rows,
    )
    assert pending["status"] == "pending"
    empty = db.connect(tmp_path / "empty.duckdb")
    early = report.make_label(
        decided_at=decision, labelled_at=_at(days[-1]), security_id="AAPL", horizon=5,
        entry_basis="next_session_open", daily_rows=rows,
        missing_confirmation={"method": "recorded_fetch_attempt",
                              "observed_through": days[-1].isoformat()},
        verification_con=empty,
    )
    empty.close()
    assert early["status"] == "pending"
    confirmation, observed = _confirmation(days[-1])
    con = _missing_db(tmp_path / "exit.duckdb", days[-1], observed)
    terminal = report.make_label(
        decided_at=decision, labelled_at=_at(observed, 23), security_id="AAPL", horizon=5,
        entry_basis="next_session_open", daily_rows=rows,
        missing_confirmation=confirmation, verification_con=con,
    )
    assert terminal["status"] == "available"
    assert terminal["exit_date"] == days[-2].isoformat()
    assert terminal["missing_bar_status"] == "last_available_close"
    assert len(terminal["missing_confirmation_sha256"]) == 64
    con.close()


def test_missing_evidence_must_postdate_the_missing_session(tmp_path):
    decision = datetime(2026, 9, 25, 20, tzinfo=timezone.utc)
    missing_day = date(2026, 9, 28)
    confirmation, observed = _confirmation(missing_day)
    con = _missing_db(
        tmp_path / "predated.duckdb", missing_day, observed,
        attempted=date(2026, 9, 1),
    )
    value = report.make_label(
        decided_at=decision, labelled_at=_at(observed, 23), security_id="AAPL", horizon=1,
        entry_basis="next_session_open", daily_rows=(),
        missing_confirmation=confirmation, verification_con=con,
    )
    assert value["status"] == "pending"
    con.close()


def test_daily_price_ingestion_cannot_precede_availability():
    day = date(2026, 9, 28)
    bad = _daily("AAPL", day, 100, 101)
    bad["ingested_at"] = (datetime.fromisoformat(bad["available_at"])
                          - timedelta(seconds=1)).isoformat()
    identity = {key: value for key, value in bad.items() if key != "row_sha256"}
    bad["row_sha256"] = canonical_sha256(identity)
    with pytest.raises(ValueError, match="not mature"):
        report.make_label(
            decided_at=datetime(2026, 9, 25, 20, tzinfo=timezone.utc),
            labelled_at=_at(day, 23), security_id="AAPL", horizon=1,
            entry_basis="next_session_open", daily_rows=[bad, _daily("SPY", day, 200, 201)],
        )


def _report_row(index, *, eps=True, available=True, accepted_offset=0):
    session = "2026-09-28"
    value = float(index)
    return {"cik": f"{index:010d}", "issuer_id": f"sec-cik:{index:010d}",
            "accession": f"a-{index}-{accepted_offset}",
            "security_id": f"S{index}", "primary_security_id": f"S{index}",
            "accepted_at": f"2026-09-27T12:{index + accepted_offset:02d}:00+00:00",
            "eligible_at": f"2026-09-27T12:{index + accepted_offset:02d}:30+00:00",
            "decided_at": f"2026-09-27T13:{index:02d}:00+00:00",
            "expected_excess_bp_5": value, "expected_excess_bp_10": value * 2,
            "tone": value / 10,
            "eps_yoy_sign": ([1, 1, 0, -1, -1, None][index] if eps else None),
            "counterpart_known_at": "2026-09-27T12:00:00+00:00",
            "acceptance_to_discovery_ms": index * 100,
            "discovery_to_bundle_ms": index * 200,
            "acceptance_to_retrieval_ms": index * 500,
            "queue_delay_ms": index * 300, "model_latency_ms": index * 400,
            "retrieval_latency_ms": index * 1_000, "states": ["parsed", "scored"],
            "deterministic_event_kind": "earnings", "model_event_kind": "earnings",
            "item": "2.02", "exhibit_status": "ex99_1",
            "company_reported_consensus": False, "liquidity_tier": "large",
            "truncated": False, "latency_bucket": "<=60", "guidance_change": "none",
            "headline_surprise": "unknown", "consensus_surprise": "beat",
            "deterministic_guidance_change": "none",
            "label": {"status": "available" if available else "unavailable",
                      "entry_session": session, "horizon": 5,
                      "entry_basis": "next_session_open", "net_excess_return": value / 100,
                      "labelled_at": "2026-09-27T23:00:00+00:00",
                      "missing_bar_status": "complete"}}


def test_report_uses_first_primary_row_and_exact_paired_intersection():
    rows = [_report_row(index) for index in range(6)]
    duplicate = {**_report_row(0, available=True, accepted_offset=20),
                 "expected_excess_bp_5": -1_000,
                 "label": {**_report_row(0)["label"], "net_excess_return": 10.0}}
    result = report.filing_report(
        [*rows, duplicate], horizon=5, basis="next_session_open",
        generated_at=datetime(2026, 9, 28, tzinfo=timezone.utc), sec_status="unconfigured",
    )
    assert result["primary_count"] == 6 and result["supplemental_count"] == 1
    assert result["daily"][0]["model_all_ic"] == pytest.approx(1)
    assert result["daily"][0]["model_paired_ic"] == pytest.approx(1)
    assert result["daily"][0]["eps_paired_ic"] < 0
    assert result["daily"][0]["paired_excluded"] == 1
    assert result["counts"]["parsed"] == 7 and result["counts"]["scored"] == 7
    assert result["counts"]["unavailable"] == 0
    assert result["factor_neutral"] == {"status": "unavailable"}
    assert "paired_difference" in result["by_deterministic_event_kind"]["earnings"]
    assert "unknown|beat" in result["secondary"]["counterpart_cross"]
    assert result["daily"][0]["counts"]["parsed"] == 6
    assert result["by_deterministic_event_kind"]["earnings"]["daily"][0][
        "counts"
    ]["scored"] == 6
    assert result["latencies"]["discovery_to_bundle"]["count"] == 7


def test_first_filing_selection_happens_before_label_availability():
    first = _report_row(0, available=False)
    later = {**_report_row(0, accepted_offset=20), "label": _report_row(0)["label"]}
    result = report.filing_report(
        [first, later, *[_report_row(index) for index in range(1, 6)]],
        horizon=5, basis="next_session_open",
        generated_at=datetime(2026, 9, 28, tzinfo=timezone.utc), sec_status="ready",
    )
    assert result["primary_count"] == 6 and result["supplemental_count"] == 1
    assert result["daily"][0]["model_count"] == 5
    assert result["daily"][0]["model_all_ic"] == pytest.approx(1)


def test_report_separates_lifecycle_rows_bases_and_future_labels():
    rows = [_report_row(index) for index in range(6)]
    rows[0] = {**rows[0], "label": {**rows[0]["label"],
                                     "labelled_at": "2026-09-29T00:00:00+00:00"}}
    other_basis = {**_report_row(0), "label": {**_report_row(0)["label"],
                                                "entry_basis": "next_bar"}}
    result = report.filing_report(
        [*rows, other_basis], horizon=5, basis="next_session_open",
        generated_at=datetime(2026, 9, 28, tzinfo=timezone.utc), sec_status="ready",
        lifecycle_rows=[{"event_at": "2026-09-27T10:00:00+00:00",
                         "states": ["queued", "capacity_unavailable", "sla_miss"],
                         "source_status": "capacity_unavailable"},
                        {"event_at": "2099-01-01T00:00:00+00:00", "states": ["queued"]}],
    )
    assert result["supplemental_count"] == 0
    assert result["daily"][0]["model_count"] == 5
    assert result["counts"]["queued"] == 1
    assert result["counts"]["parsed"] == 6
    assert result["counts"]["capacity_unavailable"] == 1
    assert result["counts"]["sla_miss"] == 1
    assert result["retrieval_sla"]["status"] == "censored_failures"
    assert result["retrieval_sla"]["p95_seconds"] is None
    assert result["retrieval_sla"]["conditional_success_p95_seconds"] == pytest.approx(4.75)
    assert result["retrieval_sla"]["denominator"] == 7
    assert result["source_completeness"]["capacity_unavailable"] == 1

    with pytest.raises(ValueError, match="duplicate"):
        report.filing_report(
            [rows[1], rows[1]], horizon=5, basis="next_session_open",
            generated_at=datetime(2026, 9, 28, tzinfo=timezone.utc), sec_status="ready",
        )


def test_sla_counts_timeout_and_past_due_work_as_failures():
    rows = [_report_row(index) for index in range(6)]
    lifecycle = [
        {"event_at": "2026-09-27T10:00:00+00:00", "states": ["unavailable"],
         "reason": "model_timeout", "source_status": "timeout"},
        {"event_at": "2026-09-27T11:00:00+00:00", "states": ["queued"],
         "deadline_at": "2026-09-27T11:05:00+00:00", "source_status": "pending"},
    ]
    result = report.filing_report(
        rows, horizon=5, basis="next_session_open",
        generated_at=datetime(2026, 9, 28, tzinfo=timezone.utc), sec_status="ready",
        lifecycle_rows=lifecycle,
    )
    assert result["counts"]["timeout"] == 1
    assert result["counts"]["sla_miss"] == 2
    assert result["retrieval_sla"]["failure_count"] == 2
    assert result["retrieval_sla"]["denominator"] == 8
    assert result["retrieval_sla"]["p95_seconds"] is None


def test_future_counterparts_are_hidden_from_all_outputs():
    rows = [{**_report_row(index), "counterpart_known_at": "2026-09-28T01:00:00+00:00"}
            for index in range(6)]
    result = report.filing_report(
        rows, horizon=5, basis="next_session_open",
        generated_at=datetime(2026, 9, 28, tzinfo=timezone.utc), sec_status="ready",
    )
    assert result["daily"][0]["paired_count"] == 0
    assert set(result["secondary"]["eps_baseline_category"]) == {"unavailable_at_decision"}
    assert set(result["secondary"]["counterpart_cross"]) == {"unavailable_at_decision"}


def test_sparse_slices_preserve_the_global_session_index():
    first = [_report_row(index) for index in range(6)]
    second = [{**_report_row(index), "accession": f"b-{index}",
               "deterministic_event_kind": "governance",
               "label": {**_report_row(index)["label"], "entry_session": "2026-09-30"}}
              for index in range(6)]
    result = report.filing_report(
        [*first, *second], horizon=5, basis="next_session_open",
        generated_at=datetime(2026, 9, 30, tzinfo=timezone.utc), sec_status="ready",
    )
    earnings = result["by_deterministic_event_kind"]["earnings"]["daily"]
    assert [row["entry_session"] for row in earnings] == [
        "2026-09-28", "2026-09-29", "2026-09-30",
    ]
    assert earnings[0]["model_all_ic"] == pytest.approx(1)
    assert earnings[1]["model_all_ic"] is None
    assert earnings[2]["model_all_ic"] is None
    assert result["secondary"]["size_tier"]["unknown"]["daily"] == pytest.approx(
        [0.025, None, 0.025]
    )


def test_report_gives_null_reason_and_event_kind_sensitivity():
    rows = [{**_report_row(index), "expected_excess_bp_5": 1.0}
            for index in range(6)]
    result = report.filing_report(
        rows, horizon=5, basis="next_session_open",
        generated_at=datetime(2026, 9, 28, tzinfo=timezone.utc), sec_status="ready",
    )
    assert result["daily"][0]["model_all_reason"] == "constant_score"
    assert result["by_deterministic_event_kind"]["earnings"]["daily"][0][
        "model_all_reason"
    ] == "constant_score"
    assert result["complete_bar_sensitivity"]["mean"] is None


def test_circular_session_interval_is_registered_and_deterministic():
    values = [(-1) ** index * (index + 1) / 100 for index in range(30)]
    first = report.circular_session_ci(values, horizon=5)
    second = report.circular_session_ci(values, horizon=5)
    assert first == second
    assert first["status"] == "available" and first["lower"] < first["upper"]
    assert report.circular_session_ci(values[:29], horizon=5)["status"] == "descriptive_only"
    with pytest.raises(ValueError, match="nonfinite"):
        report.circular_session_ci([*values, float("nan")], horizon=5)
