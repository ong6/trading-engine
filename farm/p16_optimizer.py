"""P16 convex active-risk optimizer with deterministic no-trade faces."""
from __future__ import annotations

import math

import numpy as np

from farm.p16_projection import Constraints


def objective(weights, alpha, covariance, risk_aversion, cost, previous) -> float:
    stock_weights = np.asarray(weights)[:-1]
    return float(
        alpha @ stock_weights
        - risk_aversion * (stock_weights @ covariance @ stock_weights)
        - np.asarray(cost) @ np.abs(weights - previous)
    )


def solve(
    alpha, covariance, beta, sectors, previous, *, risk_aversion, cost,
    band=0.005, max_iterations=5_000, tolerance=1e-9,
    zero_alpha_core=True, beta_bounds=(0.8, 1.1), horizon_sessions=5,
    fixed_weights=None, upper_limits=None,
) -> dict:
    """Solve one registered P16 target; failures never return executable weights."""
    alpha = np.asarray(alpha, dtype=float)
    covariance = np.asarray(covariance, dtype=float)
    previous = np.asarray(previous, dtype=float)
    names = len(alpha)
    costs = np.broadcast_to(np.asarray(cost, dtype=float), (names + 1,)).copy()
    if (covariance.shape != (names, names) or previous.shape != (names + 1,)
            or not all(np.all(np.isfinite(value))
                       for value in (alpha, covariance, previous, costs))):
        raise ValueError("unaligned or nonfinite optimizer inputs")
    if (not np.isfinite(risk_aversion) or risk_aversion < 0 or np.any(costs < 0)
            or not np.allclose(covariance, covariance.T, atol=1e-12)
            or not np.isfinite(band) or band < 0 or horizon_sessions <= 0
            or max_iterations < 1 or not 0 < tolerance <= 1e-3):
        raise ValueError("invalid optimizer settings")
    if abs(previous.sum() - 1) > 1e-8 or np.any(previous < -1e-12):
        raise ValueError("previous funded long-only weights required")
    constraints = Constraints(
        beta, sectors, beta_bounds=beta_bounds,
        fixed=fixed_weights, upper_limits=upper_limits,
    )
    if names == 0:
        return _core_result(constraints, "zero_alpha_core")
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    if eigenvalues.min() < -1e-12:
        raise ValueError("covariance not positive semidefinite")
    covariance_repaired = bool(eigenvalues.min() < 0)
    if covariance_repaired:
        covariance = ((eigenvectors * np.maximum(eigenvalues, 0)) @ eigenvectors.T)
        eigenvalues = np.maximum(eigenvalues, 0)
    if zero_alpha_core and np.max(np.abs(alpha)) <= 1e-15:
        core = np.r_[np.zeros(names), 1.0]
        if constraints.violation(core) > 1e-10:
            raise ValueError("zero-alpha core infeasible under mandatory bounds")
        return _core_result(constraints, "zero_alpha_core")
    risk_repair = constraints.violation(previous) > 1e-8
    maximum_eigenvalue = max(float(eigenvalues.max()), 0.0)
    step_size = (
        1 / (2 * risk_aversion * maximum_eigenvalue)
        if risk_aversion > 0 and maximum_eigenvalue > 1e-16
        else 1 / max(float(np.max(np.abs(alpha))), float(costs.max()), 1e-4)
    )
    objective_scale = max(
        float(np.max(np.abs(alpha))), float(costs.max()),
        2 * risk_aversion * maximum_eigenvalue, 1e-12,
    )
    frozen = dict(fixed_weights or {})
    weights = previous.copy()
    iterations = 0
    mapping = relative_mapping = math.inf
    prox_state = None
    unbanded_objective = None
    warm_start_distances = []
    for _face in range(names + 2):
        face = Constraints(
            beta, sectors, beta_bounds=beta_bounds,
            fixed=frozen, upper_limits=upper_limits,
        )
        prior_face = weights.copy()
        if face.violation(weights) > 1e-12:
            weights, _ = face.prox(
                weights, 0.0, previous, outer_tolerance=tolerance,
            )
        warm_start_distances.append(float(np.max(np.abs(weights - prior_face))))
        for _iteration in range(max_iterations):
            gradient = np.r_[
                2 * risk_aversion * (covariance @ weights[:-1]) - alpha, 0.0,
            ]
            candidate, prox_state = face.prox(
                weights - step_size * gradient, step_size * costs, previous,
                outer_tolerance=tolerance,
            )
            mapping = float(np.max(np.abs(candidate - weights)) / step_size)
            relative_mapping = mapping / objective_scale
            weight_step = float(np.max(np.abs(candidate - weights)))
            iterations += 1
            old_value = objective(
                weights, alpha, covariance, risk_aversion, costs, previous,
            )
            new_value = objective(
                candidate, alpha, covariance, risk_aversion, costs, previous,
            )
            value_scale = max(objective_scale, abs(old_value), abs(new_value), 1e-12)
            if new_value < old_value - 1e-10 * value_scale:
                raise RuntimeError("objective decreased beyond tolerance")
            weights = candidate
            if (relative_mapping <= tolerance and weight_step <= 1e-9
                    and abs(new_value - old_value) <= 1e-10 * value_scale):
                break
        else:
            return {
                "status": "not_converged", "weights": None,
                "iterations": iterations, "gradient_mapping": mapping,
                "relative_gradient_mapping": relative_mapping,
                "sector_status": face.sector_status,
                "sector_coverage": face.sector_coverage,
            }
        if unbanded_objective is None:
            unbanded_objective = objective(
                weights, alpha, covariance, risk_aversion, costs, previous,
            )
        if risk_repair or band == 0:
            break
        newly_frozen = {
            index: float(previous[index])
            for index in range(names + 1)
            if index not in frozen
            and abs(weights[index] - previous[index]) < band - 1e-10
        }
        if not newly_frozen:
            break
        frozen.update(newly_frozen)
    else:
        raise RuntimeError("no-trade active-set iteration exceeded dimension")
    weights[np.abs(weights) < 1e-12] = 0.0
    if face.violation(weights) > 1e-10 or np.any(weights < 0):
        raise RuntimeError("post-cleanup constraint check failed")
    final_objective = objective(
        weights, alpha, covariance, risk_aversion, costs, previous,
    )
    return {
        "weights": weights, "status": "converged", "iterations": iterations,
        "gradient_mapping": mapping, "relative_gradient_mapping": relative_mapping,
        "objective_scale": objective_scale, "warm_start_distances": warm_start_distances,
        "sector_status": face.sector_status, "sector_coverage": face.sector_coverage,
        "prox_gap": prox_state["gap"], "prox_cycles": prox_state["cycles"],
        "prox_cycle_budget": prox_state["cycle_budget"],
        "inner_tolerance": prox_state["inner_tolerance"],
        "violation": face.violation(weights), "frozen_indices": sorted(frozen),
        "band_overridden": bool(risk_repair),
        "tracking_error": math.sqrt(max(
            0.0, 252 / horizon_sessions * (weights[:-1] @ covariance @ weights[:-1]),
        )),
        "objective": final_objective, "step_size": step_size,
        "covariance_roundoff_repair": covariance_repaired,
        "unbanded_objective": unbanded_objective,
        "band_objective_loss": unbanded_objective - final_objective,
    }


def _core_result(constraints: Constraints, status: str) -> dict:
    return {
        "weights": np.r_[np.zeros(constraints.n - 1), 1.0], "status": status,
        "gradient_mapping": None, "relative_gradient_mapping": None,
        "iterations": 0, "tracking_error": 0.0, "violation": 0.0,
        "band_overridden": True, "sector_status": constraints.sector_status,
        "sector_coverage": constraints.sector_coverage,
    }
