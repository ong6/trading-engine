from datetime import date, datetime, timezone

import pytest

from farm.study.benchmark import Benchmark, gross_returns
from farm.study.costs import CostSelection, calculate
from farm.study.data import Bar, DerivedInput, Dividend, LookAheadError, MarketData, PriceSource
from farm.study.protocol import run_identity
from farm.study.report import build_report
from farm.study.simulate import simulate_events, simulate_portfolio
from farm.study.spec import EventStrategy, ExitRule, FillPoint, Order, PortfolioStrategy
from farm.study.universe import ListingInterval, Universe

D0, D1, D2 = (date(2024, 1, day) for day in (2, 3, 4))
COSTS = CostSelection("ibkr_tiered_auction_v1", ("ibkr_fixed_v1",))


def _bar(ticker, day, open_px=100.0, close=100.0):
    return Bar(ticker, day, open_px, max(open_px, close), min(open_px, close), close,
               1_000_000)


def _market(bars, *, dividends=(), derived=()):
    source = PriceSource.declared(source="followup-2", bars=bars, dividends=dividends)
    listings = tuple(ListingInterval(ticker, min(
        bar.session for bar in bars if bar.ticker == ticker))
        for ticker in sorted({bar.ticker for bar in bars}))
    return MarketData(source, derived_inputs=derived), Universe(source, listings)


def _one_order(view, session):
    return ([Order("AAA", "long", FillPoint.open_auction(),
                   ExitRule.same_session_close(), 750)] if session == D0 else [])


def test_exit_cost_can_use_registered_entry_notional_and_default_is_unchanged():
    data, universe = _market([_bar("AAA", D0, 100, 110)])
    default = simulate_events(EventStrategy("default", "pre_open", _one_order, 1, 750),
                              data, universe, [D0], COSTS, Benchmark("cash"))
    registered = simulate_events(
        EventStrategy("registered", "pre_open", _one_order, 1, 750,
                      exit_cost_basis="entry_notional"),
        data, universe, [D0], COSTS, Benchmark("cash"))
    assert default.trades[0].costs_by_profile[COSTS.primary]["exit"] == pytest.approx(
        calculate(COSTS.primary, side="sell", notional=825, fill_price=110).total)
    expected_exit = calculate(COSTS.primary, side="sell", notional=750, fill_price=110)
    assert expected_exit.shares == pytest.approx(750 / 110)
    assert registered.trades[0].costs_by_profile[COSTS.primary]["exit"] == pytest.approx(
        expected_exit.total)
    assert run_identity(EventStrategy("basis", "pre_open", _one_order, 1, 750), COSTS,
                        data.primary.declaration.snapshot_sha256).sha256 != run_identity(
        EventStrategy("basis", "pre_open", _one_order, 1, 750,
                      exit_cost_basis="entry_notional"), COSTS,
        data.primary.declaration.snapshot_sha256).sha256
    report = _report(data, registered, Benchmark("cash"))
    assert "exit costs on entry notional (registered approximation)" in report["caveats"]


def _close_above_105(view, position):
    return view.value(position.ticker, "close") > 105


def _entry_session_order(view, session):
    return ([Order("AAA", "long", FillPoint.open_auction(),
                   ExitRule.first_condition(_close_above_105, 1,
                                            first_check="entry_session"), 1_000)]
            if session == D0 else [])


def test_first_condition_can_check_the_entry_session_and_rejects_incompatible_fill():
    data, universe = _market([_bar("AAA", D0, 100, 110), _bar("AAA", D1, 100, 100)])
    ledger = simulate_events(
        EventStrategy("same-day-condition", "pre_open", _entry_session_order, 1, 1_000,
                      close_as_indication=True),
        data, universe, (D0, D1), COSTS, Benchmark("cash"))
    assert (ledger.trades[0].exit_session, ledger.trades[0].exit_reason) == (
        D0, "first_condition")
    with pytest.raises(ValueError, match="entry fill.*exit decision"):
        Order("AAA", "long", FillPoint.close_auction(),
              ExitRule.first_condition(_close_above_105, 1,
                                       first_check="entry_session"), 1_000)


def _eligible_from_function(view, window):
    assert window == (D0, D1)
    return {"AAA"}


def _late_eligible(view, window):
    view.value("AAA", "close")
    return {"AAA"}


def _benchmark_order(view, session):
    return ([Order("AAA", "long", FillPoint.open_auction(),
                   ExitRule.after_n_sessions(1, at=FillPoint.close_auction()), 1_000)]
            if session == D0 else [])


def test_equal_weight_eligible_uses_only_point_in_time_names_and_fails_on_lookahead():
    bars = [_bar("AAA", D0), _bar("AAA", D1, 100, 110),
            _bar("BBB", D0), _bar("BBB", D1, 100, 90)]
    eligibility = DerivedInput("membership", [
        {"session": D0, "ticker": ticker,
         "available_at": datetime(2024, 1, 2, 14, tzinfo=timezone.utc),
         "eligible": ticker == "AAA"} for ticker in ("AAA", "BBB")])
    data, universe = _market(bars, derived=(eligibility,))
    assert gross_returns(Benchmark("ew_eligible", eligible=eligibility), data, [D0, D1],
                         universe=universe) == pytest.approx([0.1])
    assert gross_returns(Benchmark("ew_eligible", eligible=_eligible_from_function), data,
                         [D0, D1], universe=universe) == pytest.approx([0.1])
    with pytest.raises(LookAheadError):
        simulate_events(EventStrategy("late", "pre_open", _benchmark_order, 1, 1_000),
                        data, universe, (D0, D1), COSTS,
                        Benchmark("ew_eligible", eligible=_late_eligible))


