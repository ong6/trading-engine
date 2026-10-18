"""Revision-15 admission, cleanup, execution and board agree on the same evidence."""
from datetime import date

import pandas as pd
import pytest

from engine import price_quarantine, screen
from engine.lib import db
from engine.lib.data_quality import price_bar_reasons, trusted_bar, trusted_bar_sql
from server import market_read_models, position_read_models
from sim import league, portfolio
from tests.read_model_helpers import liquid_universe


def test_admission_cleanup_screen_fill_mark_and_board(con, book):
    signal, day, next_day = date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)
    liquid_universe(con, ('SPY',))
    good = dict(ticker='AAA', date=signal, open=10., high=11., low=9., close=10.5,
                volume=1000000, source='fixture')
    assert db.upsert_prices(con, pd.DataFrame([good])) == 1
    assert db.upsert_prices(con, pd.DataFrame([{**good, 'ticker': 'SPY', 'date': day}])) == 1
    bad = {**good, 'date': day, 'high': 10., 'close': 10.8}
    assert price_bar_reasons(bad) == ['high_geometry']
    assert not trusted_bar(tuple(bad[f] for f in ('open', 'high', 'low', 'close', 'volume')))
    assert db.upsert_prices(con, pd.DataFrame([bad])) == 0
    # A legacy retained row models the pre-cleanup store. It must never mark or fill.
    con.execute('INSERT INTO prices(ticker,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)',
                [bad[f] for f in ('ticker', 'date', 'open', 'high', 'low', 'close', 'volume')])
    con.execute("INSERT INTO sim_positions VALUES (?,'AAA',2,10)", [book])
    con.execute("INSERT INTO sim_orders VALUES (1,?,'AAA','buy',1,?,'pending',NULL)", [book, signal])
    assert league.fill_pending(con, day) == {'filled': 0, 'rejected': 0, 'pending': 1}
    assert position_read_models._position_closes(con, day, ['AAA']) == {'AAA': 10.5}
    original_valid = con.execute(f'SELECT * FROM prices WHERE {trusted_bar_sql()} ORDER BY ALL').fetchall()
    dry = price_quarantine.cleanup_hard_invalid_prices(con)
    assert dry['invalid_rows'] == dry['tickers'] == 1 and dry['moved'] == 0
    applied = price_quarantine.cleanup_hard_invalid_prices(con, dry_run=False)
    assert applied['moved'] == 1
    assert price_quarantine.cleanup_hard_invalid_prices(con)['invalid_rows'] == 0
    assert con.execute(f'SELECT * FROM prices WHERE {trusted_bar_sql()} ORDER BY ALL').fetchall() == original_valid
    bars = screen.pull_bars(con, day, ['AAA'])
    assert len(bars) == 1 and bars.iloc[0]['date'].date() == signal
    assert league.fill_pending(con, day)['filled'] == 0
    marked = portfolio.mark_to_market(con, book, day)
    assert marked['carried'] == ['AAA']
    assert marked['equity'] == pytest.approx(portfolio.get_cash(con, book) + 21.)
    projected = position_read_models.positions(con, book, discretionary_id='discretionary')['positions'][0]
    assert projected['close'] == 10.5 and projected['market_value'] == 21.
    quality = projected['retained_bar_quality']
    assert quality['invalid_count'] == 1 and quality['latest_invalid_date'] == day
    assert market_read_models.retained_bar_quality(con, ['AAA'], day)['AAA'] == quality
    assert db.upsert_prices(con, pd.DataFrame([{**good, 'date': next_day}])) == 1
    assert db.upsert_prices(con, pd.DataFrame([{**good, 'ticker': 'SPY', 'date': next_day}])) == 1
    assert league.fill_pending(con, next_day)['filled'] == 1
    marked = portfolio.mark_to_market(con, book, next_day)
    projected = position_read_models.positions(con, book, discretionary_id='discretionary')['positions'][0]
    assert projected['market_value'] == pytest.approx(portfolio.get_positions(con, book)['AAA']['qty'] * 10.5)
    assert marked['equity'] == pytest.approx(portfolio.get_cash(con, book) + projected['market_value'])
    assert projected['retained_bar_quality']['invalid_count'] == 1


def test_valid_archive_receipts_do_not_become_board_rejections(con):
    day = date(2026, 10, 16)
    good = dict(ticker='AAA', date=day, open=10., high=11., low=9., close=10.5,
                volume=100, source='fixture')
    assert db.upsert_prices(con, pd.DataFrame([good, good])) == 1
    db.append_price_observations(con, [good], reason='split_restatement_predecessor', batch_id='split')
    quality = market_read_models.retained_bar_quality(con, ['AAA'], day)['AAA']
    assert quality['retained_count'] == 1 and quality['invalid_count'] == 0


@pytest.mark.parametrize('family', ['sector', 'xs'])
def test_revision15_migrates_after_v2_break_and_preserves_frozen_outcomes(con, monkeypatch, family):
    import copy

    from engine import forward_review as sector
    from engine import xs_forward_review as xs
    from tests.test_forward_review import _prior_v6_result, _test_baseline
    from tests.test_xs_forward_review import _freeze, _setup, _transition

    review = sector if family == 'sector' else xs
    if family == 'sector':
        _test_baseline.__wrapped__(monkeypatch)
        result = review.migrate_runtime_contract(con, _prior_v6_result(con))
    else:
        _setup(con)
        waiting = _freeze(con)
        _transition(con)
        result = review.evaluate(con, prior_result=waiting)
    for book in (review.CANDIDATE_ID, review.CONTROL_ID):
        con.execute("INSERT INTO sim_book_breaks VALUES (?, DATE '2026-10-19', 'cost_profile', "
                    "'baseline_v1', 'ibkr_pro_tiered_v1', 14, 'D0', current_timestamp)", [book])
    prior = review.evaluate(con, prior_result=result)
    prior = copy.deepcopy(prior)
    prior['frozen_runtime'].update(
        runtime_contract_version=review.PRIOR_RUNTIME_CONTRACT_VERSION,
        runtime_contract_sha256=review.PRIOR_RUNTIME_CONTRACT_SHA256,
        runtime_contract_files=list(review.PRIOR_RUNTIME_CONTRACT_FILES),
        superseded_runtime_contract_sha256=review.PRIOR_SUPERSEDED_RUNTIME_CONTRACT_SHA256,
        runtime_contract_migration=review.PRIOR_RUNTIME_CONTRACT_MIGRATION)
    if family == 'xs':
        prior['frozen_runtime']['signal_boundary']['protocol_contract']['runtime_contract_sha256'] = review.PRIOR_RUNTIME_CONTRACT_SHA256
    migrated = review.migrate_runtime_contract(con, prior)
    for section in ('status', 'candidate', 'control', 'criterion', 'observation', 'execution', 'metrics'):
        assert migrated[section] == prior[section]
    assert review.evaluate(con, prior_result=migrated) == migrated
    assert review.evaluate(con, prior_result=migrated) == migrated
    changed = copy.deepcopy(prior)
    changed['observation']['equity_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='checkpoint|previously published'):
        review.migrate_runtime_contract(con, changed)
