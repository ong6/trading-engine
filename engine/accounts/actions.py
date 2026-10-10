"""Captured corporate-action application for signed account ledgers."""
from __future__ import annotations

import json
from datetime import date, timedelta

from engine.lib.util import table_exists
from sim import bar_sources


def recorded_splits(con, account_id: str, through: date | None = None):
    if not table_exists(con, 'account_events'):
        return []
    events = []
    for (payload,) in con.execute(
        "SELECT payload FROM account_events WHERE portfolio_id=? AND kind='split'",
        [account_id],
    ).fetchall():
        item = json.loads(payload)
        ex = date.fromisoformat(item['ex_date'])
        if through is None or ex <= through:
            events.append((item['instrument_id'], ex, float(item['ratio'])))
    return sorted(events, key=lambda item: (item[1], item[0]))


def capture_splits(con, account_id: str, day: date, now, record_event) -> None:
    """Admit captured split facts; orders always retain their receipt quantities."""
    if not table_exists(con, 'corporate_actions'):
        return
    applied = {(ticker, ex) for ticker, ex, _ in recorded_splits(con, account_id)}
    rows = con.execute(
        "SELECT ticker,ex_date,value FROM corporate_actions WHERE kind='split' "
        'AND ex_date<=? AND value>0 AND isfinite(value) '
        'AND (fetched_at IS NULL OR fetched_at<=?) AND ticker IN ('
        'SELECT ticker FROM sim_fills WHERE portfolio_id=? UNION '
        'SELECT ticker FROM sim_orders WHERE portfolio_id=?) ORDER BY ex_date,ticker',
        [day, now, account_id, account_id],
    ).fetchall()
    for ticker, ex, ratio in rows:
        if (ticker, ex) not in applied:
            record_event(con, account_id, 'split',
                         {'instrument_id': ticker, 'ex_date': ex.isoformat(), 'ratio': ratio}, now)


def prepare_order(con, row: dict, day: date, now) -> dict:
    """Convert immutable receipt units to the execution session inside the fold."""
    if not table_exists(con, 'corporate_actions'):
        return row
    prepared = dict(row)
    for ex, ratio in con.execute(
        "SELECT ex_date,value FROM corporate_actions WHERE ticker=? AND kind='split' "
        'AND ex_date<=? AND value>0 AND isfinite(value) '
        'AND (fetched_at IS NULL OR fetched_at<=?) ORDER BY ex_date',
        [row['ticker'], day, now],
    ).fetchall():
        if bar_sources._naive_utc(row['received_at']) < bar_sources.session_bounds(ex)[0]:
            prepared['qty'] *= ratio
            if prepared['limit_px'] is not None:
                prepared['limit_px'] /= ratio
    return prepared


def credit_dividends(con, account_id, day, now, *, replay=False):
    """Book entitlement at its own close; append corrections after historical changes."""
    from sim import ledger

    if not table_exists(con, 'corporate_actions'):
        return
    rows = con.execute(
        "SELECT ticker,value FROM corporate_actions WHERE kind='dividend' AND ex_date=? "
        'AND value>0 AND isfinite(value) AND (fetched_at IS NULL OR fetched_at<=?)',
        [day, now],
    ).fetchall()
    if not rows:
        return
    prefix = ledger.projected_state(con, account_id, through=day - timedelta(days=1))
    for ticker, dps in rows:
        qty = prefix['positions'].get(ticker, {}).get('qty', 0.)
        amount = qty * float(dps)
        old = con.execute('SELECT amount FROM sim_dividends WHERE portfolio_id=? AND ticker=? '
                          'AND ex_date=?', [account_id, ticker, day]).fetchone()
        if old is None:
            if not qty:
                continue
            con.execute('INSERT INTO sim_dividends VALUES (?,?,?,?,?,?)',
                        [account_id, ticker, day, qty, dps, amount])
            con.execute('UPDATE portfolios SET cash=cash+? WHERE id=?', [amount, account_id])
        else:
            note = 'historical dividend entitlement correction'
            correction = con.execute(
                "SELECT COALESCE(SUM(amount),0) FROM sim_cash_events WHERE portfolio_id=? "
                "AND event_date=? AND instrument_id=? AND kind='adjustment' AND note=?",
                [account_id, day, ticker, note]).fetchone()[0]
            delta = amount - float(old[0]) - float(correction)
            if abs(delta) > 1e-10:
                ledger.apply_cash_event(con, dict(portfolio_id=account_id, instrument_id=ticker,
                    event_date=day, kind='adjustment', amount=delta, note=note,
                    created_at=bar_sources.session_bounds(day)[0]))
