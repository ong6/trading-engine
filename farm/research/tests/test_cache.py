import concurrent.futures
import importlib
import shutil
from dataclasses import replace

import numpy as np
import pandas as pd

from engine.lib.resources import write_text_atomic
from farm.research.cache import (
    CacheCorruption,
    CacheError,
    PanelCacheIdentity,
    ResearchCache,
    TableCacheIdentity,
    UniverseCacheIdentity,
)
from farm.study.bench import build_market
from farm.study.synthetic import generate_market

pytest = importlib.import_module("pytest")


def _identity(kind, revision="v1"):
    return {
        "kind": kind,
        "source_parts": ["a" * 64],
        "columns": ["open", "close"],
        "date_range": ["2024-01-01", "2024-12-31"],
        "normalization": "v1",
        "quality": revision,
        "calendar": "XNYS-v1",
        "availability": "daily-close",
        "universe": "pit-v1",
        "recipe": "fixture-v1",
    }


def _panel_identity(source, revision="v1"):
    return PanelCacheIdentity.from_source(
        source,
        normalization_version="v1",
        quality_version=revision,
        calendar_version="XNYS-v1",
        availability_version="daily-close-v1",
    )


def _universe_identity(universe):
    return UniverseCacheIdentity.from_universe(
        universe,
        recipe_sha256="4" * 64,
        coverage_version="pit-v1",
    )


def _table_identity(frame, family, revision="v1"):
    return TableCacheIdentity.from_frame(
        frame,
        recipe_sha256=("7" if revision == "v1" else "8") * 64,
        availability_version="daily-close-v1",
        family=family,
    )


def test_panel_and_universe_cold_warm_are_read_only_and_byte_equivalent(tmp_path):
    cache = ResearchCache(tmp_path / "cache")
    market, universe = build_market(ticker_count=48, session_count=45)
    builds = 0

    def panel_builder():
        nonlocal builds
        builds += 1
        return market.primary

    identity = _panel_identity(market.primary)
    cold = cache.panel(identity, panel_builder)
    warm = cache.panel(identity, panel_builder)
    assert not cold.object.hit and warm.object.hit and builds == 2
    assert warm.source.declaration == market.primary.declaration
    assert warm.source.tickers == market.primary.tickers
    assert warm.source.sessions == market.primary.sessions
    assert list(warm.source.bars) == list(market.primary.bars)
    with pytest.raises(ValueError):
        warm.source.panel.fields["close"][0, 0] = 0

    cached_universe = cache.universe(
        _universe_identity(universe), warm, lambda: universe,
        exclusions={"T0001": ["coverage"]},
    )
    assert cached_universe.universe.listings == universe.listings
    assert cached_universe.coverage.shape == (48, 45)
    assert cached_universe.exclusions == {"T0001": ("coverage",)}
    assert not cached_universe.coverage.flags.writeable


def test_cache_refuses_corruption_schema_drift_and_identity_staleness(tmp_path):
    cache = ResearchCache(tmp_path / "cache")
    market, _ = build_market(ticker_count=32, session_count=40)
    cached = cache.panel(_panel_identity(market.primary), lambda: market.primary)
    field = cached.object.data_path / "arrays" / "field-close.npy"
    field.chmod(0o644)
    with field.open("r+b") as handle:
        handle.seek(-1, 2)
        handle.write(b"x")
    with pytest.raises(CacheCorruption, match="hash differs"):
        cache.panel(_panel_identity(market.primary), lambda: market.primary)

    fresh = cache.panel(_panel_identity(market.primary, "quality-v2"), lambda: market.primary)
    assert fresh.object.digest != cached.object.digest

    truncated = cache.build("feature", _identity("feature", "truncated"), lambda path: (
        _write_fixture(path, "features.json", "{}\n")
    ))
    manifest = truncated.path / "manifest.json"
    manifest.chmod(0o644)
    write_text_atomic(manifest, "{")
    with pytest.raises(CacheCorruption, match="manifest is invalid"):
        cache.get("feature", _identity("feature", "truncated"))

    wrong_panel = cache.build("panel", _identity("panel", "wrong-schema"), lambda path: (
        _write_fixture(path, "panel.json", '{"format":"unknown"}\n')
    ))
    with pytest.raises(CacheCorruption, match="metadata schema"):
        cache.load_panel(wrong_panel)


def test_feature_and_label_tables_use_separate_namespaces_and_partitioned_parquet(tmp_path):
    cache = ResearchCache(tmp_path / "cache")
    features = pd.DataFrame({
        "session": ["2024-01-02", "2024-01-03"],
        "ticker": ["AAA", "AAA"],
        "score": [1.0, 2.0],
    })
    labels = pd.DataFrame({
        "session": ["2024-01-02", "2024-01-03"],
        "ticker": ["AAA", "AAA"],
        "return_h1": [0.1, -0.1],
    })
    feature = cache.table(
        "feature", _table_identity(features, "momentum"), lambda: features,
        family="momentum", expected_columns=tuple(features.columns),
    )
    label = cache.table(
        "label", _table_identity(labels, "forward"), lambda: labels,
        family="forward", expected_columns=tuple(labels.columns),
    )
    assert "/features/objects/" in feature.path.as_posix()
    assert "/outcomes/objects/" in label.path.as_posix()
    assert len(feature.parquet_files()) == 2 and len(label.parquet_files()) == 2
    assert feature.read_table()["score"].tolist() == [1.0, 2.0]
    assert label.read_table()["return_h1"].tolist() == [0.1, -0.1]


