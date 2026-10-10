"""Deterministic session settlement for account-engine portfolios."""
from __future__ import annotations

import json
import math
from contextlib import nullcontext
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

import duckdb

from engine.accounts import account_portfolios, actions, sources
from engine.accounts import service as account_service
from engine.lib import db
from engine.lib.util import table_exists
from engine.money import alerts, halts
from sim import bar_sources, fills, ledger, margin, nyse, portfolio, shorts, valuation
from sim.costs import charge
from sim.schema import portfolio_account

MARGIN_CALL_PENALTY_BPS = 25.0


def _utc_aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_naive(value: datetime) -> datetime:
    return _utc_aware(value).replace(tzinfo=None)


def _special_reason(value: str | None, reason: str) -> bool:
    return reason in (value or "").split("|")


def _state(
    con: duckdb.DuckDBPyConnection,
    order_id: int,
    state: str,
    reason: str | None,
    at: datetime,
) -> None:
    coarse = "filled" if state == "filled" else (
        "pending" if state == "queued" else "cancelled" if state == "cancelled"
        else "rejected"
    )
    con.execute(
        "UPDATE sim_orders SET status=?,reject_reason=? WHERE id=?",
        [coarse, reason if coarse == "rejected" else None, order_id],
    )
    con.execute(
        "UPDATE sim_order_details SET state=?,state_reason=?,state_at=? WHERE order_id=?",
        [state, reason, _utc_naive(at), order_id],
    )


def _missing_bar(
    con: duckdb.DuckDBPyConnection,
    order_id: int,
    old_reason: str | None,
    at: datetime,
) -> None:
    reasons = [part for part in (old_reason or "").split("|") if part]
    if "bar_missing" not in reasons:
        reasons.append("bar_missing")
    _state(con, order_id, "queued", "|".join(reasons), at)


def _fill_attempt(
    con: duckdb.DuckDBPyConnection,
    row: dict[str, Any],
    settings: dict[str, Any],
    day: date,
    available_at: datetime,
) -> fills.FillResult:
    order_type = row["order_type"]
    received = _utc_aware(row["received_at"])
    execution_profile = row["execution_profile"] or "baseline_v1"
    penalty = (
        shorts.BUY_IN_PENALTY_BPS
        if _special_reason(row["state_reason"], "buy_in")
        else MARGIN_CALL_PENALTY_BPS
        if _special_reason(row["state_reason"], "margin_call")
        else 0.0
    )
    if order_type == "next_open":
        return fills.attempt_next_open_fill(
            con, row["ticker"], row["side"], row["qty"], row["signal_date"], day,
            execution_profile, price_source=settings["price_source"],
            available_at=available_at, penalty_bps=penalty,
        )
    if order_type in {"moo", "moc"}:
        return fills.attempt_auction_fill(
            con, row["ticker"], row["side"], row["qty"], day, received,
            order_type, execution_profile, price_source=settings["price_source"],
            available_at=available_at, penalty_bps=penalty,
        )
    minute_source = (
        "massive_minute" if settings["price_source"] == "massive_daily"
        else "intraday_prices"
    )
    if order_type == "market":
        return fills.attempt_intraday_market_fill(
            con, row["ticker"], row["side"], row["qty"], day, received,
            execution_profile, price_source=minute_source,
            daily_price_source=settings["price_source"],
            available_at=available_at,
        )
    if order_type == "limit":
        return fills.attempt_intraday_limit_fill(
            con, row["ticker"], row["side"], row["qty"], day, received,
            row["limit_px"], execution_profile, price_source=minute_source,
            daily_price_source=settings["price_source"],
            available_at=available_at,
        )
    return fills.FillResult(status="rejected", reject_reason="unsupported_order_type")


def _contingent_quantity(
    con: duckdb.DuckDBPyConnection, parent_order_id: int | None,
) -> tuple[str, float | None]:
    if parent_order_id is None:
        return "independent", None
    row = con.execute(
        "SELECT qty FROM sim_fills WHERE order_id=?", [parent_order_id]
    ).fetchone()
    if row is not None:
        return "filled", float(row[0])
    state = con.execute(
        "SELECT status FROM sim_orders WHERE id=?", [parent_order_id]
    ).fetchone()
    if state is None or state[0] in {"rejected", "cancelled"}:
        return "failed", None
    return "pending", None


