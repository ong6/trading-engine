"""The fill model — honest by design (execution design §2).

An order created from a close-of-day-t signal fills at the day t+1 OPEN. There
are **no same-bar fills, ever**: ``fill_date > signal_date`` is enforced in
exactly one place (``attempt_fill``) and is the single look-ahead guard. The
guard raises unconditionally, including when Python runs with optimization.

The historical compatibility profile, ``baseline_v1``, uses:

    slippage_bps = max(half_spread_bps, 5) + 5          # +5/side = 10bp round-trip

    half_spread_bps (from 60-bar median dollar volume, conservative tiers):
        >= $50M -> 5 bp
        >= $20M -> 10 bp
        >= $5M  -> 15 bp
        else    -> 25 bp

    buys  fill at open * (1 + slippage_bps/1e4)
    sells fill at open * (1 - slippage_bps/1e4)

Other named profiles may change spread, adverse movement, participation impact,
fees, and the capacity ceiling; their full payload is serialized in research
artifacts. Under ``baseline_v1``, order notional (qty * open) may not exceed 1% of the name's
60-bar median daily dollar volume → the order is REJECTED (partial fills are not
modeled in v1). If the fill-date bar is missing (halt / delisting), has a non-positive open,
or printed zero volume (nobody traded — dead quotes from the feed look exactly
like this) the order stays pending; after 3 trading days with still no
tradeable bar it rejects as 'no_bar'. A bar is never invented.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import duckdb

from engine.lib.data_quality import trusted_bar

from . import bar_sources, calendar, execution, money_inputs, nyse, order_types

OrderType = order_types.OrderType

MEDVOL_BARS = 60          # lookback for median dollar volume
# Compatibility alias. New code reads this from the named execution profile.
MAX_NOTIONAL_FRAC = execution.BASELINE.max_participation
PENDING_MAX_DAYS = 3      # trading days a bar may be missing before 'no_bar'


@dataclass
class FillResult:
    """Outcome of attempting to fill one order on a given date."""
    status: str                 # 'filled' | 'rejected' | 'pending'
    reject_reason: str | None = None
    open_px: float | None = None
    fill_px: float | None = None
    slippage_bps: float | None = None
    cost_bps: float | None = None
    median_dollar_vol: float | None = None
    participation: float | None = None
    impact_bps: float | None = None
    fee_bps: float | None = None
    execution_profile: str | None = None
    fill_kind: str | None = None
    price_source: str | None = None
    bar_ref: str | None = None
    fill_ts: datetime | None = None
    reference_px: float | None = None


def median_dollar_vol(
    con: duckdb.DuckDBPyConnection, ticker: str, as_of: date, bars: int = MEDVOL_BARS
) -> float | None:
    """Median of close*volume over the last `bars` sessions STRICTLY BEFORE
    `as_of`.

    The window excludes `as_of` itself (date < as_of): `as_of` is the fill date,
    so including its own close×volume in the liquidity cap and slippage tier would
    consume information from the bar being traded — a small look-ahead. Returns
    None if the name has no bars at all in the window.
    """
    row = con.execute(
        """
        SELECT MEDIAN(close * volume) FROM (
            SELECT close, volume FROM prices
            WHERE ticker = ? AND date < ?
            ORDER BY date DESC LIMIT ?
        )
        """,
        [ticker, as_of, bars],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def half_spread_bps(mdv: float | None) -> float:
    """Conservative liquidity-tiered half-spread estimate (documented above)."""
    return execution.half_spread_bps(mdv)


def slippage_bps_for(mdv: float | None,
                     profile: str | execution.ExecutionProfile | None = None,
                     *, side: str = "buy", qty: float = 1.0,
                     open_px: float = 1.0) -> float:
    """Per-side slippage in bps: max(half_spread, 5) + 5 (the +5 = 10bp r/t)."""
    return execution.cost_components(
        profile, side=side, qty=qty, open_px=open_px,
        median_dollar_volume=mdv)["total_bps"]


def attempt_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    signal_date: date,
    fill_date: date,
    profile: str | execution.ExecutionProfile | None = None,
) -> FillResult:
    """Try to fill one order at `fill_date`'s open. The ONLY look-ahead guard.

    - Requires fill_date > signal_date (no same-bar fills, ever).
    - Missing bar: 'pending' until PENDING_MAX_DAYS trading days elapse, then
      'rejected' with reason 'no_bar' (a bar is never fabricated).
    - Liquidity guard: notional above the profile's participation cap is rejected.
    - Otherwise 'filled' at the slippage-adjusted open.
    """
    if fill_date <= signal_date:
        raise ValueError(
            f"look-ahead violation: fill_date {fill_date} !> signal_date {signal_date}"
        )

    refusal = money_inputs.order_refusal(side, qty, sides=("buy", "sell"))
    if refusal:
        return FillResult(status="rejected", reject_reason=refusal)
    bar = con.execute(
        "SELECT open,high,low,close,volume FROM prices WHERE ticker=? AND date=?",
        [ticker, fill_date],
    ).fetchone()
    if not trusted_bar(bar):
        elapsed = calendar.trading_days_between(con, signal_date, fill_date)
        if elapsed >= PENDING_MAX_DAYS:
            return FillResult(status="rejected", reject_reason="no_bar")
        return FillResult(status="pending", reject_reason="untrusted_bar")

    open_px = float(bar[0])
    mdv = median_dollar_vol(con, ticker, fill_date)

    selected = execution.resolve_profile(profile)
    components = execution.cost_components(
        selected, side=side, qty=qty, open_px=open_px,
        median_dollar_volume=mdv)

    # Liquidity guard (partial fills not modeled v1).
    if (mdv is not None
            and components["participation"] > selected.max_participation):
        return FillResult(
            status="rejected",
            reject_reason=f"illiquid: notional ${qty * open_px:,.0f} > "
            f"{selected.max_participation:.2%} of "
            f"median $vol ${mdv:,.0f} (profile {selected.id})",
            open_px=open_px,
            median_dollar_vol=mdv,
        )

    slip = components["total_bps"]
    if side == "buy":
        fill_px = open_px * (1 + slip / 1e4)
    elif side == "sell":
        fill_px = open_px * (1 - slip / 1e4)

    if money_inputs.order_refusal(side, qty, fill_price=fill_px) or not math.isfinite(qty * fill_px):
        return FillResult(status="rejected", reject_reason="invalid_order: fill arithmetic")
    return FillResult(
        status="filled",
        open_px=open_px,
        fill_px=fill_px,
        slippage_bps=components["market_bps"],
        cost_bps=slip,
        median_dollar_vol=mdv,
        participation=components["participation"],
        impact_bps=components["impact_bps"],
        fee_bps=components["fee_bps"],
        execution_profile=selected.id,
    )


def _utc_naive(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _v2_result(
    *,
    side: str,
    qty: float,
    reference_px: float,
    mdv: float | None,
    slip_bps: float,
    fill_kind: str,
    price_source: str,
    bar_ref: str,
    fill_ts: datetime,
    profile: str | execution.ExecutionProfile | None,
) -> FillResult:
    refusal = money_inputs.order_refusal(side, qty, reference_price=reference_px)
    if refusal:
        return FillResult(status="rejected", reject_reason=refusal)
    selected = execution.resolve_profile(profile)
    participation = (
        0.0 if mdv is None or mdv <= 0 else qty * reference_px / mdv
    )
    if mdv is not None and participation > selected.max_participation:
        return FillResult(
            status="rejected",
            reject_reason=f"illiquid: notional ${qty * reference_px:,.0f} > "
            f"{selected.max_participation:.2%} of median $vol ${mdv:,.0f} "
            f"(profile {selected.id})",
            open_px=reference_px,
            median_dollar_vol=mdv,
            participation=participation,
            execution_profile=selected.id,
            fill_kind=fill_kind,
            price_source=price_source,
            bar_ref=bar_ref,
            fill_ts=fill_ts,
            reference_px=reference_px,
        )
    direction = 1 if side in {"buy", "cover"} else -1
    if side not in {"buy", "sell", "short", "cover"}:
        raise ValueError(f"bad side {side!r}")
    fill_px = reference_px * (1 + direction * slip_bps / 1e4)
    if money_inputs.order_refusal(side, qty, fill_price=fill_px) or not math.isfinite(qty * fill_px):
        return FillResult(status="rejected", reject_reason="invalid_order: fill arithmetic")
    return FillResult(
        status="filled",
        open_px=reference_px,
        fill_px=fill_px,
        slippage_bps=slip_bps,
        cost_bps=slip_bps,
        median_dollar_vol=mdv,
        participation=participation,
        impact_bps=0.0,
        fee_bps=0.0,
        execution_profile=selected.id,
        fill_kind=fill_kind,
        price_source=price_source,
        bar_ref=bar_ref,
        fill_ts=fill_ts,
        reference_px=reference_px,
    )


def attempt_next_open_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    signal_date: date,
    fill_date: date,
    profile: str | execution.ExecutionProfile | None = None,
    *,
    price_source: str = "prices",
    available_at: datetime | None = None,
    penalty_bps: float = 0.0,
) -> FillResult:
    """V2 next-open attempt with alternate daily sources and explicit sides."""
    refusal = money_inputs.order_refusal(side, qty)
    if refusal:
        return FillResult(status="rejected", reject_reason=refusal)
    if fill_date <= signal_date:
        raise ValueError(
            f"look-ahead violation: fill_date {fill_date} !> signal_date {signal_date}"
        )
    bar = bar_sources.daily_bar(
        con, ticker, fill_date, source=price_source, available_at=available_at,
    )
    if bar is None:
        elapsed = 0
        cursor = signal_date
        while cursor < fill_date:
            cursor += timedelta(days=1)
            if nyse.is_session(cursor):
                elapsed += 1
        if elapsed >= PENDING_MAX_DAYS:
            return FillResult(status="rejected", reject_reason="no_bar")
        return FillResult(status="pending", reject_reason="untrusted_bar", price_source=price_source)
    mdv = bar_sources.median_dollar_volume(
        con, ticker, fill_date, source=price_source, available_at=available_at,
    )
    slip = half_spread_bps(mdv) + 5.0 + penalty_bps
    fill_ts = datetime.combine(
        fill_date, datetime.min.time().replace(hour=9, minute=30),
        bar_sources.NEW_YORK,
    ).astimezone(timezone.utc).replace(tzinfo=None)
    return _v2_result(
        side=side,
        qty=qty,
        reference_px=bar.open,
        mdv=mdv,
        slip_bps=slip,
        fill_kind="next_open",
        price_source=price_source,
        bar_ref=bar.bar_ref,
        fill_ts=fill_ts,
        profile=profile,
    )


def attempt_auction_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    session_date: date,
    received_at: datetime,
    order_type: str = "moo",
    profile: str | execution.ExecutionProfile | None = None,
    *,
    price_source: str = "prices",
    available_at: datetime | None = None,
    penalty_bps: float = 0.0,
) -> FillResult:
    """Attempt an opening- or closing-auction fill without a same-bar peek."""
    kind = OrderType(order_type)
    refusal = money_inputs.order_refusal(side, qty)
    if refusal:
        return FillResult(status="rejected", reject_reason=refusal)
    if kind not in {OrderType.MOO, OrderType.MOC}:
        raise ValueError("auction order_type must be 'moo' or 'moc'")
    if received_at.utcoffset() is None:
        raise ValueError("received_at must include its timezone")
    if not order_types.received_at_allowed(kind, session_date, received_at):
        return FillResult(status="rejected", reject_reason="cutoff")
    bar = bar_sources.daily_bar(
        con, ticker, session_date, source=price_source, available_at=available_at,
    )
    if bar is None:
        return FillResult(status="pending", reject_reason="untrusted_bar", price_source=price_source)
    opening = kind is OrderType.MOO
    reference = bar.open if opening else bar.close
    mdv = bar_sources.median_dollar_volume(
        con, ticker, session_date, source=price_source, available_at=available_at,
    )
    # Auction orders trade at one clearing print: half the normal estimated
    # half-spread tier and no fixed adverse-movement component.
    slip = half_spread_bps(mdv) / 2 + penalty_bps
    opened, _closed = bar_sources.session_bounds(session_date)
    fill_ts = opened if opening else _utc_naive(order_types.session_close(session_date))
    return _v2_result(
        side=side,
        qty=qty,
        reference_px=reference,
        mdv=mdv,
        slip_bps=slip,
        fill_kind="open_auction" if opening else "close_auction",
        price_source=price_source,
        bar_ref=bar.bar_ref,
        fill_ts=fill_ts,
        profile=profile,
    )


def _eligible_minutes(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    session_date: date,
    received_at: datetime,
    *,
    price_source: str,
    available_at: datetime | None,
) -> list[bar_sources.MinuteBar]:
    earliest = _utc_naive(received_at) + timedelta(minutes=1)
    return [
        bar for bar in bar_sources.minute_bars(
            con, ticker, session_date, source=price_source, available_at=available_at,
        )
        if bar.ts >= earliest
    ]


def _missing_intraday_result(
    session_date: date,
    available_at: datetime | None,
    *,
    price_source: str,
    terminal_status: str,
    terminal_reason: str,
) -> FillResult:
    if available_at is None:
        return FillResult(status="pending", price_source=price_source)
    elapsed = 0
    cursor = session_date
    through = _utc_naive(available_at).date()
    while cursor < through:
        cursor += timedelta(days=1)
        if nyse.is_session(cursor):
            elapsed += 1
    if elapsed < PENDING_MAX_DAYS:
        return FillResult(status="pending", price_source=price_source)
    return FillResult(
        status=terminal_status,
        reject_reason=terminal_reason,
        price_source=price_source,
    )


def attempt_intraday_market_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    session_date: date,
    received_at: datetime,
    profile: str | execution.ExecutionProfile | None = None,
    *,
    price_source: str = "intraday_prices",
    daily_price_source: str = "prices",
    available_at: datetime | None = None,
) -> FillResult:
    """Fill at the first minute bar at least 60 seconds after receipt."""
    refusal = money_inputs.order_refusal(side, qty)
    if refusal:
        return FillResult(status="rejected", reject_reason=refusal)
    if received_at.utcoffset() is None:
        raise ValueError("received_at must include its timezone")
    if not order_types.received_at_allowed(OrderType.MARKET, session_date, received_at):
        return FillResult(status="rejected", reject_reason="market_closed")
    bars = _eligible_minutes(
        con, ticker, session_date, received_at,
        price_source=price_source, available_at=available_at,
    )
    if not bars:
        if bar_sources.minute_session_complete(
            con, ticker, session_date, source=price_source,
            available_at=available_at,
        ):
            return FillResult(
                status="rejected", reject_reason="no_bar", price_source=price_source,
            )
        return _missing_intraday_result(
            session_date, available_at, price_source=price_source,
            terminal_status="rejected", terminal_reason="no_bar",
        )
    bar = bars[0]
    reference = bar.vwap if bar.vwap is not None and math.isfinite(bar.vwap) and bar.vwap > 0 else (
        bar.open + bar.high + bar.low + bar.close
    ) / 4
    mdv = bar_sources.median_dollar_volume(
        con, ticker, session_date, source=daily_price_source, available_at=available_at,
    )
    slip = half_spread_bps(mdv) + 5.0
    return _v2_result(
        side=side,
        qty=qty,
        reference_px=reference,
        mdv=mdv,
        slip_bps=slip,
        fill_kind="intraday_bar",
        price_source=price_source,
        bar_ref=bar.bar_ref,
        # Minute timestamps are interval starts.  The simulated decision/fill
        # occurs only once the complete [ts, ts+1m) bar is observable.
        fill_ts=bar.ts + timedelta(minutes=1),
        profile=profile,
    )


def tick_size(price: float) -> float:
    """US equity tick used by the deterministic limit-touch rule."""
    money_inputs.finite_number(price, "limit price", positive=True)
    return 0.01 if price >= 1 else 0.0001


def attempt_intraday_limit_fill(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    side: str,
    qty: float,
    session_date: date,
    received_at: datetime,
    limit_px: float,
    profile: str | execution.ExecutionProfile | None = None,
    *,
    price_source: str = "intraday_prices",
    daily_price_source: str = "prices",
    available_at: datetime | None = None,
) -> FillResult:
    """Fill a day limit only after a full later minute bar crosses one tick."""
    refusal = money_inputs.order_refusal(side, qty, limit_price=limit_px)
    if refusal:
        return FillResult(status="rejected", reject_reason=refusal)
    if received_at.utcoffset() is None:
        raise ValueError("received_at must include its timezone")
    if not order_types.received_at_allowed(OrderType.LIMIT, session_date, received_at):
        return FillResult(status="rejected", reject_reason="market_closed")
    bars = _eligible_minutes(
        con, ticker, session_date, received_at,
        price_source=price_source, available_at=available_at,
    )
    if not bars:
        if bar_sources.minute_session_complete(
            con, ticker, session_date, source=price_source,
            available_at=available_at,
        ):
            return FillResult(
                status="expired", reject_reason="day_limit_not_touched",
                price_source=price_source,
            )
        return _missing_intraday_result(
            session_date, available_at, price_source=price_source,
            terminal_status="rejected", terminal_reason="no_bar",
        )
    tick = tick_size(limit_px)
    if side in {"buy", "cover"}:
        touched = next((bar for bar in bars if bar.low <= limit_px - tick), None)
    elif side in {"sell", "short"}:
        touched = next((bar for bar in bars if bar.high >= limit_px + tick), None)
    else:
        raise ValueError(f"bad side {side!r}")
    if touched is None and not bar_sources.minute_session_complete(
        con, ticker, session_date, source=price_source, available_at=available_at,
    ):
        return _missing_intraday_result(
            session_date, available_at, price_source=price_source,
            terminal_status="rejected", terminal_reason="no_bar",
        )
    if touched is None:
        return FillResult(
            status="expired", reject_reason="day_limit_not_touched",
            price_source=price_source,
        )
    mdv = bar_sources.median_dollar_volume(
        con, ticker, session_date, source=daily_price_source, available_at=available_at,
    )
    return _v2_result(
        side=side,
        qty=qty,
        reference_px=limit_px,
        mdv=mdv,
        slip_bps=0.0,
        fill_kind="limit_touch",
        price_source=price_source,
        bar_ref=touched.bar_ref,
        fill_ts=touched.ts + timedelta(minutes=1),
        profile=profile,
    )
