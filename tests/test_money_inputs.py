"""Invalid money inputs never mutate accounting, even without a transaction wrapper."""
from datetime import datetime

import pytest

from engine.accounts import actions
from sim import league, ledger, p15_books, portfolio, settle
from sim.costs import FeeBreakdown
from tests.conftest import SESSIONS, insert_bars
from tests.test_accounts_settle import DAY, PRIOR, SETTLED_AT, _account, _order
from tests.test_settle import D1, D2, D3, _book, _dead_name, _fill, _pending, _terms

BAD = [float('nan'), float('inf'), float('-inf'), -1., 0., True, '10', None]
MONEY_TABLES = ('portfolios', 'sim_positions', 'sim_position_lots', 'sim_fills',
                'sim_fill_fees', 'sim_cash_events', 'sim_dividends')


def _money(con):
    return {name: con.execute(f'SELECT * FROM {name} ORDER BY ALL').fetchall()
            for name in MONEY_TABLES}


@pytest.mark.parametrize('kind,value', [(kind, value) for kind in ('cash', 'stock', 'worthless')
                         for value in BAD if kind == 'cash' or not (type(value) is float and value == 0)])
def test_settlement_price_refusal_leaves_every_row_unchanged(con, kind, value):
    pf = _book(con)
    _dead_name(con)
    insert_bars(con, 'ACQ', [D3], close=20)
    _fill(con, pf, 'EA', 'buy', 10, 100, D1, 1)
    _pending(con, pf, 'EA', 'sell', 10, D2, 2)
    settle.ensure_table(con)
    before = _money(con), con.execute('SELECT * FROM sim_orders ORDER BY id').fetchall()
    with pytest.raises(settle.SettlementRefused):
        settle.settle(con, _terms(kind=kind, price=value,
                     into_ticker='ACQ' if kind == 'stock' else None,
                     ratio=1 if kind == 'stock' else None), apply=True)
    assert (_money(con), con.execute('SELECT * FROM sim_orders ORDER BY id').fetchall()) == before
    assert con.execute('SELECT COUNT(*) FROM sim_settlements').fetchone() == (0,)
    assert con.execute('SELECT COUNT(*) FROM audit_log').fetchone() == (0,)


@pytest.mark.parametrize('value', BAD + [1e308, 1e-308])
def test_stock_ratio_refusal_and_overflow_are_atomic(con, value):
    pf = _book(con)
    _dead_name(con)
    insert_bars(con, 'ACQ', [D3], close=20)
    _fill(con, pf, 'EA', 'buy', 10, 100, D1, 1)
    before = _money(con)
    with pytest.raises(settle.SettlementRefused):
        settle.settle(con, _terms(kind='stock', price=0, into_ticker='ACQ', ratio=value), apply=True)
    assert _money(con) == before


def test_overflow_cash_refused_before_any_book_or_settlement_insert(con):
    for name in ('a', 'b'):
        _book(con, name)
        _fill(con, name, 'EA', 'buy', 10, 100, D1, 1 if name == 'a' else 2)
    _dead_name(con)
    before = _money(con)
    with pytest.raises(settle.SettlementRefused, match='finite'):
        settle.settle(con, _terms(price=1e308), apply=True)
    assert _money(con) == before


@pytest.mark.parametrize('field', ['qty', 'fill_px', 'multiplier'])
@pytest.mark.parametrize('value', BAD + [1e308])
def test_fill_refusal_before_lot_cash_fee_writes(con, book, field, value):
    before = _money(con)
    fill = dict(portfolio_id=book, ticker='AAA', side='buy', qty=10., fill_px=100.,
                multiplier=1., order_id=1, fill_date=SESSIONS[0])
    fill[field] = value
    assert ledger.apply_fill(con, fill) == 0
    assert _money(con) == before


