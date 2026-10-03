from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from farm.study.audit import (
    AuditContract,
    AuditExecutionError,
    AuditListing,
    AuditSnapshot,
    Availability,
    InputRequirement,
    audit_study,
    prior_sessions,
)
from farm.study.data import Bar

DAY = date(2024, 3, 28)
NY = ZoneInfo("America/New_York")


def bar(ticker, day, close=10, volume=1000):
    return Bar(ticker, day, close, close, close, close, volume)


def fixture(names=("SEEN", "OMITTED"), **contract_kwargs):
    days = prior_sessions(DAY, 60)
    rows = tuple(bar(t, d) for t in names for d in days)
    listings = tuple(AuditListing(t, days[0]) for t in names)
    reference = AuditSnapshot("independent", rows, listings=listings)
    audited = AuditSnapshot("audited", rows)
    contract = AuditContract("fictional-study", (DAY,), DAY, **contract_kwargs)
    return contract, audited, reference


def row(report):
    return report["sessions"][0]


def test_complete_population_and_bins_are_independent_and_deterministic():
    contract, audited, reference = fixture()
    report = audit_study(contract, audited, reference)
    assert report["decision"] == "supported"
    assert row(report)["base_membership"] == row(report)["expected"] == 2
    assert row(report)["complete_inputs"] == 2 and row(report)["coverage"] == 1
    assert row(report)["bins"]["below_1000000"]["expected"] == 2
    assert report == audit_study(contract, audited, reference)
    assert audited.sha256 == replace(audited, bars=audited.bars[::-1]).sha256
    assert report["checks"]["actions"]["status"] == "not_applicable"
    with pytest.raises(FrozenInstanceError):
        audited.source = "changed"


def test_wholly_omitted_and_missing_warmup_never_shrink_expected():
    contract, audited, reference = fixture(requirements=(InputRequirement(lookback=60),))
    audited = replace(audited, bars=tuple(b for b in audited.bars if b.ticker == "SEEN")[:-1])
    report = audit_study(contract, audited, reference)
    assert row(report)["expected"] == 2
    assert row(report)["missing_inputs"] == 2
    assert report["decision"] == "unusable"
    assert report["finding_summary"]["reason_counts"] == {"missing": 2}


def test_sparse_reference_calendar_does_not_pull_older_observations():
    contract, audited, reference = fixture(names=("SEEN",))
    old = prior_sessions(DAY, 61)[0]
    reference = replace(reference, bars=(bar("SEEN", old, 100), *reference.bars[1:]))
    result = audit_study(contract, audited, reference)
    assert row(result)["expected"] == 0
    assert row(result)["unresolved_eligibility"] == 1
    assert row(result)["coverage"] is None
    assert result["decision"] == "limited"
    assert row(result)["bins"]["unknown_liquidity"]["unresolved_eligibility"] == 1


def test_unresolved_member_cannot_be_hidden_by_known_subset_ratio():
    contract, audited, reference = fixture()
    reference = replace(reference, bars=tuple(b for b in reference.bars if b.ticker == "SEEN"))
    report = audit_study(contract, audited, reference)
    assert row(report)["known_subset_coverage"] == 1
    assert row(report)["coverage"] is None
    assert row(report)["unresolved_eligibility"] == 1
    assert report["decision"] == "limited"
    missing = replace(audited, bars=())
    assert audit_study(contract, missing, reference)["decision"] == "unusable"


def test_unknown_reference_membership_and_reused_ticker_are_retained():
    contract, audited, reference = fixture(names=("SEEN",))
    report = audit_study(contract, audited, replace(reference, membership_complete=False))
    assert report["decision"] == "limited"
    assert row(report)["coverage"] is None and row(report)["known_subset_coverage"] == 1
    assert all(counts["coverage"] is None for counts in row(report)["bins"].values())
    duplicate = replace(reference, listings=reference.listings * 2)
    report = audit_study(contract, audited, duplicate)
    assert row(report)["unresolved_eligibility"] == 1
    assert report["checks"]["identity"]["status"] == "unknown"
    unavailable = replace(reference, membership_basis="observed_source")
    assert audit_study(contract, audited, unavailable)["decision"] == "limited"


def test_empty_known_population_has_null_ratio_and_explicit_reason():
    contract, audited, reference = fixture(min_price=100)
    report = audit_study(contract, audited, reference)
    assert row(report)["base_membership"] == 2 and row(report)["ineligible"] == 2
    assert row(report)["expected"] == 0 and row(report)["coverage"] is None
    assert row(report)["coverage_reason"] == "empty_expected_population"
    assert report["decision"] == "limited"


