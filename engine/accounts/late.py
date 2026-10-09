"""Oldest-first recovery of unresolved account sessions and their dependent state."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from engine.accounts import account_portfolios, service
from engine.accounts import settle as processor
from engine.lib import db
from engine.money import halts
from sim import bar_sources, ledger, nyse


def unresolved(con, account_id: str) -> set[date]:
    days = set()
    for signal, session, kind in con.execute(
        'SELECT o.signal_date,d.session_date,d.order_type FROM sim_orders o '
        'JOIN sim_order_details d ON d.order_id=o.id '
        "WHERE o.portfolio_id=? AND o.status='pending'", [account_id],
    ).fetchall():
        days.add(nyse.next_session(signal) if kind == 'next_open' else session)
    resolved = set()
    events = con.execute(
        "SELECT kind,payload FROM account_events WHERE portfolio_id=? AND kind IN "
        "('stale_mark','settlement_error','late_reconciled') ORDER BY id", [account_id],
    ).fetchall()
    for kind, raw in events:
        day = date.fromisoformat(json.loads(raw)['session_date'])
        if kind == 'late_reconciled':
            resolved.add(day)
        else:
            resolved.discard(day)
            days.add(day)
    days -= resolved
    days.update(row[0] for row in con.execute(
        'SELECT DISTINCT f.fill_date FROM sim_fills f LEFT JOIN sim_equity e '
        'ON e.portfolio_id=f.portfolio_id AND e.date=f.fill_date '
        'WHERE f.portfolio_id=? AND e.date IS NULL', [account_id],
    ).fetchall())
    return days


def settle(con, *, session_date=None, short_con=None, settled_at=None) -> dict:
    """Recover each affected account atomically through its latest dependent mark."""
    now = settled_at or datetime.now(timezone.utc)
    latest = con.execute(
        'SELECT MAX(session_day) FROM (SELECT MAX(date) AS session_day FROM prices UNION ALL '
        'SELECT MAX(date) FROM sim_equity)'
    ).fetchone()[0]
    counts = {'filled': 0, 'rejected': 0, 'expired': 0, 'pending': 0, 'late_settled': 0}
    out = {**counts, 'errors': {}, 'sessions': [], 'completed': [], 'carried': {},
           'affected_accounts': [], 'recovered_marks': []}
    for settings in account_portfolios(con, active_only=False):
        if settings['status'] not in {'active', 'halted', 'retiring'}:
            continue
        account_id = settings['portfolio_id']
        days = {day for day in unresolved(con, account_id)
                if bar_sources.session_bounds(day)[1] <= bar_sources._naive_utc(now)}
        action_start = recovery_start(con, account_id, session_date or now.date(), now)
        if action_start is not None:
            days.add(action_start)
        if session_date is not None:
            days.add(session_date)
        if not days:
            continue
        end = max(value for value in (latest, session_date, min(days)) if value is not None)
        days = {day for day in days if day <= end}
        if not days:
            continue
        start = min(days)
        try:
            result = recover_account(con, account_id, start, end, now=now, short_con=short_con)
            out['sessions'].extend(result.pop('sessions'))
            for key in counts:
                out[key] += result[key]
            out['carried'].update(result['carried'])
            for key in ('affected_accounts', 'recovered_marks'):
                out[key] = sorted(set(out[key]) | set(result[key]))
            out['completed'].append(account_id)
        except Exception as exc:
            out['errors'][account_id] = {'exception_type': type(exc).__name__, 'message': str(exc)[:1000]}
            with db.transaction(con):
                if isinstance(exc, service.VerificationError):
                    service.persist_mismatch(con, account_id, exc.result, now=now)
                processor._record_account_event(con, account_id, 'settlement_error',
                    {'session_date': start.isoformat(), 'exception_type': type(exc).__name__,
                     'message': str(exc)[:1000]}, now)
    return out


def recovery_start(con, account_id, day, now):
    """Find historical work before mutating the latest account state."""
    latest = con.execute('SELECT MAX(date) FROM sim_equity WHERE portfolio_id=?',
                         [account_id]).fetchone()[0]
    if latest is None:
        return None
    starts = [day] if day <= latest else []
    from engine.accounts.actions import recorded_splits
    from engine.lib.util import table_exists

    if table_exists(con, 'corporate_actions'):
        splits = {(ticker, ex) for ticker, ex, _ in recorded_splits(con, account_id)}
        dividends = set(con.execute('SELECT ticker,ex_date FROM sim_dividends WHERE portfolio_id=?',
                                    [account_id]).fetchall())
        for ticker, ex, kind in con.execute(
            "SELECT ticker,ex_date,kind FROM corporate_actions WHERE ex_date<=? "
            "AND kind IN ('split','dividend') AND value>0 AND isfinite(value) "
            'AND (fetched_at IS NULL OR fetched_at<=?) AND ticker IN ('
            'SELECT ticker FROM sim_fills WHERE portfolio_id=?)', [latest, now, account_id],
        ).fetchall():
            if (ticker, ex) not in (splits if kind == 'split' else dividends):
                starts.append(ex)
    return min(starts) if starts else None


def recover_account(con, account_id, start, end, *, now, short_con=None, verified=False,
                    mutation=None, manage_transaction=True, risk_only=False):
    """One atomic rewind/replay for every historical entry point."""
    from contextlib import nullcontext

    if not verified:
        service.require_verified(con, account_id, now=now,
                                 manage_transaction=manage_transaction)
    latest = con.execute('SELECT MAX(date) FROM sim_equity WHERE portfolio_id=?',
                         [account_id]).fetchone()[0]
    end = max(end, latest) if latest else end
    out = dict(filled=0, rejected=0, expired=0, pending=0, late_settled=0,
               affected_accounts=[], recovered_marks=[], carried={}, sessions=[])
    with db.transaction(con) if manage_transaction else nullcontext():
        checkpoint_day = ledger.restore_checkpoint(con, account_id, start)
        if mutation:
            mutation()
        day = checkpoint_day + timedelta(days=1) if checkpoint_day else start
        if risk_only:
            for event in ledger.events(con, [account_id], since=day, include_risk=True):
                if event.kind != 'equity':
                    ledger.apply_event(con, event)
            halts.restore_risk(con, account_id, now)
            service.require_verified(con, account_id, now=now, manage_transaction=False)
            return out
        while day <= end:
            if nyse.is_session(day):
                result = processor.settle_session(
                    con, day, late=True, short_con=short_con, settled_at=now,
                    portfolio_id=account_id, manage_transactions=False, replay=True)
                out['sessions'].append({'account_id': account_id, 'session_date': day.isoformat(), **result})
                for key in ('filled', 'rejected', 'expired', 'pending', 'late_settled'):
                    out[key] += result[key]
                for key in ('affected_accounts', 'recovered_marks'):
                    out[key] = sorted(set(out[key]) | set(result[key]))
                out['carried'].update(result['carried'])
                if not result['carried'] and not result['pending']:
                    processor._record_account_event(con, account_id, 'late_reconciled',
                                                     {'session_date': day.isoformat()}, now)
            day += timedelta(days=1)
        halts.restore_risk(con, account_id, now)
        service.require_verified(con, account_id, now=now, manage_transaction=False)
    return out
