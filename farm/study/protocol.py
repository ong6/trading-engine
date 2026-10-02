"""Development/holdout boundaries and immutable study run identities."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from engine.lib.provenance import canonical_sha256
from farm.walkforward.protocol import Fold, minus_months

from .costs import CostSelection
from .data import MarketData, PointInTimeView
from .spec import EventStrategy, PortfolioStrategy
from .version import CORE_VERSION


class HoldoutAlreadyOpened(RuntimeError):
    pass


@dataclass(frozen=True)
class Windows:
    dev_folds: tuple[Fold, ...]
    holdout: Fold

    def __post_init__(self) -> None:
        if len(self.dev_folds) < 6:
            raise ValueError("at least six development folds are required")
        all_folds = (*self.dev_folds, self.holdout)
        if any(minus_months(fold.validate_end, 12) != fold.split_date for fold in all_folds):
            raise ValueError("validation and holdout windows must each be one year")
        if any(left.validate_end > right.split_date
               for left, right in zip(all_folds[:-1], all_folds[1:], strict=True)):
            raise ValueError("development and holdout windows must be ordered and non-overlapping")

    @property
    def development_max_date(self) -> date:
        return self.dev_folds[-1].validate_end

    def development_view(self, data: MarketData, fold_index: int, session: date,
                         decision_time: str, *, open_as_indication: bool = False,
                         close_as_indication: bool = False,
                         source: str = "primary") -> PointInTimeView:
        fold = next((item for item in self.dev_folds if item.index == fold_index), None)
        if fold is None:
            raise ValueError(f"unknown development fold {fold_index}")
        return data.view(session, decision_time, fold.validate_end,
                         open_as_indication=open_as_indication,
                         close_as_indication=close_as_indication, source=source)

    def assert_development_rows(self, sessions: Iterable[date]) -> None:
        if any(day > self.development_max_date for day in sessions):
            raise ValueError("development run attempted to load holdout rows")

    def open_holdout(self, marker_path: str | Path, run_identity: str) -> Fold:
        marker = Path(marker_path)
        marker.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"run_identity": run_identity,
                              "opened_at": datetime.now(timezone.utc).isoformat()},
                             sort_keys=True) + "\n"
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise HoldoutAlreadyOpened(f"holdout marker already exists: {marker}") from exc
        with os.fdopen(descriptor, "w") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return self.holdout


@dataclass(frozen=True)
class RunIdentity:
    sha256: str
    spec_source_sha256: str
    parameters_sha256: str
    core_version: str
    cost_profile_hashes: dict[str, str]
    data_snapshot_sha256: str
    secondary_data_snapshot_sha256: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def _spec_config(strategy: EventStrategy | PortfolioStrategy) -> dict:
    common = {"name": strategy.name, "decision_time": strategy.decision_time,
              "parameters": dict(strategy.parameters)}
    if isinstance(strategy, EventStrategy):
        config = common | {
            "kind": "event", "max_concurrent_slots": strategy.max_concurrent_slots,
            "slot_notional": strategy.slot_notional,
            "max_new_per_session": strategy.max_new_per_session,
            "order_sort_key": strategy.order_sort_key,
            "open_as_indication": strategy.open_as_indication,
            "close_as_indication": strategy.close_as_indication,
            "exit_cost_basis": strategy.exit_cost_basis,
            "already_held": strategy.already_held,
            "dividend_withholding": strategy.dividend_withholding}
        if strategy.window_end != "force_close":
            config["window_end"] = strategy.window_end
        if strategy.require_complete_path:
            config["require_complete_path"] = True
        return config
    schedule = (strategy.rebalance_schedule if isinstance(strategy.rebalance_schedule, str)
                else [day.isoformat() for day in strategy.rebalance_schedule])
    return common | {"kind": "portfolio", "rebalance_schedule": schedule,
                     "fill": asdict(strategy.fill), "initial_capital": strategy.initial_capital,
                     "open_as_indication": strategy.open_as_indication,
                     "close_as_indication": strategy.close_as_indication,
                     "dividend_withholding": strategy.dividend_withholding}


def run_identity(strategy: EventStrategy | PortfolioStrategy, costs: CostSelection,
                 data_snapshot_sha256: str, *,
                 secondary_data_snapshot_sha256: str | None = None) -> RunIdentity:
    function = strategy.order_function if isinstance(strategy, EventStrategy) else strategy.weight_function
    try:
        source = inspect.getsource(function)
    except (OSError, TypeError) as exc:
        raise ValueError("strategy function source is unavailable") from exc
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    config = _spec_config(strategy)
    parameters_hash = canonical_sha256(config)
    components = {"spec_source_sha256": source_hash, "parameters_sha256": parameters_hash,
                  "core_version": CORE_VERSION, "cost_profile_hashes": costs.hashes,
                  "data_snapshot_sha256": data_snapshot_sha256,
                  "secondary_data_snapshot_sha256": secondary_data_snapshot_sha256}
    return RunIdentity(canonical_sha256(components), source_hash, parameters_hash, CORE_VERSION,
                       costs.hashes, data_snapshot_sha256, secondary_data_snapshot_sha256)
