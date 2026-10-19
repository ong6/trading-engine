"""Small complete contract factory shared by targeted research tests."""

from __future__ import annotations

import shutil
import sys
from copy import deepcopy
from pathlib import Path

from engine.lib.resources import write_text_atomic
from farm.research.canonical import file_sha256, python_runtime_sha256


def complete_contract(root: Path) -> dict:
    input_path = root / "input.json"
    outcome_path = root / "outcome.json"
    membership_path = root / "membership.json"
    quality_path = root / "quality.json"
    census_path = root / "census.jsonl"
    write_text_atomic(input_path, (
        '[{"_availability":{"close":"session close","session":"session open"},'
        '"close":100.0,"session":"2024-01-02"},'
        '{"_availability":{"close":"session close","session":"session open"},'
        '"close":101.0,"session":"2024-01-03"}]\n'
    ))
    write_text_atomic(outcome_path, (
        '[{"return_h1":0.01,"session":"2024-01-02"},'
        '{"return_h1":0.0,"session":"2024-01-03"}]\n'
    ))
    write_text_atomic(membership_path, (
        '{"coverage":1.0,"expected_rows":2,"point_in_time":true,'
        '"survivor_status":"point_in_time"}\n'
    ))
    write_text_atomic(quality_path, (
        '{"invalid_rows":0,"policy":"reject invalid OHLC geometry",'
        '"status":"accepted","version":"fixture-v1"}\n'
    ))
    write_text_atomic(census_path, '{"selection_n":140}\n')
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
                {"field": "session", "known_at": "session open"},
                {"field": "close", "known_at": "session close"},
            ],
            "primary_key": ["session"],
            "price_basis": "split-adjusted",
            "timezone": "America/New_York",
            "calendar": {"name": "XNYS", "version": "fixture-v1"},
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
                {"name": "return_h1", "dtype": "float64", "nullable": False},
                {"name": "available_at", "dtype": "datetime", "nullable": False},
            ],
        },
        "strategy": {
            "callback": callback | {"function": "strategy"},
            "parameters": {"threshold": 0.0},
            "decision_rule": "rank at close",
            "fill_rule": "next open",
            "exit_rule": "next close",
            "universe_rule": "point-in-time membership",
            "liquidity_rule": "positive trailing volume",
            "capital": 10_000,
        },
        "evaluation": {
            "callback": callback | {"function": "evaluation_recipe"},
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
                "pass": {"metric": "mean_net_return", "operator": ">=", "threshold": 2},
                "admit": {"metric": "mean_net_return", "operator": ">=", "threshold": 1},
                "kill": {"metric": "mean_net_return", "operator": "<", "threshold": 1},
            },
            "holdout": {"lease_id": "fixture-holdout-v1", "marker": "holdout/opened.json"},
            "missing_data_policy": "refuse",
        },
        "costs": {
            "profiles": [{"name": "fixture-zero", "sha256": "2" * 64, "rate_bps": 0.0}],
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
            "python_sha256": file_sha256(Path(sys.executable).resolve()),
            "python_runtime_sha256": python_runtime_sha256(),
        },
    }
    return deepcopy(contract)
