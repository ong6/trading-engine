"""Convex constraint projection for P16's long-only SPY-core portfolios."""
from __future__ import annotations

import numpy as np


class Constraints:
    """Name, sector, funding and beta constraints; the last coordinate is SPY."""

    def __init__(
        self, beta, sectors, *, name_cap=0.1, sector_cap=0.3,
        beta_bounds=(0.8, 1.1), fixed=None, upper_limits=None,
    ):
        stock_beta = np.asarray(beta, dtype=float)
        if (stock_beta.ndim != 1 or len(sectors) != len(stock_beta)
                or not np.all(np.isfinite(stock_beta))):
            raise ValueError("invalid beta/sector inputs")
        if (not 0 < name_cap <= 1 or not 0 < sector_cap <= 1
                or not beta_bounds[0] <= beta_bounds[1]):
            raise ValueError("invalid constraint limits")
        self.n = len(stock_beta) + 1
        self.beta = np.r_[stock_beta, 1.0]
        self.beta_low, self.beta_high = map(float, beta_bounds)
        self.sector_cap = float(sector_cap)
        normalized = [
            "unknown" if value is None or not str(value).strip()
            else str(value).strip().lower()
            for value in sectors
        ]
        self.sector_coverage = (
            sum(value != "unknown" for value in normalized) / len(normalized)
            if normalized else 1.0
        )
        self.sector_status = (
            "available" if self.sector_coverage >= 0.8 else "sector_unavailable"
        )
        if self.sector_status == "sector_unavailable":
            normalized = ["all_stocks"] * len(normalized)
        self.groups = [
            np.asarray([index for index, value in enumerate(normalized) if value == sector],
                       dtype=int)
            for sector in sorted(set(normalized))
        ]
        self.lower = np.zeros(self.n)
        self.upper = np.r_[np.full(len(stock_beta), name_cap), 1.0]
        if upper_limits is not None:
            upper = np.asarray(upper_limits, dtype=float)
            if (upper.shape != stock_beta.shape or not np.all(np.isfinite(upper))
                    or np.any(upper < 0) or np.any(upper > name_cap)):
                raise ValueError("invalid restricted name upper bounds")
            self.upper[:-1] = upper
        for index, value in (fixed or {}).items():
            if (not isinstance(index, int) or not 0 <= index < self.n
                    or not np.isfinite(value) or value < self.lower[index] - 1e-12
                    or value > self.upper[index] + 1e-12):
                raise ValueError("infeasible fixed weight")
            self.lower[index] = self.upper[index] = float(value)
        self.seed = self._feasible_seed()

    def _extreme(self, maximize: bool) -> np.ndarray:
        weights = self.lower.copy()
        if (weights.sum() > 1 + 1e-12 or self.upper.sum() < 1 - 1e-12
                or any(weights[group].sum() > self.sector_cap + 1e-12
                       for group in self.groups)):
            raise ValueError("infeasible budget/sector bounds")
        order = np.argsort(-self.beta if maximize else self.beta, kind="stable")
        group_by_index = {
            int(index): group for group in self.groups for index in group
        }
        for index in order:
            room = self.upper[index] - weights[index]
            group = group_by_index.get(int(index))
            if group is not None:
                room = min(room, self.sector_cap - weights[group].sum())
            weights[index] += max(0.0, min(room, 1 - weights.sum()))
        if abs(weights.sum() - 1) > 1e-10:
            raise ValueError("infeasible funded allocation")
        return weights

    def _feasible_seed(self) -> np.ndarray:
        low_weights, high_weights = self._extreme(False), self._extreme(True)
        low_beta = float(self.beta @ low_weights)
        high_beta = float(self.beta @ high_weights)
        if low_beta > self.beta_high + 1e-10 or high_beta < self.beta_low - 1e-10:
            raise ValueError("infeasible beta interval")
        target = float(np.clip(1.0, max(low_beta, self.beta_low),
                               min(high_beta, self.beta_high)))
        if high_beta - low_beta < 1e-14:
            return low_weights
        scale = (target - low_beta) / (high_beta - low_beta)
        return low_weights + scale * (high_weights - low_weights)

    def violation(self, weights) -> float:
        value = np.asarray(weights, dtype=float)
        if value.shape != (self.n,) or not np.all(np.isfinite(value)):
            return float("inf")
        return max(
            abs(float(value.sum()) - 1), float(np.max(self.lower - value)),
            float(np.max(value - self.upper)),
            max((float(value[group].sum() - self.sector_cap)
                 for group in self.groups), default=0.0),
            float(self.beta_low - self.beta @ value),
            float(self.beta @ value - self.beta_high), 0.0,
        )

    def prox(
        self, vector, penalty, previous, *, outer_tolerance=1e-9,
        initial_cycles=20_000, maximum_cycles=160_000,
    ) -> tuple[np.ndarray, dict]:
        """Generalized Dykstra prox with an adaptive cycle budget and dual-gap check."""
        vector = np.asarray(vector, dtype=float)
        penalty = np.broadcast_to(np.asarray(penalty, dtype=float), (self.n,))
        previous = np.asarray(previous, dtype=float)
        if (vector.shape != (self.n,) or previous.shape != (self.n,)
                or not np.all(np.isfinite(vector)) or not np.all(np.isfinite(previous))
                or np.any(penalty < 0) or not 0 < outer_tolerance <= 1e-3
                or initial_cycles < 5 or maximum_cycles < initial_cycles):
            raise ValueError("invalid proximal inputs")
        tolerance = max(1e-12, min(1e-10, outer_tolerance * 1e-2))
        set_count = 4 + len(self.groups)
        corrections = np.zeros((set_count, self.n))
        current = vector.copy()
        next_budget = initial_cycles
        for cycle in range(1, maximum_cycles + 1):
            for projection in range(set_count):
                shifted = current + corrections[projection]
                if projection == 0:
                    target = previous + np.sign(shifted - previous) * np.maximum(
                        np.abs(shifted - previous) - penalty, 0,
                    )
                elif projection == 1:
                    target = np.clip(shifted, self.lower, self.upper)
                elif projection == 2:
                    target = shifted - (shifted.sum() - 1) / self.n
                elif projection < 3 + len(self.groups):
                    group = self.groups[projection - 3]
                    target = shifted.copy()
                    excess = max(0.0, (shifted[group].sum() - self.sector_cap) / len(group))
                    target[group] -= excess
                else:
                    beta_value = float(self.beta @ shifted)
                    target = shifted + (
                        (float(np.clip(beta_value, self.beta_low, self.beta_high)) - beta_value)
                        / float(self.beta @ self.beta)
                    ) * self.beta
                corrections[projection] = shifted - target
                current = target
            if cycle != 1 and cycle % 5:
                continue
            support = float(corrections[0] @ previous)
            support += float(np.maximum(corrections[1] * self.lower,
                                        corrections[1] * self.upper).sum())
            support += float(corrections[2].mean())
            for index, group in enumerate(self.groups):
                support += float(corrections[index + 3, group].mean()) * self.sector_cap
            beta_multiplier = float(
                corrections[-1] @ self.beta / (self.beta @ self.beta)
            )
            support += beta_multiplier * (
                self.beta_high if beta_multiplier >= 0 else self.beta_low
            )
            dual = (0.5 * float(vector @ vector)
                    - 0.5 * float(np.sum((vector - corrections.sum(axis=0)) ** 2))
                    - support)
            primal = (0.5 * float(np.sum((current - vector) ** 2))
                      + float(penalty @ np.abs(current - previous)))
            gap = float(primal - dual)
            scale = max(1.0, abs(primal), abs(dual), float(vector @ vector),
                        float(penalty @ np.abs(current - previous)))
            violation = self.violation(current)
            if violation <= tolerance and abs(gap) <= tolerance * (1 + scale):
                return current, {
                    "cycles": cycle, "cycle_budget": next_budget,
                    "gap": gap, "violation": violation,
                    "inner_tolerance": tolerance,
                }
            if cycle == next_budget:
                next_budget = min(maximum_cycles, next_budget * 2)
        raise RuntimeError("proximal projection did not converge")