def _existing_notional(
    con: duckdb.DuckDBPyConnection, day: date,
) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for ticker, side, qty, reference in con.execute(
        "SELECT ticker,side,qty,open_px FROM sim_fills WHERE fill_date=?",
        [day],
    ).fetchall():
        key = (ticker, _direction(side))
        out[key] = out.get(key, 0.0) + abs(float(qty) * float(reference))
    return out


def _direction(side: str) -> str:
    return "buy" if side in {"buy", "cover"} else "sell"


def _max_gross_fraction(
    con: duckdb.DuckDBPyConnection, portfolio_id: str,
) -> float:
    try:
        row = con.execute(
            "SELECT payload FROM paper_account_specs WHERE account_id=?", [portfolio_id]
        ).fetchone()
    except duckdb.Error:
        return 1.0
    if row is None:
        return 1.0
    try:
        payload = json.loads(row[0])
        value = float(payload.get("max_gross_fraction", 1.0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 1.0
    return min(max(value, 0.0), 1.5)


def _available_close_quantity(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    ticker: str,
    side: str,
    requested: float,
) -> float:
    if side not in {"sell", "cover"}:
        return requested
    row = con.execute(
        "SELECT qty FROM sim_positions WHERE portfolio_id=? AND ticker=?",
        [portfolio_id, ticker],
    ).fetchone()
    held = float(row[0]) if row else 0.0
    available = max(held, 0.0) if side == "sell" else abs(min(held, 0.0))
    return min(requested, available)


def _cash_quantity(
    con: duckdb.DuckDBPyConnection,
    settings: dict[str, Any],
    portfolio_id: str,
    side: str,
    requested: float,
    price: float,
    fee_total: float,
) -> float:
    if settings["account_type"] != "cash_legacy" or side != "buy":
        return requested
    available = max(portfolio.get_cash(con, portfolio_id) - fee_total, 0.0)
    return min(requested, available / price * (1.0 - 1e-12))


def _record_account_event(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    kind: str,
    payload: dict[str, Any],
    created_at: datetime,
) -> None:
    if not table_exists(con, "account_events"):
        return
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if con.execute(
        "SELECT 1 FROM account_events WHERE portfolio_id=? AND kind=? AND payload=?",
        [portfolio_id, kind, encoded],
    ).fetchone():
        return
    event_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM account_events"
    ).fetchone()[0])
    con.execute(
        "INSERT INTO account_events (id,portfolio_id,kind,payload,created_at) "
        "VALUES (?,?,?,?,?)",
        [event_id, portfolio_id, kind, encoded, _utc_naive(created_at)],
    )


def _persist_fill(
    con: duckdb.DuckDBPyConnection,
    row: dict[str, Any],
    result: fills.FillResult,
    fee,
    day: date,
    settled_at: datetime,
    late: bool,
) -> float:
    fill = {
        "order_id": row["order_id"],
        "portfolio_id": row["portfolio_id"],
        "instrument_id": row["ticker"],
        "side": row["side"],
        "qty": row["qty"],
        "fill_px": result.fill_px,
        "fill_date": day,
        "session_date": day,
        "multiplier": 1.0,
    }
    applied = ledger.apply_fill(con, fill, fee)
    if applied <= 0:
        return 0.0
    con.execute(
        "INSERT INTO sim_fills VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            row["order_id"], row["portfolio_id"], row["ticker"], row["side"],
            applied, day, result.reference_px, result.fill_px,
            result.slippage_bps, result.cost_bps,
        ],
    )
    con.execute(
        "INSERT INTO sim_fill_details "
        "(order_id,fill_ts,fill_kind,price_source,bar_ref,reference_px,multiplier,"
        "late_settled,settled_at) VALUES (?,?,?,?,?,?,1,?,?)",
        [
            row["order_id"], result.fill_ts, result.fill_kind, result.price_source,
            result.bar_ref, result.reference_px, late, _utc_naive(settled_at),
        ],
    )
    con.execute(
        "INSERT INTO sim_fill_costs VALUES (?,?,?,?,?,?,?)",
        [
            row["order_id"], result.execution_profile, result.participation,
            result.slippage_bps or 0.0, result.impact_bps or 0.0,
            result.fee_bps or 0.0, result.cost_bps or 0.0,
        ],
    )
    return applied