def test_precedence_and_supplemental_findings_survive_sample_limit():
    contract, audited, reference = fixture(evidence_limit=0)
    previous = prior_sessions(DAY, 1)[0]
    bad = tuple(replace(b, close=-1) if b.session == previous else b for b in audited.bars)
    late = tuple(Availability(t, previous, "close", datetime(2024, 3, 28, 12, tzinfo=NY))
                 for t in ("SEEN", "OMITTED"))
    report = audit_study(contract, replace(audited, bars=bad, availability=late), reference)
    assert row(report)["invalid_inputs"] == 2 and row(report)["late_inputs"] == 0
    assert report["checks"]["availability"]["status"] == "fail"
    assert report["evidence"]["rows"] == report["findings"] == []
    assert report["finding_summary"] == {"total": 2, "displayed": 0, "truncated": True,
                                         "reason_counts": {"invalid": 2, "late": 2}}


def test_observed_publication_required_is_unknown_without_metadata():
    contract, audited, reference = fixture(availability_basis="observed_source")
    observed = tuple(Availability(b.ticker, b.session, field,
                                 datetime.combine(b.session, datetime.min.time(), NY) + timedelta(hours=17))
                     for b in reference.bars for field in ("close", "volume"))
    reference = replace(reference, availability=observed)
    result = audit_study(contract, audited, reference)
    assert row(result)["expected"] == 2 and row(result)["unknown_inputs"] == 2
    assert result["checks"]["availability"]["status"] == "unknown"
    assert result["decision"] == "limited"


def test_same_session_observed_timestamp_cannot_authorize_future_close():
    contract, audited, reference = fixture(requirements=(InputRequirement("close", offset=0),))
    audited = replace(audited, bars=(*audited.bars, *(bar(t, DAY) for t in ("SEEN", "OMITTED"))),
                      availability=tuple(Availability(t, DAY, "close", datetime(2024, 3, 28, 9, tzinfo=NY))
                                         for t in ("SEEN", "OMITTED")))
    report = audit_study(contract, audited, reference)
    assert row(report)["late_inputs"] == 2 and report["decision"] == "unusable"


def test_open_permission_and_future_ohlc_cannot_change_earlier_signal_coverage():
    contract, audited, reference = fixture(requirements=(InputRequirement("open", offset=0),),
                                           decision_time="at_open")
    audited = replace(audited, bars=(*audited.bars, *(bar(t, DAY) for t in ("SEEN", "OMITTED"))))
    assert row(audit_study(contract, audited, reference))["late_inputs"] == 2
    contract = replace(contract, open_as_indication=True)
    before = audit_study(contract, audited, reference)
    mutated = replace(audited, bars=tuple(replace(b, high=1, close=-100) if b.session == DAY else b
                                        for b in audited.bars))
    after = audit_study(contract, mutated, reference)
    assert row(before) == row(after)
    assert before["decision"] == after["decision"] == "supported"
    assert before["audit_id"] != after["audit_id"]


def test_source_clock_mutation_never_changes_reference_denominator():
    contract, audited, reference = fixture()
    baseline = audit_study(contract, audited, reference)
    changed = audit_study(contract, replace(audited, timezone="UTC", session_open="23:59"), reference)
    assert row(changed)["expected"] == row(baseline)["expected"] == 2
    assert changed["audit_id"] != baseline["audit_id"]


@pytest.mark.parametrize("day,utc_hour", [(date(2024, 3, 8), 21), (date(2024, 3, 11), 20),
                                         (date(2024, 11, 29), 18)])
def test_dst_early_close_and_equality_use_native_market_clock(day, utc_hour):
    previous = prior_sessions(day, 1)[0]
    rows = (bar("SEEN", previous), bar("SEEN", day))
    reference = AuditSnapshot("reference", rows, listings=(AuditListing("SEEN", previous),))
    contract = AuditContract("clock", (day,), day, requirements=(InputRequirement("close", offset=0),),
                             decision_time="at_close", close_as_indication=True, window_sessions=1, min_history=1)
    exact = datetime(day.year, day.month, day.day, utc_hour, tzinfo=timezone.utc)
    audited = AuditSnapshot("audited", rows, availability=(Availability("SEEN", day, "close", exact),))
    assert row(audit_study(contract, audited, reference))["complete_inputs"] == 1
    audited = replace(audited, availability=(Availability("SEEN", day, "close", exact + timedelta(microseconds=1)),))
    assert row(audit_study(contract, audited, reference))["late_inputs"] == 1


def test_future_only_mutation_changes_identity_but_no_signal_measurement():
    contract, audited, reference = fixture()
    first = audit_study(contract, audited, reference)
    future = replace(audited, bars=(*audited.bars, bar("SEEN", date(2024, 4, 1), 123)))
    second = audit_study(contract, future, reference)
    assert first["sessions"] == second["sessions"]
    assert first["audit_id"] != second["audit_id"]
    assert audited.sha256 != replace(audited, daily_bar_lag_seconds=1).sha256
    assert first["audit_id"] != audit_study(replace(contract, study_run_id="external-run"), audited, reference)["audit_id"]