def _priority_orders(view, session):
    if session == D0:
        return [Order("HELD", "long", FillPoint.open_auction(),
                      ExitRule.after_n_sessions(2, at=FillPoint.close_auction()), 1_000)]
    if session == D1:
        return [Order("WEAK", "long", FillPoint.open_auction(),
                      ExitRule.same_session_close(), 1_000, priority=1,
                      signal={"strength": 1}),
                Order("HELD", "long", FillPoint.open_auction(),
                      ExitRule.same_session_close(), 1_000, priority=3),
                Order("STRONG", "long", FillPoint.open_auction(),
                      ExitRule.same_session_close(), 1_000, priority=2,
                      signal={"z": 2, "strength": 2})]
    return []


def test_priority_fills_the_free_slot_after_already_held_rejection():
    bars = [_bar(ticker, day) for ticker in ("HELD", "STRONG", "WEAK")
            for day in (D0, D1, D2)]
    data, universe = _market(bars)
    strategy = EventStrategy("priority", "pre_open", _priority_orders, 2, 1_000,
                             max_new_per_session=3,
                             order_sort_key=("-priority", "ticker"))
    ledger = simulate_events(strategy, data, universe, (D0, D2), COSTS, Benchmark("cash"))
    assert [(row.ticker, row.entry_session) for row in ledger.trades] == [
        ("HELD", D0), ("STRONG", D1)]
    assert ledger.rejected_counts == {"already_held": 1, "max_concurrent": 1}
    signal = next(row for row in ledger.trades if row.ticker == "STRONG").as_dict()[
        "signal"]
    assert list(signal) == ["strength", "z"] and signal == {"strength": 2.0, "z": 2.0}


def _dividend_order(view, session):
    return ([Order("AAA", "long", FillPoint.open_auction(),
                   ExitRule.after_n_sessions(2, at=FillPoint.close_auction()), 1_000)]
            if session == D0 else [])


def _long_weights(view, session):
    return {"AAA": 1.0}


def test_cash_dividend_is_credited_to_trades_benchmarks_and_portfolios():
    warmup = date(2024, 1, 1)
    dividend = Dividend("AAA", D1, 1.0,
                        datetime(2024, 1, 2, 12, tzinfo=timezone.utc))
    bars = [_bar(ticker, day) for ticker in ("AAA", "BBB")
            for day in (warmup, D0, D1, D2)]
    data, universe = _market(bars, dividends=(dividend,))
    strategy = EventStrategy("dividend", "pre_open", _dividend_order, 1, 1_000,
                             dividend_withholding=0.2)
    ledger = simulate_events(strategy, data, universe, (D0, D2), COSTS,
                             Benchmark("ticker", "AAA"))
    trade = ledger.trades[0]
    assert (trade.gross_dividend_cash, trade.dividend_cash) == pytest.approx((10, 8))
    assert trade.gross_return == pytest.approx(0.008)
    assert trade.benchmark_return == pytest.approx(0.008)
    assert gross_returns(Benchmark("ticker", "AAA"), data, [D0, D1, D2],
                         dividend_withholding=0.2) == pytest.approx([0.008, 0])
    assert gross_returns(Benchmark("ew"), data, [D0, D1], universe=universe,
                         dividend_withholding=0.2) == pytest.approx([0.004])
    portfolio = simulate_portfolio(
        PortfolioStrategy("dividend", "pre_open", _long_weights, (D0,),
                          FillPoint.open_auction(), dividend_withholding=0.2),
        data, universe, (D0, D2), COSTS, Benchmark("cash"))
    assert sum(row.dividend_cash for row in portfolio.days) == pytest.approx(800)
    report = _report(data, ledger, Benchmark("ticker", "AAA"))
    assert report["dividends"] == {"withholding_rate": 0.2,
                                   "gross_of_withholding_cash": 10.0,
                                   "net_cash": 8.0}


def test_dividends_require_an_availability_timestamp():
    with pytest.raises(ValueError, match="availability timestamp"):
        Dividend("AAA", D1, 1.0, None)


def _report(data, ledger, benchmark):
    trade = ledger.trades[0]
    return build_report(
        identity="f" * 64, data=data, costs=COSTS, benchmark=benchmark,
        variants=[{"variant": "x", "net_return": trade.net_return,
                   "benchmark_return": trade.benchmark_return,
                   "excess_return": trade.excess_return,
                   "absolute_net_positive": trade.absolute_net_positive,
                   "trades": 1, "one_sided_t": 0.0}], folds=[], hard_max_date=D2,
        ledger=ledger, runtime_seconds=0.0, worker_count=1, job_count=1,
        serial_parallel_identical=True)
