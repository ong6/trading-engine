"""Authoritative P22 verified fee examples and compatibility profile."""
from __future__ import annotations

from datetime import date

import pytest

from engine.instruments import Instrument
from engine.lib.provenance import canonical_sha256
from farm.study import costs as study_costs
from sim.costs import (
    IBKR_PRO_TIERED_V1,
    borrow_fee,
    charge,
    margin_interest,
    resolve_profile,
)

OCTOBER = date(2026, 10, 12)
STOCK = Instrument("XYZ", "stock", 1.0)


@pytest.mark.parametrize(
    "side,qty,price,fill_kind,session_date,total",
    [
        ("buy", 300, 5.00, "moo", OCTOBER, 1.56),
        ("buy", 10, 300.00, "moo", OCTOBER, 0.37),
        ("sell", 1_000, 2.00, "market", OCTOBER, 6.75),
        ("sell", 1_000, 2.00, "market", date(2027, 1, 4), 6.94),
        ("buy", 10, 0.20, "moo", OCTOBER, 0.04),
        ("sell", 1_000, 2.00, "market", date(2026, 3, 2), 6.90),
    ],
)
def test_verified_stock_examples(side, qty, price, fill_kind, session_date, total):
    fees = charge(
        "ibkr_pro_tiered_v1", side=side, qty=qty, price=price,
        fill_kind=fill_kind, instrument=STOCK, session_date=session_date,
    )
    assert fees.total_usd == total
    assert charge(
        "baseline_v1", side=side, qty=qty, price=price,
        fill_kind=fill_kind, instrument=STOCK, session_date=session_date,
    ).total_usd == 0


def test_verified_effective_dates_and_unrounded_components():
    paused = charge(
        "ibkr_pro_tiered_v1", side="sell", qty=1_000, price=2,
        fill_kind="market", instrument=STOCK, session_date=OCTOBER,
    )
    resumed = charge(
        "ibkr_pro_tiered_v1", side="sell", qty=1_000, price=2,
        fill_kind="market", instrument=STOCK, session_date=date(2027, 1, 4),
    )
    before_sec = charge(
        "ibkr_pro_tiered_v1", side="sell", qty=1_000, price=2,
        fill_kind="market", instrument=STOCK, session_date=date(2026, 3, 2),
    )
    assert paused.finra_taf == 0 and resumed.finra_taf == pytest.approx(0.195)
    assert paused.sec_fee == pytest.approx(0.0412) and before_sec.sec_fee == 0
    assert paused.pass_through == pytest.approx(0.00259)
    assert paused.cat_fee == pytest.approx(0.003)


def test_commission_cap_below_minimum_and_taf_cap():
    cheap = charge(
        "ibkr_pro_tiered_v1", side="buy", qty=10, price=0.20,
        fill_kind="moo", instrument=STOCK, session_date=OCTOBER,
    )
    capped = charge(
        "ibkr_pro_tiered_v1", side="sell", qty=100_000, price=2,
        fill_kind="market", instrument=STOCK, session_date=date(2027, 1, 4),
    )
    assert cheap.commission == pytest.approx(0.02)
    assert capped.finra_taf == pytest.approx(9.79)


def test_verified_borrow_and_margin_examples():
    assert borrow_fee(5_000, 10, session_date=OCTOBER) == 0.35
    assert margin_interest(2_000, 30, session_date=OCTOBER) == 8.97
    assert borrow_fee(5_000, 10, session_date=OCTOBER, profile="baseline_v1") == 0
    assert margin_interest(2_000, 30, session_date=OCTOBER, profile="baseline_v1") == 0


def test_verified_option_combo_example_and_baseline():
    call_long = Instrument(
        "XYZ261218C00002500", "option", 100, "XYZ", date(2026, 12, 18), 2.5, "C",
    )
    call_short = Instrument(
        "XYZ261218C00001200", "option", 100, "XYZ", date(2026, 12, 18), 1.2, "C",
    )
    kwargs = {
        "side": ["buy", "sell"],
        "qty": [1, 1],
        "price": [2.50, 1.20],
        "fill_kind": "market",
        "instrument": [call_long, call_short],
        "session_date": OCTOBER,
    }
    fees = charge("ibkr_pro_tiered_v1", **kwargs)
    assert fees.commission == pytest.approx(1.30)
    assert fees.occ_fee == pytest.approx(0.05)
    assert fees.orf_fee == pytest.approx(0.04)
    assert fees.cat_fee == pytest.approx(0.0006)
    assert fees.sec_fee == pytest.approx(0.002472)
    assert fees.finra_taf == 0
    assert fees.total_usd == 1.99
    assert charge("baseline_v1", **kwargs).total_usd == 0


def test_profile_payload_identity_is_stable_and_study_wrapper_delegates():
    profile = resolve_profile("ibkr_pro_tiered_v1")
    assert profile is IBKR_PRO_TIERED_V1
    assert profile.sha256 == canonical_sha256(profile.payload)
    assert all(
        set(row) == {"component", "rate", "effective_from", "effective_to"}
        for row in profile.payload["rates"]
    )
    study = study_costs.calculate(
        "ibkr_pro_tiered_v1", side="buy", notional=1_500, fill_price=5,
        session_date=OCTOBER, fill_kind="moo",
    )
    assert study.total == 1.56
    assert study_costs.resolve("ibkr_pro_tiered_v1").payload == profile.payload
