import pytest

from farm.study.bench import build_market, run_benchmark

pytest.mark._config.addinivalue_line("markers", "slow: deterministic performance benchmark")
pytestmark = pytest.mark.slow


def test_synthetic_benchmark_has_required_shape_and_deterministic_bytes():
    data, universe = build_market(ticker_count=48, session_count=45)
    assert len(data.primary.sessions) == 45
    assert len({bar.ticker for bar in data.primary.bars}) == 48
    assert data.primary.dividends
    assert any(data.primary.get("T0000", day) is None for day in data.primary.sessions)
    first = run_benchmark(ticker_count=48, session_count=45, workers=1, folds=3)
    second = run_benchmark(ticker_count=48, session_count=45, workers=1, folds=3)
    assert first["event_trades"] > 100
    assert first["portfolio_days"] == 45
    assert first["result_sha256"] == second["result_sha256"]
