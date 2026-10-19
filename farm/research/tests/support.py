"""Small complete contract factory shared by targeted research tests."""

from __future__ import annotations

import platform
import shutil
from copy import deepcopy
from pathlib import Path

from engine.lib.resources import write_text_atomic
from farm.research.canonical import file_sha256


def complete_contract(root: Path) -> dict:
    input_path = root / "input.json"
    outcome_path = root / "outcome.json"
    membership_path = root / "membership.json"
    quality_path = root / "quality.json"
    census_path = root / "census.jsonl"
    lock_path = root / "uv.lock"
    write_text_atomic(input_path, (
        '[{"_availability":{"close":"2024-01-02T16:00:00-05:00",'
        '"session":"2024-01-02T09:30:00-05:00"},'
        '"close":100.0,"session":"2024-01-02"},'
        '{"_availability":{"close":"2024-01-03T16:00:00-05:00",'
        '"session":"2024-01-03T09:30:00-05:00"},'
        '"close":101.0,"session":"2024-01-03"}]\n'
    ))
    write_text_atomic(outcome_path, (
        '[{"entry_at":"2024-01-03T09:30:00-05:00",'
        '"entry_price":100.0,"exit_at":"2024-01-03T16:00:00-05:00",'
        '"exit_price":101.0,"session":"2024-01-02"},'
        '{"entry_at":"2024-01-04T09:30:00-05:00",'
        '"entry_price":101.0,"exit_at":"2024-01-04T16:00:00-05:00",'
        '"exit_price":101.0,"session":"2024-01-03"}]\n'
    ))
    write_text_atomic(membership_path, (
        '{"point_in_time":true,"survivor_status":"point_in_time","rows":['
        '{"eligible":true,"session":"2024-01-02"},'
        '{"eligible":true,"session":"2024-01-03"}]}\n'
    ))
    write_text_atomic(quality_path, (
        '{"invalid_rows":0,"policy":"reject invalid OHLC geometry",'
        '"status":"accepted","version":"fixture-v1"}\n'
    ))
    write_text_atomic(census_path, '{"selection_n":140}\n')
    write_text_atomic(lock_path, "fixture-lock\n")
    callback_path = root / "callbacks" / "study_fixture_callbacks.py"
    callback_path.parent.mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("fixture_callbacks.py"), callback_path)
    callback = {
        "module": "study_fixture_callbacks",
        "function": "feature_recipe",
        "source": "callbacks/study_fixture_callbacks.py",
        "kind": "module",
        "sha256": file_sha256(callback_path),
        "dependencies": [],
    }
    contract = {
        "schema_version": 1,
        "study": {
            "id": "synthetic-contract",
            "version": "1.0.0",
            "hypothesis": "A deterministic fixture has no economic claim.",
            "phase": "development",
            "owner": "research",
            "prior": [],
            "parents": [],
        },
        "inputs": {
            "generation_sha256": "1" * 64,
            "feature_parts": [{
                "path": "input.json", "sha256": file_sha256(input_path), "format": "rows_json",
            }],
            "outcome_parts": [{
                "path": "outcome.json", "sha256": file_sha256(outcome_path), "format": "opaque",
            }],
            "schema": [
                {"name": "session", "dtype": "date", "nullable": False},
                {"name": "close", "dtype": "float64", "nullable": False},
            ],
            "availability": [
                "session", "close",
            ],
            "primary_key": ["session"],
            "price_basis": "split-adjusted",
            "timezone": "America/New_York",
            "calendar": {"name": "XNYS", "version": "fixture-v1", "session_close": "16:00"},
            "membership": {
                "point_in_time": True,
                "evidence": {"path": "membership.json", "sha256": file_sha256(membership_path)},
            },
            "coverage": {"minimum": 0.99, "unit": "eligible ticker sessions"},
            "survivor_status": "point_in_time",
            "quality": {
                "version": "fixture-v1",
                "policy": "reject invalid OHLC geometry",
                "evidence": {"path": "quality.json", "sha256": file_sha256(quality_path)},
            },
        },
        "features": [{
            "name": "fixture",
            "callback": callback,
            "dependencies": [],
            "availability": "available_at",
            "output_schema": [
                {"name": "session", "dtype": "date", "nullable": False},
                {"name": "score", "dtype": "float64", "nullable": False},
                {"name": "available_at", "dtype": "datetime", "nullable": False},
            ],
            "parameters": {"window": 2},
        }],
        "outcomes": {
            "callback": callback | {"function": "label_recipe"},
            "parameters": {"horizon": 1},
            "horizons": [1],
            "availability": "available_at",
            "output_schema": [
                {"name": "session", "dtype": "date", "nullable": False},
                {"name": "entry_at", "dtype": "datetime", "nullable": False},
                {"name": "entry_price", "dtype": "float64", "nullable": False},
                {"name": "exit_at", "dtype": "datetime", "nullable": False},
                {"name": "exit_price", "dtype": "float64", "nullable": False},
                {"name": "available_at", "dtype": "datetime", "nullable": False},
            ],
        },
        "strategy": {
            "callback": callback | {"function": "strategy"},
            "parameters": {"threshold": 0.0},
            "decision": {"time": "16:00", "timezone": "America/New_York"},
            "fill_rule": {
                "entry_price_field": "entry_price",
                "exit_price_field": "exit_price",
                "horizon_sessions": 1,
            },
            "universe_rule": "point-in-time membership",
            "liquidity_rule": "positive trailing volume",
            "capital": 10_000,
        },
        "evaluation": {
            "variants": [{"name": "base", "parameters": {}}],
            "controls": ["cash"],
            "folds": [{"name": "development-1", "start": "2024-01-01", "end": "2024-07-01"}],
            "benchmark_mode": "gross cash",
            "statistics": ["mean_net_return"],
            "dsr_census": {
                "path": "census.jsonl",
                "sha256": file_sha256(census_path),
                "selection_n": 140,
            },
            "rules": {
                "pass": {"metric": "mean_net_return", "operator": ">=", "threshold": 0.01},
                "admit": {"metric": "mean_net_return", "operator": ">=", "threshold": 0.004},
                "kill": {"metric": "mean_net_return", "operator": "<", "threshold": 0.004},
            },
            "holdout": {"lease_id": "fixture-holdout-v1", "marker": "holdout/opened.json"},
            "missing_data_policy": "refuse",
        },
        "costs": {
            "profiles": [{
                "name": "ibkr_tiered_auction_v1",
                "sha256": "be60ad69ae19cc9f1e2bcd5a1c91ee312c4a690260f1678e8def45991e72337e",
            }],
            "scope": {
                name: {"status": "zero", "reason": "synthetic fixture", "sha256": "3" * 64}
                for name in ("execution", "commission", "borrow_funding", "fx", "tax", "data")
            },
        },
        "execution": {
            "seed": 71,
            "workers": 1,
            "memory_mb": 256,
            "expected_seconds": 5,
            "output_subdir": "synthetic-contract/v1",
            "python_version": platform.python_version(),
            "uv_lock": {"path": "uv.lock", "sha256": file_sha256(lock_path)},
            "packages": [],
        },
    }
    return deepcopy(contract)
