"""Round-4 regressions for consumers of the shared account ledger."""
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.accounts import cli, service
from engine.lib import db
from server import agent_evaluation
from sim import fills, ledger, margin, p15_books, portfolio
from sim.costs import FeeBreakdown
from sim.schema import set_portfolio_account
from tests.test_p22_round2 import DAY, PRIOR, Harness
from tools import migrate_cost_profiles


@pytest.fixture
def h(tmp_path, monkeypatch):
    return Harness(tmp_path, monkeypatch)


@pytest.mark.parametrize('book_id', p15_books.BOOK_IDS)
@pytest.mark.parametrize('migrated', [False, True])
def test_p15_fee_aware_resize_validates(con, monkeypatch, book_id, migrated):
    agent_evaluation.init_schema(con)
    p15_books.initialize_books(con, PRIOR)
    if migrated:
        migrate_cost_profiles.migrate(con, DAY)
    con.execute(
        "INSERT INTO p15_order_intents VALUES "
        "(1,NULL,?,'SPY','buy',1,?,'spy_reinvest',99,100,NULL,NULL,"
        "'pending',NULL,NULL,CURRENT_TIMESTAMP)", [book_id, PRIOR])
    result = fills.FillResult(status='filled', open_px=624.999375, fill_px=624.999375,
                              slippage_bps=0, cost_bps=0, execution_profile='baseline_v1',
                              median_dollar_vol=1e9, participation=0, impact_bps=0, fee_bps=0)
    monkeypatch.setattr(fills, 'attempt_fill', lambda *_args: result)
    intent = (1, book_id, 'SPY', 'buy', 1., PRIOR, 'spy_reinvest', 99, 100., None, None)
    assert p15_books._terminal_order(con, intent, DAY, result) == 'filled'
    assert con.execute('SELECT qty FROM sim_fills').fetchone()[0] == (15 if migrated else 16)
    agent_evaluation.validate_p15_evidence(con, generated_at=datetime(2026, 10, 8, tzinfo=timezone.utc))


def _fill(con, book, order_id, day, side, qty, px=100):
    fill = dict(order_id=order_id, portfolio_id=book, ticker='XYZ', side=side,
                qty=qty, fill_date=day, fill_px=px)
    ledger.apply_fill(con, fill)
    con.execute('INSERT INTO sim_fills VALUES (?,?,?,?,?,?,?, ?,0,0)',
                [order_id, book, 'XYZ', side, qty, day, px, px])


@pytest.mark.parametrize('side', ['buy', 'short'])
def test_ex_date_fill_never_gets_dividend_on_retry(con, book, side):
    db.init_actions_schema(con)
    set_portfolio_account(con, book, account_type='margin')
    con.execute("INSERT INTO corporate_actions VALUES ('XYZ',?,'dividend',1,'fixture',now())", [DAY])
    assert portfolio.credit_dividends(con, DAY)['amount'] == 0
    _fill(con, book, 1, DAY, side, 10)
    assert portfolio.credit_dividends(con, DAY)['amount'] == 0


@pytest.mark.parametrize('side,expected', [('buy', 10), ('short', -10)])
def test_late_dividend_uses_historical_units(con, book, side, expected):
    db.init_actions_schema(con)
    set_portfolio_account(con, book, account_type='margin')
    _fill(con, book, 1, PRIOR, side, 10)
    con.execute("INSERT INTO corporate_actions VALUES ('XYZ',?,'dividend',1,'fixture',now())", [DAY])
    split_day = DAY + timedelta(days=1)
    con.execute("INSERT INTO split_adjustments (ticker,ex_date,ratio,outcome) "
                "VALUES ('XYZ',?,2,'applied')", [split_day])
    ledger.rebuild_state(con, [book])
    assert portfolio.credit_dividends(con, split_day)['amount'] == expected
    assert portfolio.credit_dividends(con, split_day)['amount'] == 0


def test_p15_cash_prefix_includes_fees(con, book):
    con.execute('UPDATE portfolios SET initial_cash=10000')
    _fill(con, book, 1, PRIOR, 'buy', 1)
    ledger._persist_fees(con, 1, FeeBreakdown("baseline_v1", commission=1, total_usd=1))
    _fill(con, book, 2, DAY, 'buy', 1)
    assert agent_evaluation._cash_before_fill(con, book, 2) == 9899