@pytest.mark.parametrize('field', list(FeeBreakdown.__dataclass_fields__)[1:])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1., True, '1'])
def test_each_fee_component_refused_before_any_write(con, book, field, value):
    before = _money(con)
    fees = FeeBreakdown('ibkr_pro_tiered_v1', **{field: value})
    with pytest.raises(ValueError):
        ledger.apply_fill(con, dict(portfolio_id=book, ticker='AAA', side='buy',
                          qty=10, fill_px=100, order_id=1, fill_date=SESSIONS[0]), fees)
    assert _money(con) == before


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), -1., 0., None, 1e308])
@pytest.mark.parametrize('account', [False, True])
def test_dividend_refused_before_cash_or_ledger_write(con, book, value, account):
    _fill(con, book, 'AAA', 'buy', 10, 100, D1, 1)
    con.execute('CREATE TABLE corporate_actions(ticker VARCHAR,ex_date DATE,kind VARCHAR,value DOUBLE,fetched_at TIMESTAMP)')
    con.execute("INSERT INTO corporate_actions VALUES ('AAA',?,'dividend',?,NULL)", [D2, value])
    before = _money(con)
    with pytest.raises(ValueError):
        if account:
            actions.credit_dividends(con, book, D2, datetime(2024, 6, 5))
        else:
            portfolio.credit_dividends(con, D2)
    assert _money(con) == before


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), True, '1', None])
def test_cash_event_refusal_is_atomic(con, book, value):
    before = _money(con)
    with pytest.raises(ValueError):
        ledger.apply_cash_event(con, dict(portfolio_id=book, event_date=D2,
                                kind='adjustment', amount=value))
    assert _money(con) == before


@pytest.mark.parametrize('qty', [float('nan'), float('inf'), -1., 0.])
@pytest.mark.parametrize('side', ['buy', 'sell', 'invalid'])
def test_retained_legacy_order_gets_one_explicit_terminal_refusal(con, book, qty, side):
    insert_bars(con, 'AAA', SESSIONS[:2])
    con.execute('INSERT INTO sim_orders VALUES (1,?,?,?, ?,?,\'pending\',NULL)',
                [book, 'AAA', side, qty, SESSIONS[0]])
    before = _money(con)
    assert league.fill_pending(con, SESSIONS[1]) == {'filled': 0, 'rejected': 1, 'pending': 0}
    assert _money(con) == before
    assert con.execute('SELECT reject_reason FROM sim_orders').fetchone()[0].startswith('invalid_order:')
    assert con.execute('SELECT outcome,reject_reason FROM sim_execution_attempts').fetchone()[0] == 'rejected'
    assert league.fill_pending(con, SESSIONS[1]) == {'filled': 0, 'rejected': 0, 'pending': 0}


@pytest.mark.parametrize('qty', [float('nan'), float('inf'), -1., 0.])
def test_account_retained_order_refused_explicitly(con, qty):
    from engine.accounts.settle import _fill_attempt, _settle_order
    from sim.schema import portfolio_account

    _account(con, 'a')
    insert_bars(con, 'AAA', [PRIOR, DAY])
    oid = _order(con, 'a', 'AAA', 'buy', qty, 'moo', datetime(2026, 10, 12, 13, 20))
    before = _money(con)
    row = dict(order_id=oid, portfolio_id='a', ticker='AAA', side='buy', qty=qty,
               limit_px=None, order_type='moo', received_at=datetime(2026, 10, 12, 13, 20),
               state_reason=None, execution_profile='baseline_v1')
    settings = portfolio_account(con, 'a')
    attempt = _fill_attempt(con, row, settings, DAY, SETTLED_AT)
    assert attempt.status == 'rejected'
    assert _settle_order(con, row, attempt, settings, DAY, SETTLED_AT, False, con, set(), {}) == 'rejected'
    assert _money(con) == before
    assert con.execute('SELECT state_reason FROM sim_order_details WHERE order_id=?', [oid]).fetchone()[0].startswith('invalid_order:')


