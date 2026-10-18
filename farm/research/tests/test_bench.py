from farm.research.bench import panel_benchmark, synthetic_benchmark


def test_synthetic_cache_preserves_report_bytes(tmp_path):
    result = synthetic_benchmark(tmp_path / "cache", tmp_path / "reports")
    assert result["primary_bars"] == 11_401
    assert result["secondary_bars"] > 10_000
    assert result["reports_byte_identical"]
    assert result["warm_bytes_read"] > 0
    assert result["warm_verified_load_seconds"] < result["uncached_build_seconds"]


def test_scan_panel_cache_preserves_digest_and_is_faster(tmp_path):
    result = panel_benchmark(
        tmp_path / "cache", ticker_count=300, session_count=500, folds=4,
    )
    assert result["bar_count"] == 148_850
    assert result["event_trades"] == 1_490
    assert result["portfolio_days"] == 500
    assert result["results_byte_identical"]
    assert result["warm_speedup_fraction"] >= 0.80
    assert result["warm_bytes_read"] > 0