def test_declared_basis_mismatch_is_blocking_and_unsupported_checks_unknown():
    contract, audited, reference = fixture()
    assert audit_study(contract, replace(audited, price_basis="split_adjusted"), reference)["decision"] == "unusable"
    for check in ("actions", "revisions", "field_trace", "outcomes"):
        result = audit_study(replace(contract, required_checks=("coverage", "eligibility", check)), audited, reference)
        assert result["checks"][check]["status"] == "unknown" and result["decision"] == "limited"


def test_bin_gap_blocks_even_when_aggregate_threshold_passes():
    contract, audited, reference = fixture(names=("A", "B", "C", "D"), coverage_threshold=0.7,
                                           liquidity_bins=(100_000,))
    reference = replace(reference, bars=tuple(replace(b, volume=20_000) if b.ticker == "D" else b for b in reference.bars))
    audited = replace(audited, bars=tuple(b for b in audited.bars if b.ticker != "D"))
    report = audit_study(contract, audited, reference)
    assert row(report)["coverage"] == 0.75
    assert row(report)["bins"]["at_least_100000"]["coverage"] == 0
    assert report["decision"] == "unusable"


def test_execution_errors_have_no_decision_and_raw_duplicates_cannot_disappear():
    contract, audited, reference = fixture()
    with pytest.raises(AuditExecutionError, match="duplicate"):
        replace(audited, bars=(*audited.bars, audited.bars[0]))
    with pytest.raises(AuditExecutionError, match="hash") as failure:
        replace(audited, snapshot_sha256="0" * 64)
    assert "decision" not in failure.value.as_dict()
    for change in ({"hard_max_date": DAY - timedelta(days=1)}, {"sessions": (date(2024, 3, 29),)},
                   {"coverage_threshold": float("nan")}, {"schema_version": True}):
        with pytest.raises(AuditExecutionError):
            replace(contract, **change)
    with pytest.raises(AuditExecutionError):
        AuditContract.from_dict({**contract.canonical(), "typo": True})
    with pytest.raises(AuditExecutionError):
        replace(audited, bars=(replace(audited.bars[0], close=float("inf")),))
    with pytest.raises(AuditExecutionError):
        InputRequirement(field=[])
    with pytest.raises(AuditExecutionError):
        replace(audited, timezone=None)


def test_reference_dollar_volume_overflow_is_unresolved_not_nonfinite_output():
    contract, audited, reference = fixture(names=("SEEN",))
    reference = replace(reference, bars=tuple(replace(b, close=1e308, volume=1e308) for b in reference.bars))
    result = audit_study(contract, audited, reference)
    assert row(result)["unresolved_eligibility"] == 1
    assert result["decision"] == "limited"


def test_native_outcome_counts_preserve_terminal_zero_and_never_certify_quality():
    contract, audited, reference = fixture()
    ledger = {"schema_version": 1, "kind": "event", "trades": [{
        "ticker": "SEEN", "side": "long", "entry_session": DAY.isoformat(), "exit_session": DAY.isoformat(),
        "entry_price": 10, "exit_price": 0, "notional": 100, "flags": ["delisting_fallback"]}],
        "rejected_orders": [], "unfilled_orders": [{"ticker": "OMITTED", "session": DAY.isoformat(),
                                                      "reason": "missing_entry_bar"}], "open_positions": []}
    report = audit_study(contract, audited, reference, outcomes=ledger)
    assert report["outcomes"]["recorded_attempts"] == 2
    assert report["outcomes"]["terminal_zero_trades"] == 1
    assert report["outcomes"]["exclusion_reasons"] == {"missing_entry_bar": 1}
    required = replace(contract, required_checks=("coverage", "eligibility", "outcomes"))
    assert audit_study(required, audited, reference, outcomes=ledger)["decision"] == "limited"
    for malformed in ({**ledger, "schema_version": 999}, {**ledger, "trades": [5]},
                      {**ledger, "trades": [{}]}):
        with pytest.raises(AuditExecutionError):
            audit_study(contract, audited, reference, outcomes=malformed)


def test_named_market_clocks_preserve_instant_under_contract_timezone_conversion():
    contract, audited, reference = fixture(requirements=(InputRequirement("open", offset=0),),
                                           decision_time="at_open", open_as_indication=True)
    audited = replace(audited, bars=(*audited.bars, *(bar(t, DAY) for t in ("SEEN", "OMITTED"))))
    ny = audit_study(contract, audited, reference)
    utc = audit_study(replace(contract, timezone="UTC"), audited, reference)
    assert ny["sessions"] == utc["sessions"]
    assert ny["decision"] == utc["decision"] == "supported"


def test_same_close_indication_requires_explicit_permission():
    contract, audited, reference = fixture(requirements=(InputRequirement("close", offset=0),),
                                           decision_time="at_close")
    audited = replace(audited, bars=(*audited.bars, *(bar(t, DAY) for t in ("SEEN", "OMITTED"))))
    assert row(audit_study(contract, audited, reference))["late_inputs"] == 2
    assert audit_study(replace(contract, close_as_indication=True), audited, reference)["decision"] == "supported"
