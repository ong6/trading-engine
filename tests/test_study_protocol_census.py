import csv
import json
from datetime import date

import pytest

from farm.study.census import CENSUS_COLUMNS, TrialRow, append_rows
from farm.study.costs import CostSelection
from farm.study.data import Bar, MarketData, PriceSource
from farm.study.protocol import HoldoutAlreadyOpened, Windows, run_identity
from farm.study.spec import EventStrategy
from farm.walkforward.protocol import Fold


def _orders(view, session):
    return []


def _other_orders(view, session):
    return []


def _fold(index, year):
    return Fold(index, date(year - 2, 1, 1), date(year, 1, 1), date(year + 1, 1, 1))


def _windows():
    return Windows(tuple(_fold(index, year) for index, year in enumerate(range(2017, 2023), 1)),
                   _fold(7, 2023))


def _strategy(function=_orders, parameter=1):
    return EventStrategy("event", "pre_open", function, 2, 1_000, {"parameter": parameter})


def test_windows_require_six_ordered_yearly_development_folds():
    windows = _windows()
    assert windows.development_max_date == date(2023, 1, 1)
    with pytest.raises(ValueError, match="six"):
        Windows(tuple(_fold(i, 2017 + i) for i in range(1, 6)), _fold(6, 2023))
    bad = list(windows.dev_folds)
    bad[-1] = Fold(6, date(2020, 1, 1), date(2022, 6, 1), date(2023, 1, 1))
    with pytest.raises(ValueError, match="one year"):
        Windows(tuple(bad), windows.holdout)


def test_development_view_cannot_access_holdout_rows():
    source = PriceSource.declared(source="fixture", bars=[
        Bar("AAA", date(2023, 1, 1), 1, 1, 1, 1, 1),
        Bar("AAA", date(2023, 2, 1), 2, 2, 2, 2, 1),
    ])
    windows = _windows()
    windows.assert_development_rows([date(2023, 1, 1)])
    with pytest.raises(ValueError, match="holdout"):
        windows.assert_development_rows([date(2023, 2, 1)])
    view = windows.development_view(MarketData(source), 6, date(2023, 1, 1), "at_close")
    with pytest.raises(ValueError, match="boundary"):
        view.value("AAA", "close", date(2023, 2, 1))


def test_holdout_marker_is_atomic_one_shot(tmp_path):
    marker = tmp_path / "seal" / "opened.json"
    windows = _windows()
    assert windows.open_holdout(marker, "f" * 64) == windows.holdout
    assert json.loads(marker.read_text())["run_identity"] == "f" * 64
    with pytest.raises(HoldoutAlreadyOpened):
        windows.open_holdout(marker, "f" * 64)


def test_run_identity_binds_source_parameters_costs_and_both_snapshots():
    costs = CostSelection("binance_perp_base_v1", ("binance_spot_base_v1",))
    first = run_identity(_strategy(), costs, "a" * 64,
                         secondary_data_snapshot_sha256="b" * 64)
    assert first == run_identity(_strategy(), costs, "a" * 64,
                                 secondary_data_snapshot_sha256="b" * 64)
    assert first.sha256 != run_identity(_strategy(parameter=2), costs, "a" * 64).sha256
    assert first.sha256 != run_identity(_strategy(_other_orders), costs, "a" * 64,
                                        secondary_data_snapshot_sha256="b" * 64).sha256
    assert set(first.cost_profile_hashes) == {
        "binance_perp_base_v1", "binance_spot_base_v1"}


def test_census_schema_is_documented_study_owned_and_atomic(tmp_path):
    identity = run_identity(
        _strategy(), CostSelection("binance_perp_base_v1", ("binance_spot_base_v1",)),
        "a" * 64)
    path = tmp_path / "study" / "census.csv"
    first = TrialRow.from_identity(
        "trial-1", "base", "1", "development", "complete", 3, identity)
    second = TrialRow.from_identity(
        "trial-2", "base", "2", "holdout", "complete", 3, identity)
    append_rows(path, [first])
    append_rows(path, [second])
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == CENSUS_COLUMNS
    assert [row["trial_id"] for row in rows] == ["trial-1", "trial-2"]
    assert json.loads(rows[0]["cost_profile_hashes"]) == identity.cost_profile_hashes
    with pytest.raises(ValueError, match="unique"):
        append_rows(path, [first])
