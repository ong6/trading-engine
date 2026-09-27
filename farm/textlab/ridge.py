"""Numpy-only reduced text-lab sampling and expanding ridge contracts."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Mapping, Sequence

import numpy as np

LAMBDA_GRID = (0.01, 0.1, 1.0, 10.0, 100.0)
REDUCED_CHECKPOINTS = {
    range(2015, 2018): "chrono-bert-2014",
    range(2018, 2021): "chrono-bert-2017",
    range(2021, 2024): "chrono-bert-2020",
    range(2024, 2026): "chrono-bert-2023",
}


def issuer_in_reduced_sample(cik: str) -> bool:
    normalized = str(cik).zfill(10)
    return int(hashlib.sha256(normalized.encode()).hexdigest(), 16) % 4 == 0


def checkpoint_for_year(test_year: int) -> str:
    for years, checkpoint in REDUCED_CHECKPOINTS.items():
        if test_year in years:
            return checkpoint
    raise ValueError("textlab_year_outside_registration")


def ridge_predict(x_train, y_train, x_test, penalty: float) -> np.ndarray:
    x, y, test = np.asarray(x_train, dtype=float), np.asarray(y_train, dtype=float), np.asarray(
        x_test, dtype=float
    )
    if (
        x.ndim != 2
        or y.shape != (len(x),)
        or len(x) < 2
        or test.ndim != 2
        or test.shape[1] != x.shape[1]
        or penalty <= 0
        or not all(np.isfinite(value).all() for value in (x, y, test))
    ):
        raise ValueError("invalid_textlab_ridge_input")
    mean, scale = x.mean(0), x.std(0)
    scale[scale == 0] = 1.0
    z, centered = (x - mean) / scale, y - y.mean()
    beta = np.linalg.solve(
        z.T @ z / len(z) + penalty * np.eye(z.shape[1]), z.T @ centered / len(z)
    )
    return (test - mean) / scale @ beta + y.mean()


def select_lambda(folds: Sequence[Mapping]) -> dict:
    """Choose by pooled pre-2018 validation MSE; ties use the larger penalty."""
    if not folds:
        return {"status": "lambda_unconfigured", "reason": "pre_2018_fold_missing"}
    errors = {}
    for penalty in LAMBDA_GRID:
        squared = []
        for fold in folds:
            prediction = ridge_predict(
                fold["x_train"], fold["y_train"], fold["x_validation"], penalty
            )
            actual = np.asarray(fold["y_validation"], dtype=float)
            if actual.shape != prediction.shape:
                raise ValueError("textlab_validation_shape")
            squared.extend(((prediction - actual) ** 2).tolist())
        errors[penalty] = float(np.mean(squared))
    selected = min(LAMBDA_GRID, key=lambda value: (errors[value], -value))
    return {"status": "selected", "lambda": selected, "pooled_mse": errors[selected]}


def training_indices(
    rows: Sequence[Mapping], *, fit_at: datetime, checkpoint: str
) -> list[int]:
    cutoff = fit_at.astimezone(timezone.utc)
    selected = []
    for index, row in enumerate(rows):
        accepted = datetime.fromisoformat(str(row["accepted_at"]).replace("Z", "+00:00"))
        visible = datetime.fromisoformat(str(row["label_visible_at"]).replace("Z", "+00:00"))
        if (
            accepted.tzinfo is None
            or visible.tzinfo is None
            or row.get("checkpoint") != checkpoint
            or row.get("label_status") != "terminal"
        ):
            continue
        if accepted.astimezone(timezone.utc) < cutoff and visible.astimezone(timezone.utc) < cutoff:
            selected.append(index)
    return selected


def inference_readiness() -> dict:
    return {
        "status": "inference_unconfigured",
        "reason": "research_text_dependency_not_approved",
        "variant": "text-chrono-reduced-ridge-v1",
        "issuer_sample": "sha256_cik_modulo_4_equals_0",
    }
