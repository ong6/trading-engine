"""Effective-dated IBKR Pro Tiered US stock and option costs.

Sources retrieved 2026-10-06:
- https://www.interactivebrokers.com/en/pricing/commissions-stocks.php
- https://www.interactivebrokers.com/en/accounts/fees/NYSEstkfees.php
- https://www.interactivebrokers.com/en/accounts/fees/INETstkfees.php
- https://www.interactivebrokers.com/en/pricing/commissions-options.php
- https://www.interactivebrokers.com/en/pricing/margin-rates.php
- https://www.interactivebrokers.com/campus/trading-lessons/short-selling-and-margin/
- https://www.sec.gov/rules-regulations/fee-rate-advisories/section-31-transaction-fee-rate-advisory-2026-2
- https://www.finra.org/rules-guidance/rule-filings/sr-finra-2026-020
- https://www.finra.org/rules-guidance/rule-filings/sr-finra-2026-021
- https://www.cboe.com/us/options/regulation/rule_filings/

The option exchange fee is explicitly an unverified conservative placeholder;
all other entries are the orchestrator's verified 2026-10-06 table. Components
remain unrounded and only their sum is rounded half-up to cents.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .profiles import CostProfile, FeeBreakdown, RateRow

_MIN_DATE = date.min
_PAUSE_START = date(2026, 10, 1)
_PAUSE_END = date(2026, 12, 31)
RATES = (
    RateRow("stock_commission_per_share", 0.0035, _MIN_DATE),
    RateRow("stock_commission_minimum", 0.35, _MIN_DATE),
    RateRow("fractional_commission_minimum", 0.01, _MIN_DATE),
    RateRow("stock_commission_value_cap", 0.01, _MIN_DATE),
    RateRow("opening_auction_per_share", 0.0015, _MIN_DATE),
    RateRow("closing_auction_per_share", 0.0016, _MIN_DATE),
    RateRow("remove_liquidity_per_share", 0.0030, _MIN_DATE),
    RateRow("add_liquidity_per_share", 0.0, _MIN_DATE),
    RateRow("stock_clearing_per_share", 0.00020, _MIN_DATE),
    RateRow("nyse_pass_through_fraction", 0.000175, _MIN_DATE),
    RateRow("finra_pass_through_fraction", 0.000565, _MIN_DATE),
    RateRow("stock_cat_per_share", 0.000003, _MIN_DATE),
    RateRow("sec_fraction", 0.0, _MIN_DATE, date(2026, 4, 3)),
    RateRow("sec_fraction", 0.0000206, date(2026, 4, 4)),
    RateRow("stock_taf_per_share", 0.000195, _MIN_DATE, date(2026, 9, 30)),
    RateRow("stock_taf_per_share", 0.0, _PAUSE_START, _PAUSE_END),
    RateRow("stock_taf_per_share", 0.000195, date(2027, 1, 1)),
    RateRow("stock_taf_cap", 9.79, _MIN_DATE),
    RateRow("borrow_annual_fraction", 0.0025, _MIN_DATE),
    RateRow("margin_benchmark_fraction", 0.0433, _MIN_DATE, date(2026, 10, 1)),
    RateRow("margin_benchmark_fraction", 0.0388, date(2026, 10, 2)),
    RateRow("margin_markup_fraction", 0.0150, _MIN_DATE),
    RateRow("option_commission_high", 0.65, _MIN_DATE),
    RateRow("option_commission_mid", 0.50, _MIN_DATE),
    RateRow("option_commission_low", 0.25, _MIN_DATE),
    RateRow("option_commission_minimum", 1.00, _MIN_DATE),
    RateRow("option_occ_per_contract", 0.025, _MIN_DATE),
    RateRow("option_orf_per_contract", 0.020, date(2026, 7, 1)),
    RateRow("option_exchange_per_contract", 0.30, _MIN_DATE),
    RateRow("option_cat_per_contract", 0.0003, _MIN_DATE),
    RateRow("option_taf_per_contract", 0.00329, _MIN_DATE, date(2026, 9, 30)),
    RateRow("option_taf_per_contract", 0.0, _PAUSE_START, _PAUSE_END),
    RateRow("option_taf_per_contract", 0.00329, date(2027, 1, 1)),
)


def _rate(component: str, session_date: date) -> float:
    matches = [row.rate for row in RATES if row.component == component and row.applies(session_date)]
    if len(matches) != 1:
        raise ValueError(f"no unique {component!r} rate for {session_date}")
    return matches[0]


def _round_usd(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _kind(instrument) -> str:
    if isinstance(instrument, str):
        return instrument
    if isinstance(instrument, dict):
        return str(instrument["kind"])
    return str(instrument.kind)


def _multiplier(instrument) -> float:
    if isinstance(instrument, str):
        return 100.0 if instrument == "option" else 1.0
    if isinstance(instrument, dict):
        return float(instrument.get("multiplier", 1.0))
    return float(instrument.multiplier)


def _sequence(value, count: int):
    if isinstance(value, Sequence) and not isinstance(value, str):
        if len(value) != count:
            raise ValueError("option leg fields must have the same length")
        return list(value)
    return [value] * count


def _instruments(instrument) -> list:
    if isinstance(instrument, Sequence) and not isinstance(instrument, (str, dict)):
        return list(instrument)
    return [instrument]


def _stock_charge(*, side: str, qty: float, price: float, fill_kind: str,
                  session_date: date, instrument) -> FeeBreakdown:
    shares = abs(float(qty))
    value = shares * float(price) * _multiplier(instrument)
    if not all(math.isfinite(number) and number > 0 for number in (shares, value)):
        raise ValueError("qty and price must be positive and finite")
    fractional = not shares.is_integer()
    commission = min(
        max(_rate("stock_commission_minimum", session_date),
            _rate("stock_commission_per_share", session_date) * shares),
        _rate("stock_commission_value_cap", session_date) * value,
    )
    if fractional:
        commission = max(
            _rate("fractional_commission_minimum", session_date), commission
        )
    exchange_component = {
        "moo": "opening_auction_per_share",
        "open_auction": "opening_auction_per_share",
        "next_open": "opening_auction_per_share",
        "limit_on_open": "opening_auction_per_share",
        "moc": "closing_auction_per_share",
        "close_auction": "closing_auction_per_share",
        "market": "remove_liquidity_per_share",
        "intraday_bar": "remove_liquidity_per_share",
        "limit": "add_liquidity_per_share",
        "limit_touch": "add_liquidity_per_share",
    }.get(fill_kind)
    if exchange_component is None:
        raise ValueError(f"unknown stock fill kind {fill_kind!r}")
    exchange = _rate(exchange_component, session_date) * shares
    clearing = _rate("stock_clearing_per_share", session_date) * shares
    pass_through = commission * (
        _rate("nyse_pass_through_fraction", session_date)
        + _rate("finra_pass_through_fraction", session_date)
    )
    cat = _rate("stock_cat_per_share", session_date) * shares
    sale = side in {"sell", "short"}
    sec = value * _rate("sec_fraction", session_date) if sale else 0.0
    taf = min(
        shares * _rate("stock_taf_per_share", session_date),
        _rate("stock_taf_cap", session_date),
    ) if sale else 0.0
    total = commission + exchange + clearing + pass_through + cat + sec + taf
    return FeeBreakdown(
        "ibkr_pro_tiered_v1", commission, exchange, clearing, pass_through,
        cat, sec, taf, total_usd=_round_usd(total),
    )


def _option_charge(*, side, qty, price, session_date: date, instrument) -> FeeBreakdown:
    instruments = _instruments(instrument)
    sides = _sequence(side, len(instruments))
    quantities = _sequence(qty, len(instruments))
    prices = _sequence(price, len(instruments))
    commission = sec = taf = 0.0
    contracts = 0.0
    for leg_side, leg_qty, premium, leg_instrument in zip(
        sides, quantities, prices, instruments, strict=True,
    ):
        leg_contracts = abs(float(leg_qty))
        premium = float(premium)
        if not all(math.isfinite(number) and number > 0
                   for number in (leg_contracts, premium)):
            raise ValueError("option qty and premium must be positive and finite")
        if _kind(leg_instrument) != "option":
            raise ValueError("a combo cannot mix instrument kinds")
        contracts += leg_contracts
        tier = (
            "option_commission_high" if premium >= 0.10
            else "option_commission_mid" if premium >= 0.05
            else "option_commission_low"
        )
        commission += _rate(tier, session_date) * leg_contracts
        if leg_side in {"sell", "short"}:
            value = leg_contracts * premium * _multiplier(leg_instrument)
            sec += value * _rate("sec_fraction", session_date)
            taf += leg_contracts * _rate("option_taf_per_contract", session_date)
    commission = max(commission, _rate("option_commission_minimum", session_date))
    exchange = contracts * _rate("option_exchange_per_contract", session_date)
    occ = contracts * _rate("option_occ_per_contract", session_date)
    orf = contracts * _rate("option_orf_per_contract", session_date)
    cat = contracts * _rate("option_cat_per_contract", session_date)
    taf = min(taf, _rate("stock_taf_cap", session_date))
    total = commission + exchange + cat + sec + taf + occ + orf
    return FeeBreakdown(
        "ibkr_pro_tiered_v1", commission, exchange, cat_fee=cat,
        sec_fee=sec, finra_taf=taf, occ_fee=occ, orf_fee=orf,
        total_usd=_round_usd(total),
    )


def charge(*, side, qty, price, fill_kind: str, instrument,
           session_date: date) -> FeeBreakdown:
    instruments = _instruments(instrument)
    kinds = {_kind(value) for value in instruments}
    if kinds <= {"stock", "etf"} and len(instruments) == 1:
        return _stock_charge(
            side=str(side), qty=float(qty), price=float(price), fill_kind=fill_kind,
            session_date=session_date, instrument=instruments[0],
        )
    if kinds == {"option"}:
        return _option_charge(
            side=side, qty=qty, price=price, session_date=session_date,
            instrument=instruments,
        )
    raise ValueError(f"unsupported instrument kinds: {sorted(kinds)}")


def borrow_fee(short_market_value: float, days: int = 1, *,
               session_date: date) -> float:
    if not math.isfinite(short_market_value) or short_market_value < 0 or days < 0:
        raise ValueError("short market value and days must be non-negative")
    return short_market_value * _rate("borrow_annual_fraction", session_date) * days / 360


def margin_interest(debit: float, days: int = 1, *, session_date: date) -> float:
    if not math.isfinite(debit) or debit < 0 or days < 0:
        raise ValueError("debit and days must be non-negative")
    annual = (
        _rate("margin_benchmark_fraction", session_date)
        + _rate("margin_markup_fraction", session_date)
    )
    return debit * annual * days / 360


PROFILE = CostProfile(
    id="ibkr_pro_tiered_v1",
    description="IBKR Pro Tiered US stock/ETF and option fees verified 2026-10-06.",
    rates=RATES,
    verified={
        "retrieved": "2026-10-06",
        "option_exchange_fee": "unverified conservative placeholder",
        "margin_benchmark_before_2026-10-02": "unverified best-known 4.33%",
        "source": "P22 VERIFIED FEE TABLE",
    },
    calculator=charge,
)