def test_concurrent_builders_converge_and_crash_never_publishes(tmp_path):
    cache = ResearchCache(tmp_path / "cache")
    identity = _identity("feature")

    def writer(path):
        write_text_atomic(path / "features.json", '{"value":1}\n')
        return {"format": "fixture"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        objects = list(pool.map(lambda _: cache.build("feature", identity, writer), range(4)))
    assert len({item.digest for item in objects}) == 1
    assert len({item.manifest["content_sha256"] for item in objects}) == 1

    def crash(path):
        write_text_atomic(path / "partial.json", "partial")
        raise RuntimeError("synthetic crash")

    broken_identity = _identity("feature", "broken")
    with pytest.raises(RuntimeError, match="synthetic crash"):
        cache.build("feature", broken_identity, crash)
    assert cache.get("feature", broken_identity) is None


def test_held_memory_map_survives_rebuildable_object_retention(tmp_path):
    cache = ResearchCache(tmp_path / "cache")
    market, _ = build_market(ticker_count=32, session_count=40)
    cached = cache.panel(_panel_identity(market.primary), lambda: market.primary)
    held = cached.source.panel.fields["close"]
    coordinate = np.argwhere(~np.isnan(held))[0]
    expected = float(held[*coordinate])
    shutil.rmtree(cached.object.path)
    assert float(held[*coordinate]) == expected


def test_cache_root_inside_repository_is_refused(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").mkdir()
    with pytest.raises(ValueError, match="outside"):
        ResearchCache(repository / "cache", repository_root=repository)


def test_specialized_cache_apis_refuse_caller_shaped_identity_mappings(tmp_path):
    cache = ResearchCache(tmp_path / "cache")
    market, universe = build_market(ticker_count=32, session_count=40)
    arbitrary = _identity("caller-controlled")

    with pytest.raises(TypeError, match="PanelCacheIdentity"):
        cache.panel(arbitrary, lambda: market.primary)
    with pytest.raises(TypeError, match="UniverseCacheIdentity"):
        cache.universe(arbitrary, market.primary, lambda: universe)
    with pytest.raises(TypeError, match="TableCacheIdentity"):
        cache.table(
            "feature", arbitrary,
            lambda: pd.DataFrame({"session": ["2024-01-02"], "value": [1.0]}),
            family="fixture",
        )


def test_typed_cache_identities_are_derived_and_stale_hits_refuse_actual_source_drift(
    tmp_path,
):
    cache = ResearchCache(tmp_path / "cache")
    first = generate_market(seed=11, session_count=60).data.primary
    second = generate_market(seed=12, session_count=60).data.primary
    identity = _panel_identity(first)
    cached = cache.panel(identity, lambda: first)

    with pytest.raises(CacheError, match="identity differs from the built source"):
        cache.panel(identity, lambda: second)
    with pytest.raises(CacheError, match="identity differs from the built source"):
        cache.panel(replace(identity, date_end="2099-12-31"), lambda: first)
    assert cached.source.declaration.snapshot_sha256 == first.declaration.snapshot_sha256

    frame = pd.DataFrame({
        "session": ["2024-01-02", "2024-01-03"],
        "score": [1.0, 2.0],
    })
    table_identity = _table_identity(frame, "fixture")
    cache.table("feature", table_identity, lambda: frame, family="fixture")
    changed = frame.assign(score=[10.0, 20.0])
    with pytest.raises(CacheError, match="identity differs from the built frame"):
        cache.table("feature", table_identity, lambda: changed, family="fixture")


def test_cache_root_guard_finds_other_and_nested_worktrees_independent_of_cwd(
    tmp_path, monkeypatch,
):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    other_repository = tmp_path / "private-repository"
    other_repository.mkdir()
    write_text_atomic(other_repository / ".git", "gitdir: elsewhere\n")
    monkeypatch.chdir(unrelated)
    with pytest.raises(ValueError, match="outside"):
        ResearchCache(other_repository / "artifacts" / "cache")

    nested = other_repository / "nested"
    nested.mkdir()
    (nested / ".git").mkdir()
    write_text_atomic(nested / ".git" / "HEAD", "ref: refs/heads/main\n")
    with pytest.raises(ValueError, match="outside"):
        ResearchCache(nested / "cache")


def _write_fixture(path, filename, content):
    write_text_atomic(path / filename, content)
    return {"format": "fixture"}