@pytest.mark.parametrize('field', ['qty', 'signal_close', 'limit_px', 'entry_atr'])
@pytest.mark.parametrize('value', BAD)
def test_p15_intake_refuses_invalid_numbers_before_insert(con, field, value):
    p15_books.init_schema(con)
    kwargs = dict(decision_id=None, portfolio_id=p15_books.BOOK_IDS[0], ticker='AAA',
                  side='buy', qty=10, signal_date=D1, role='entry', priority=1,
                  signal_close=100, entry_atr=2, limit_px=103, created_at=datetime(2024, 6, 4))
    kwargs[field] = value
    with pytest.raises(p15_books.P15BookError):
        p15_books._add_intent(con, **kwargs)
    assert con.execute('SELECT COUNT(*) FROM p15_order_intents').fetchone() == (0,)


@pytest.mark.parametrize('value', ['nan', 'inf', '-inf', '-1', '0', '1e308'])
def test_cli_settlement_refuses_invalid_terms_without_mutation(tmp_path, value, capsys):
    from engine.lib import db
    from sim.schema import init_sim_schema
    from tests.conftest import PRICES_DDL

    path = tmp_path / 'market.duckdb'
    con = db.connect(path)
    con.execute(PRICES_DDL)
    init_sim_schema(con)
    pf = _book(con)
    _dead_name(con)
    _fill(con, pf, 'EA', 'buy', 10, 100, D1, 1)
    before = _money(con)
    con.close()
    assert settle.main(['--db', str(path), '--ticker', 'EA', '--kind', 'cash',
                        f'--price={value}', '--effective', str(D3), '--source', 'test', '--apply']) == 2
    con = db.connect(path, read_only=True)
    try:
        assert _money(con) == before
        assert con.execute('SELECT COUNT(*) FROM audit_log').fetchone() == (0,)
    finally:
        con.close()


@pytest.mark.parametrize('stop_atr', [float('nan'), float('inf'), -1, 0, 100])
def test_p15_invalid_or_nonpositive_computed_stop_refused_before_money(con, stop_atr):
    from sim import fills
    from tests.test_p15_books import _activate

    signal, day = SESSIONS[:2]
    _activate(con, signal)
    book = p15_books.BOOK_IDS[0]
    insert_bars(con, 'AAA', SESSIONS[:2])
    con.execute('INSERT INTO p15_order_intents VALUES (1,NULL,?,\'AAA\',\'buy\',1,?,\'entry\',1,100,?,103,\'pending\',NULL,NULL,?)',
                [book, signal, stop_atr, datetime(2024, 6, 4)])
    intent = con.execute('SELECT id,portfolio_id,ticker,side,qty,signal_date,order_role,priority,signal_close,entry_atr,limit_px FROM p15_order_intents').fetchone()
    before = _money(con)
    result = fills.attempt_fill(con, 'AAA', 'buy', 1, signal, day)
    assert p15_books._terminal_order(con, intent, day, result) == 'rejected'
    assert _money(con) == before
    assert con.execute('SELECT reason FROM p15_order_intents').fetchone()[0].startswith('invalid_order:')


@pytest.mark.parametrize('field', ['quantity', 'limit_price'])
@pytest.mark.parametrize('value', BAD)
def test_v2_api_intake_refuses_bad_quantities_limits_before_rows(con, field, value):
    from engine import paper_accounts
    from tests.test_paper_accounts import MOO_RECEIVED, _intent_v2, _spec_v2

    spec = _spec_v2()
    paper_accounts.create_account(con, spec, now=MOO_RECEIVED)
    intent = _intent_v2(order_type='limit', limit_price=100)
    intent[field] = value
    before = _money(con)
    with pytest.raises(paper_accounts.AccountRefused):
        paper_accounts.submit_intent(con, intent, now=MOO_RECEIVED)
    assert _money(con) == before
    assert con.execute('SELECT COUNT(*) FROM sim_orders').fetchone() == (0,)
