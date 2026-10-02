from datetime import date

from farm.study.benchmark import Benchmark
from farm.study.costs import CostSelection
from farm.study.data import Bar, MarketData, PriceSource
from farm.study.protocol import run_identity
from farm.study.simulate import simulate_events
from farm.study.spec import EventStrategy, ExitRule, FillPoint, Order
from farm.study.universe import ListingInterval, Universe

D0, D1, D2 = (date(2024, 1, day) for day in (2, 3, 4))
COSTS = CostSelection("ibkr_tiered_auction_v1", ("ibkr_fixed_v1",))


def _never(view, position):
    return False


def _conditional_order(view, session):
    return ([Order("AAA", "long", FillPoint.open_auction(),
                   ExitRule.first_condition(_never, 4), 1_000)] if session == D0 else [])


def _fixed_order(view, session):
    return ([Order("AAA", "long", FillPoint.open_auction(),
                   ExitRule.after_n_sessions(2, at=FillPoint.close_auction()), 1_000)]
            if session == D0 else [])


def _market(bars):
    source = PriceSource.declared(source="followup-3", bars=bars)
    return (MarketData(source),
            Universe(source, (ListingInterval("AAA", D0), ListingInterval("MARKET", D0))))


def _bar(ticker, session):
    return Bar(ticker, session, 100, 101, 99, 100, 1_000_000)


def test_window_end_can_exclude_a_conditional_exit_beyond_the_run():
    data, universe = _market([_bar("AAA", day) for day in (D0, D1)])
    default = EventStrategy("strategy", "pre_open", _conditional_order, 1, 1_000,
                            close_as_indication=True)
    force_closed = simulate_events(default, data, universe, (D0, D1), COSTS, Benchmark("cash"))
    strict = EventStrategy("strategy", "pre_open", _conditional_order, 1, 1_000,
                           close_as_indication=True, window_end="unevaluable")
    excluded = simulate_events(strict, data, universe, (D0, D1), COSTS, Benchmark("cash"))
    assert len(force_closed.trades) == 1 and force_closed.trades[0].exit_session == D1
    assert excluded.trades == ()
    assert excluded.unfilled_counts == {"unevaluable_window_end": 1}
    assert run_identity(default, COSTS, data.primary.declaration.snapshot_sha256).sha256 != \
        run_identity(strict, COSTS, data.primary.declaration.snapshot_sha256).sha256


def test_complete_path_can_exclude_an_internal_missing_bar():
    data, universe = _market([_bar("AAA", D0), _bar("MARKET", D1), _bar("AAA", D2)])
    default = EventStrategy("strategy", "pre_open", _fixed_order, 1, 1_000)
    recorded = simulate_events(default, data, universe, (D0, D2), COSTS, Benchmark("cash"))
    strict = EventStrategy("strategy", "pre_open", _fixed_order, 1, 1_000,
                           require_complete_path=True)
    excluded = simulate_events(strict, data, universe, (D0, D2), COSTS, Benchmark("cash"))
    assert len(recorded.trades) == 1 and excluded.trades == ()
    assert excluded.unfilled_counts == {"unevaluable_incomplete_path": 1}
    assert run_identity(default, COSTS, data.primary.declaration.snapshot_sha256).sha256 != \
        run_identity(strict, COSTS, data.primary.declaration.snapshot_sha256).sha256
