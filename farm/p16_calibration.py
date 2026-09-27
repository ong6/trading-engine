"""Registered preactivation calibration for the two P16 construction books."""
from __future__ import annotations

import time

import numpy as np

from farm import p16_optimizer

DEFAULT_LAMBDA_GRID = np.logspace(-1, 3, 17)


def calibrate_lambda(cases: list[dict], grid=None) -> dict:
    """Choose one shared lambda; retain every solve and numerical failure."""
    values = DEFAULT_LAMBDA_GRID.copy() if grid is None else np.asarray(grid, dtype=float)
    if (values.ndim != 1 or not len(values) or not np.all(np.isfinite(values))
            or np.any(values < 0) or len(np.unique(values)) != len(values)):
        raise ValueError("invalid lambda grid")
    books = sorted({case.get("book_id") for case in cases})
    if not cases or not books or None in books:
        return {"status": "calibration_unavailable", "selected_lambda": None,
                "curve": [], "grid_bounds": [float(values.min()), float(values.max())]}
    curve = []
    for risk_aversion in values:
        tracking_errors = {book: [] for book in books}
        failures, timings = [], []
        for case_index, case in enumerate(cases):
            arguments = {key: value for key, value in case.items() if key != "book_id"}
            started = time.perf_counter()
            try:
                result = p16_optimizer.solve(
                    **arguments, risk_aversion=float(risk_aversion),
                )
            except RuntimeError as exc:
                result = {"status": "not_converged"}
                failures.append({
                    "case_index": case_index, "book_id": case["book_id"],
                    "reason": str(exc),
                })
            elapsed = time.perf_counter() - started
            timings.append({
                "case_index": case_index, "book_id": case["book_id"],
                "solve_seconds": elapsed,
            })
            if result["status"] not in {"converged", "zero_alpha_core"}:
                if not any(row["case_index"] == case_index for row in failures):
                    failures.append({
                        "case_index": case_index, "book_id": case["book_id"],
                        "reason": result["status"],
                    })
            else:
                tracking_errors[case["book_id"]].append(result["tracking_error"])
        row = {
            "risk_aversion": float(risk_aversion), "solve_timings": timings,
            "solve_seconds_total": sum(item["solve_seconds"] for item in timings),
        }
        if failures or any(not tracking_errors[book] for book in books):
            row.update(status="not_converged", eligible=False,
                       median_tracking_error=None, failures=failures)
        else:
            medians = {
                book: float(np.median(tracking_errors[book])) for book in books
            }
            row.update(
                status="converged", median_tracking_error=medians,
                eligible=all(0.04 <= value <= 0.06 for value in medians.values()),
                distance=max(abs(value - 0.05) for value in medians.values()),
                failures=[],
            )
        curve.append(row)
    eligible = [row for row in curve if row["eligible"]]
    selected = min(
        eligible, key=lambda row: (row["distance"], -row["risk_aversion"]),
    ) if eligible else None
    status = (
        "calibrated" if selected else "calibration_incomplete"
        if any(row["status"] == "not_converged" for row in curve)
        else "target_unattainable_on_grid"
    )
    return {
        "status": status,
        "selected_lambda": None if selected is None else selected["risk_aversion"],
        "selected_at_grid_endpoint": None if selected is None else bool(
            selected["risk_aversion"] in (values.min(), values.max())
        ),
        "grid_bounds": [float(values.min()), float(values.max())], "curve": curve,
    }