def _mark_account(
    con: duckdb.DuckDBPyConnection,
    portfolio_id: str,
    day: date,
    price_source: str,
    available_at: datetime,
) -> dict[str, Any]:
    """Persist one source-aware mark, carrying rather than erasing liabilities."""
    cash = portfolio.get_cash(con, portfolio_id)
    market_value = 0.0
    count = 0
    carried: list[str] = []
    marks = {}
    for ticker, qty in con.execute(
        "SELECT ticker,qty FROM sim_positions WHERE portfolio_id=? AND qty<>0",
        [portfolio_id],
    ).fetchall():
        observed = valuation.mark(
            con, portfolio_id, ticker, day, price_source=price_source,
            available_at=available_at,
        )
        close = observed.price
        marks[ticker] = close
        if observed.stale:
            carried.append(ticker)
            _record_account_event(
                con, portfolio_id, "stale_mark",
                {"instrument_id": ticker, "session_date": day.isoformat(),
                 "price_source": price_source, "carried_price": close},
                available_at,
            )
        market_value += float(qty) * close
        count += 1
    con.execute(
        "INSERT OR REPLACE INTO sim_equity VALUES (?,?,?,?,?)",
        [portfolio_id, day, cash + market_value, cash, count],
    )
    ledger.record_checkpoint(con, portfolio_id, day, marks, available_at)
    return {"equity": cash + market_value, "cash": cash, "carried": sorted(carried)}