def test_late_recovery_preserves_resume_anchor(h):
    h.create()
    h.history('LONG', 'buy', 100, 100)
    with h.con(h.daily) as con:
        con.execute("UPDATE free_daily_bars SET c=20 WHERE ticker='LONG' AND date=?", [DAY])
    assert h.night() == 0
    with h.con() as con:
        assert con.execute("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'").fetchone()[0] == 'halted'
        service.resume(con, 'acct-a', resumed_by='owner', now=datetime.combine(DAY, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=22))
    anchor = h.scalar("SELECT drawdown_anchor_equity FROM account_state WHERE portfolio_id='acct-a'")
    assert cli.main(['settle', '--late', '--date', DAY.isoformat()]) == 0
    assert h.scalar("SELECT prior_close_equity FROM account_state WHERE portfolio_id='acct-a'") == anchor
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'active'


@pytest.mark.parametrize('mutation', [
    "UPDATE sim_position_lots SET qty=qty+1",
    "UPDATE sim_position_lots SET avg_px=avg_px+1",
    "UPDATE sim_position_lots SET opened_session=opened_session-1",
    "UPDATE sim_equity SET equity=equity+100",
])
def test_verify_halts_persisted_lot_or_equity_mismatch(h, mutation):
    h.create()
    h.order('open', 'LONG', 'buy', 10)
    assert h.night() == 0
    with h.con() as con:
        con.execute(mutation)
    assert cli.main(['verify', 'acct-a']) != 0
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'halted'
    assert h.scalar("SELECT COUNT(*) FROM account_reconciliations WHERE status='mismatch'") == 1


def test_day_trade_preview_matches_fifo(con, book):
    _fill(con, book, 1, PRIOR, 'buy', 10)
    _fill(con, book, 2, DAY, 'buy', 1)
    assert not margin.would_create_day_trade(con, book, 'XYZ', 'sell', 1, DAY)
    assert margin.would_create_day_trade(con, book, 'XYZ', 'sell', 11, DAY)
    assert con.execute('SELECT SUM(qty) FROM sim_position_lots').fetchone()[0] == 11


@pytest.mark.parametrize('whole', [True, False])
def test_v2_creation_accepts_whole_shares(h, whole):
    assert h.create(whole_shares=whole)['account_id'] == 'acct-a'


def test_settlement_runbook_bash_syntax():
    text = (Path(__file__).resolve().parents[1] / 'docs/settlement-runbook.md').read_text()
    blocks = re.findall(r'^```bash\n(.*?)^```', text, re.M | re.S)
    assert blocks
    for number, block in enumerate(blocks, 1):
        result = subprocess.run(['bash', '-n'], input=block, text=True, capture_output=True)
        assert result.returncode == 0, f'bash block {number}: {result.stderr}'


@pytest.mark.parametrize('delta,status', [(0.004, 'ok'), (0.006, 'mismatch')])
def test_verify_equity_half_cent_tolerance(h, delta, status):
    h.create()
    h.order('open', 'LONG', 'buy', 10)
    assert h.night() == 0
    with h.con() as con:
        con.execute('UPDATE sim_equity SET equity=equity+?', [delta])
    assert cli.main(['verify', 'acct-a']) == int(status == 'mismatch')
    assert h.scalar("SELECT COUNT(*) FROM account_reconciliations WHERE status='mismatch'") == int(status == 'mismatch')


def test_verify_uses_selected_source_for_equity(h):
    h.create()
    with h.con(h.daily) as con:
        con.execute("UPDATE free_daily_bars SET c=120 WHERE ticker='LONG' AND date=?", [DAY])
    h.order('open', 'LONG', 'buy', 10)
    assert h.night() == 0
    assert cli.main(['verify', 'acct-a']) == 0
    assert h.scalar("SELECT COUNT(*) FROM account_reconciliations WHERE status='mismatch'") == 0


def test_late_recovery_does_not_hide_equity_corruption(h):
    h.create()
    h.history('SHORT', 'buy', 10, 100)
    assert h.night() == 0
    with h.con() as con:
        con.execute('UPDATE sim_equity SET equity=equity+100')
    assert cli.main(['settle', '--late', '--date', DAY.isoformat()]) != 0
    assert h.scalar("SELECT pa_status FROM portfolio_accounts_v WHERE portfolio_id='acct-a'") == 'halted'
    assert h.scalar("SELECT COUNT(*) FROM account_reconciliations WHERE status='mismatch'") == 1
