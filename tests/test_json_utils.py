"""Tests for strict operational JSON loading."""

import os
import sys

import pytest

from server.json_utils import (
    MAX_JSON_FILE_BYTES,
    MAX_JSON_NESTING,
    load_object,
    loads_strict,
    loads_unique_object,
    require_finite_numbers,
)


def _deeply_nested_json() -> str:
    depth = max(10_000, sys.getrecursionlimit() * 10)
    return '{"nested":' + ("[" * depth) + "0" + ("]" * depth) + "}"


def _nested_object(list_depth: int) -> str:
    return '{"nested":' + ("[" * list_depth) + "0" + ("]" * list_depth) + "}"


def test_load_object_rejects_duplicate_nested_key(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text('{"outer": {"value": 1, "value": 2}}')

    with pytest.raises(ValueError, match="duplicate JSON key: value"):
        load_object(path)


def test_load_object_rejects_non_object_and_accepts_object(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="top-level JSON value must be an object"):
        load_object(path)

    path.write_text('{"value": 1}')
    assert load_object(path) == {"value": 1}


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_load_object_rejects_nonstandard_numeric_constants(tmp_path, constant):
    path = tmp_path / "evidence.json"
    path.write_text(f'{{"value": {constant}}}')

    with pytest.raises(ValueError, match=f"invalid JSON constant: {constant}"):
        load_object(path)


def test_load_object_rejects_float_overflow(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text('{"value": 1e999}')

    with pytest.raises(ValueError, match="non-finite JSON number: 1e999"):
        load_object(path)


@pytest.mark.parametrize("loader", [loads_strict, loads_unique_object])
def test_json_loaders_normalize_excessive_nesting(loader):
    with pytest.raises(ValueError, match="JSON nesting exceeds 100 levels") as exc_info:
        loader(_deeply_nested_json())

    assert isinstance(exc_info.value.__cause__, RecursionError)


@pytest.mark.parametrize("loader", [loads_strict, loads_unique_object])
def test_json_loaders_enforce_deterministic_nesting_limit(loader):
    assert loader(_nested_object(MAX_JSON_NESTING - 1))["nested"] is not None

    with pytest.raises(ValueError, match="JSON nesting exceeds 100 levels") as exc_info:
        loader(_nested_object(MAX_JSON_NESTING))

    assert exc_info.value.__cause__ is None


def test_file_loader_normalizes_excessive_nesting(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(_deeply_nested_json())

    with pytest.raises(ValueError, match="JSON nesting exceeds 100 levels"):
        load_object(path)


def test_file_loader_accepts_exact_size_limit(tmp_path):
    path = tmp_path / "evidence.json"
    padding = MAX_JSON_FILE_BYTES - len('{"padding":""}')
    path.write_text('{"padding":"' + ("x" * padding) + '"}')

    assert len(path.read_bytes()) == MAX_JSON_FILE_BYTES
    assert len(load_object(path)["padding"]) == padding


def test_file_loader_rejects_one_byte_over_size_limit(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_bytes(b"x" * (MAX_JSON_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="JSON file exceeds 1048576 bytes"):
        load_object(path)


@pytest.mark.parametrize("dangling", [False, True])
def test_file_loader_rejects_symlink(tmp_path, dangling):
    target = tmp_path / "target.json"
    if not dangling:
        target.write_text('{"value": 1}')
    path = tmp_path / "evidence.json"
    path.symlink_to(target)

    with pytest.raises(ValueError, match="regular file, not a symlink"):
        load_object(path)


def test_file_loader_rejects_directory(tmp_path):
    path = tmp_path / "evidence.json"
    path.mkdir()

    with pytest.raises(ValueError, match="must be a regular file"):
        load_object(path)


def test_file_loader_rejects_fifo_without_blocking(tmp_path):
    path = tmp_path / "evidence.json"
    os.mkfifo(path)

    with pytest.raises(ValueError, match="must be a regular file"):
        load_object(path)


def test_file_loader_allows_regular_file_below_symlinked_parent(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "evidence.json").write_text('{"value": 1}')
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)

    assert load_object(alias / "evidence.json") == {"value": 1}


def test_file_loader_can_reject_regular_file_below_symlinked_parent(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "evidence.json").write_text('{"value": 1}')
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="JSON parent path must not contain symlinks"):
        load_object(alias / "evidence.json", allow_symlinked_parents=False)


def test_finite_number_check_handles_deep_predecoded_tree():
    payload: list = []
    root = payload
    for _ in range(sys.getrecursionlimit() * 2):
        child: list = []
        payload.append(child)
        payload = child
    payload.append(float("inf"))

    with pytest.raises(ValueError, match="non-finite JSON number"):
        require_finite_numbers(root)


def test_unique_object_loader_is_only_for_legacy_identity_classification():
    payload = loads_unique_object('{"config_id": "retired", "metric": NaN}')

    assert payload["config_id"] == "retired"


@pytest.mark.parametrize(
    "payload",
    [
        {"metric": float("nan")},
        {"nested": [{"metric": float("inf")}]},
        [float("-inf")],
    ],
)
def test_finite_number_check_rejects_nonfinite_values_anywhere(payload):
    with pytest.raises(ValueError, match="non-finite JSON number"):
        require_finite_numbers(payload)


def test_finite_number_check_accepts_standard_json_tree():
    require_finite_numbers({"metric": 1.25, "nested": [None, True, "NaN", 3]})