def _pending_rows(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    names = (
        "order_id", "portfolio_id", "ticker", "side", "qty", "signal_date",
        "order_type", "instrument_kind", "limit_px", "session_date", "received_at",
        "parent_order_id", "leg_no", "leg_ratio", "contingent_on", "state_reason",
        "execution_profile",
    )
    rows = con.execute(
        "SELECT o.id,o.portfolio_id,o.ticker,o.side,o.qty,o.signal_date,"
        "d.order_type,d.instrument_kind,d.limit_px,d.session_date,d.received_at,"
        "d.parent_order_id,d.leg_no,d.leg_ratio,d.contingent_on,d.state_reason,"
        "p.execution_profile FROM sim_orders o "
        "JOIN sim_order_details d ON d.order_id=o.id "
        "JOIN portfolios p ON p.id=o.portfolio_id "
        "WHERE o.status='pending' AND d.state='queued' "
        "ORDER BY o.id"
    ).fetchall()
    return [dict(zip(names, row, strict=True)) for row in rows]


def _due(con, row: dict[str, Any], day: date, late: bool) -> bool:
    if row["order_type"] == "next_open":
        if nyse.next_session(row["signal_date"]) != day:
            return False
    elif row["session_date"] != day:
        return False
    return True


def _execution_key(row: dict[str, Any], result: fills.FillResult, day: date) -> tuple:
    if result.fill_ts is not None:
        execution = result.fill_ts
    else:
        opened, closed = bar_sources.session_bounds(day)
        execution = (
            opened if row["order_type"] in {"next_open", "moo"}
            else closed if row["order_type"] == "moc"
            else _utc_naive(row["received_at"]) + timedelta(minutes=1)
        )
    return execution, _utc_naive(row["received_at"]), row["order_id"]


def _liquidity_refusals(con, day: date, prepared) -> set[int]:
    used = _existing_notional(con, day)
    refused: set[int] = set()
    for row, result in sorted(prepared, key=lambda item: (
        _utc_naive(item[0]["received_at"]), item[0]["order_id"],
    )):
        if result.status != "filled" or result.reference_px is None:
            continue
        key = (row["ticker"], _direction(row["side"]))
        notional = float(row["qty"]) * float(result.reference_px)
        cap = None if result.median_dollar_vol is None else result.median_dollar_vol * 0.01
        if cap is not None and used.get(key, 0.0) + notional > cap + 1e-9:
            refused.add(row["order_id"])
            continue
        used[key] = used.get(key, 0.0) + notional
    return refused


def _is_forced(row: dict[str, Any]) -> bool:
    return any(
        _special_reason(row["state_reason"], reason)
        for reason in ("buy_in", "margin_call", "retirement")
    )


def _settle_order(
    con,
    row: dict[str, Any],
    result: fills.FillResult,
    settings: dict[str, Any],
    day: date,
    now: datetime,
    late: bool,
    short_con,
    liquidity_refusals: set[int],
    execution_keys: dict[int, tuple],
) -> str:
    if (
        row["instrument_kind"] not in {"stock", "etf"}
        or row["parent_order_id"] is not None
        or row["leg_no"] is not None
        or row["leg_ratio"] is not None
    ):
        _state(con, row["order_id"], "rejected", "instrument_not_executable", now)
        return "rejected"
    if settings["status"] in {"halted", "retiring"} and not _is_forced(row):
        _state(con, row["order_id"], "cancelled", settings["status"], now)
        return "rejected"
    contingent, contingent_qty = _contingent_quantity(con, row["contingent_on"])
    if contingent == "failed":
        _state(con, row["order_id"], "rejected", "contingent_not_filled", now)
        return "rejected"
    if contingent == "pending":
        parent_key = execution_keys.get(row["contingent_on"])
        if parent_key is not None and parent_key > execution_keys[row["order_id"]]:
            _state(con, row["order_id"], "rejected", "contingent_parent_later", now)
            return "rejected"
        _missing_bar(con, row["order_id"], row["state_reason"], now)
        return "pending"
    if contingent_qty is not None:
        row["qty"] = min(row["qty"], contingent_qty)
    row["qty"] = _available_close_quantity(
        con, row["portfolio_id"], row["ticker"], row["side"], row["qty"],
    )
    if row["qty"] <= 0:
        _state(con, row["order_id"], "rejected", "no_position", now)
        return "rejected"
    if row["side"] == "short":
        if not settings["allow_short"]:
            _state(con, row["order_id"], "rejected", "short_not_allowed", now)
            return "rejected"
        if not shorts.short_data_available(short_con):
            _record_account_event(
                con, row["portfolio_id"], "locate_unavailable",
                {"instrument_id": row["ticker"], "session_date": day.isoformat()}, now,
            )
            _state(con, row["order_id"], "rejected", "locate_unavailable", now)
            return "rejected"
        locate = shorts.locate(
            short_con, row["ticker"], day, market_con=con,
            price_source=settings["price_source"], available_at=now,
        )
        if locate.data_stale:
            _record_account_event(
                con, row["portfolio_id"], "locate_data_stale",
                {"instrument_id": row["ticker"], "session_date": day.isoformat()}, now,
            )
        if not locate.available:
            _state(con, row["order_id"], "rejected", "no_locate", now)
            return "rejected"
    if result.status == "pending":
        _missing_bar(con, row["order_id"], row["state_reason"], now)
        return "pending"
    if result.status in {"rejected", "expired"}:
        state = "expired" if result.status == "expired" else "rejected"
        _state(con, row["order_id"], state, result.reject_reason, now)
        return state
    if row["order_id"] in liquidity_refusals:
        _state(con, row["order_id"], "rejected", "illiquid_aggregate", now)
        return "rejected"
    forced = _is_forced(row)
    pdt = margin.pdt_check(
        con, row["portfolio_id"], row["ticker"], row["side"], row["qty"], day,
        price=result.fill_px, price_source=settings["price_source"],
        as_of=result.fill_ts, available_at=now,
    )
    if not forced and not pdt.allowed:
        _state(con, row["order_id"], "rejected", pdt.reason, now)
        return "rejected"
    fee = charge(
        settings["cost_profile"], side=row["side"], qty=row["qty"],
        price=result.fill_px, fill_kind=result.fill_kind,
        instrument={"kind": row["instrument_kind"], "multiplier": 1.0},
        session_date=day,
    )
    applied_qty = _cash_quantity(
        con, settings, row["portfolio_id"], row["side"], row["qty"],
        result.fill_px, fee.total_usd,
    )
    if applied_qty * result.fill_px < ledger.MIN_FILL_USD:
        _state(con, row["order_id"], "rejected", "ledger_refused", now)
        return "rejected"
    if not math.isclose(applied_qty, row["qty"], rel_tol=1e-12, abs_tol=1e-12):
        row["qty"] = applied_qty
        result = replace(
            result,
            participation=(
                0.0 if not result.median_dollar_vol
                else applied_qty * result.reference_px / result.median_dollar_vol
            ),
        )
        fee = charge(
            settings["cost_profile"], side=row["side"], qty=row["qty"],
            price=result.fill_px, fill_kind=result.fill_kind,
            instrument={"kind": row["instrument_kind"], "multiplier": 1.0},
            session_date=day,
        )
    projected = margin.margin_state(
        con, row["portfolio_id"], day,
        projected=(row["ticker"], row["side"], row["qty"], result.fill_px),
        fees=fee.total_usd, price_source=settings["price_source"],
        as_of=result.fill_ts, available_at=now,
    )
    gross_cap = _max_gross_fraction(con, row["portfolio_id"])
    if not forced and row["side"] in {"buy", "short"} and projected.initial_excess < -1e-9:
        _state(con, row["order_id"], "rejected", "reg_t_initial", now)
        return "rejected"
    if (
        not forced
        and row["side"] in {"buy", "short"}
        and projected.long_market_value + projected.short_market_value
        > projected.equity * gross_cap + 1e-9
    ):
        _state(con, row["order_id"], "rejected", "gross_cap", now)
        return "rejected"
    applied = _persist_fill(con, row, result, fee, day, now, late)
    if not math.isclose(applied, row["qty"], rel_tol=1e-12, abs_tol=1e-12):
        raise RuntimeError("ledger changed the prevalidated account fill quantity")
    _state(con, row["order_id"], "filled", row["state_reason"], now)
    if _special_reason(row["state_reason"], "buy_in"):
        ledger.apply_cash_event(con, {
            "portfolio_id": row["portfolio_id"], "event_date": day,
            "kind": "buy_in_penalty", "amount": 0.0,
            "instrument_id": row["ticker"], "ref_order_id": row["order_id"],
            "note": f"{shorts.BUY_IN_PENALTY_BPS:g} bp in fill price",
        })
    return "filled"


def _fold_session(con, account_id, day, now, settings, late, short_con, counts):
    """Fold recorded events and new executions together in effective-time order."""
    from functools import partial

    prepared = []
    for row in _pending_rows(con):
        if not _due(con, row, day, late):
            continue
        row = actions.prepare_order(con, row, day, now)
        account = portfolio_account(con, row['portfolio_id'])
        prepared.append((row, _fill_attempt(con, row, account, day, now)))
    keys = {row['order_id']: _execution_key(row, result, day) for row, result in prepared}
    refusals = _liquidity_refusals(con, day, prepared)
    local = [(row, result) for row, result in prepared if row['portfolio_id'] == account_id]
    sources.require_sources(con, settings, [row for row, _ in local])
    sequence = [event for event in ledger.events(con, [account_id], since=day, through=day)
                if not (event.kind == 'cash' and event.row['kind'] in {'borrow_fee', 'margin_interest'})]
    opened = bar_sources.session_bounds(day)[0]
    operations = [
        (opened, 1, -1, lambda: actions.credit_dividends(con, account_id, day, now)),
        (opened, 3, 0, lambda: shorts.accrue_borrow(con, day, portfolio_id=account_id, replay=True)),
        (opened, -1, 1, lambda: margin.accrue_interest(con, day, portfolio_id=account_id, replay=True)),
    ]

    def execute(row, result):
        state = _settle_order(con, row, result, settings, day, now, late, short_con, refusals, keys)
        counts[state] += 1

    for row, result in local:
        operations.append((keys[row['order_id']][0], 4, row['order_id'], partial(execute, row, result)))
    for stamp, phase, seq, operation in operations:
        sequence.append(ledger.LedgerEvent(stamp, phase, (account_id, 0, seq),
                                          'operation', {'run': operation}))
    for event in sorted(sequence, key=lambda event: event.key):
        ledger.apply_event(con, event)


def fold_account(con, account_id, end, *, now, short_con=None, late=False,
                 mutation=None, manage_transaction=True):
    """Atomically replace the cache by folding the whole account from inception."""
    counts = dict(filled=0, rejected=0, expired=0, pending=0)
    with db.transaction(con) if manage_transaction else nullcontext():
        account_service.require_verified(con, account_id, now=now, manage_transaction=False)
        if mutation:
            mutation()
        created = con.execute('SELECT created FROM portfolios WHERE id=?', [account_id]).fetchone()[0]
        equity_days = [row[0] for row in con.execute(
            'SELECT date FROM sim_equity WHERE portfolio_id=?', [account_id]).fetchall()]
        event_days = [event.stamp.date() for event in ledger.events(con, [account_id])]
        end = max([end, *equity_days, *event_days])
        start = min([created, *event_days])
        actions.capture_splits(con, account_id, end, now, _record_account_event)
        ledger.rebuild_state(con, [account_id], through=start - timedelta(days=1))
        settings = {**portfolio_account(con, account_id), 'portfolio_id': account_id}
        carried = []
        day = start
        while day <= end:
            if nyse.is_session(day):
                _fold_session(con, account_id, day, now, settings,
                              late or day < end, short_con, counts)
                if day >= created or day in equity_days:
                    mark = _mark_account(con, account_id, day, settings['price_source'], now)
                    carried = mark['carried']
                    if not carried:
                        _record_account_event(con, account_id, 'late_reconciled',
                                              {'session_date': day.isoformat()}, now)
            day += timedelta(days=1)
        account_service.require_verified(con, account_id, now=now, manage_transaction=False)
        latest = con.execute('SELECT MAX(date) FROM sim_equity WHERE portfolio_id=?', [account_id]).fetchone()[0]
        if latest is not None:
            halts.check(con, account_id, latest, now=now)
            margin.check_maintenance(con, latest, portfolio_id=account_id)
            if short_con is not None:
                shorts.queue_buy_ins(con, short_con, latest, portfolio_id=account_id)
            alerts.concentration(con, latest, now=now, portfolio_id=account_id)
        account_service.finalize_retirement(con, account_id, now=now)
    return {**counts, 'late_settled': counts['filled'] if late else 0,
            'affected_accounts': [account_id] if counts['filled'] else [],
            'recovered_marks': [account_id] if not counts['filled'] else [],
            'carried': {account_id: carried} if carried else {}}


def settle_session(con, day: date, late: bool = False, *, short_con=None,
                   settled_at: datetime | None = None) -> dict[str, Any]:
    """Settle every account by a full fold; any failed account is durably halted."""
    now = _utc_aware(settled_at or datetime.now(timezone.utc))
    out = dict(filled=0, rejected=0, expired=0, pending=0, late_settled=0,
               affected_accounts=[], recovered_marks=[], completed=[], errors={}, carried={})
    accounts = account_portfolios(con, active_only=False)
    # Global liquidity uses receipt order, including across independently funded accounts.
    first = {row['portfolio_id']: (_utc_naive(row['received_at']), row['order_id'])
             for row in reversed(_pending_rows(con))}
    accounts.sort(key=lambda row: first.get(row['portfolio_id'], (datetime.max, 0)))
    for settings in accounts:
        if settings['status'] not in {'active', 'halted', 'retiring'}:
            continue
        account_id = settings['portfolio_id']
        try:
            result = fold_account(con, account_id, day, now=now, short_con=short_con, late=late)
            for key in ('filled', 'rejected', 'expired', 'pending', 'late_settled'):
                out[key] += result[key]
            for key in ('affected_accounts', 'recovered_marks'):
                out[key].extend(result[key])
            out['carried'].update(result['carried'])
            out['completed'].append(account_id)
        except Exception as exc:
            out['errors'][account_id] = {'exception_type': type(exc).__name__, 'message': str(exc)[:1000]}
            with db.transaction(con):
                account_service.persist_mismatch(con, account_id,
                    account_service.failure_result(account_id, exc), now=now)
                _record_account_event(con, account_id, 'settlement_error',
                    {'session_date': day.isoformat(), **out['errors'][account_id]}, now)
    return out


__all__ = ['settle_session']
