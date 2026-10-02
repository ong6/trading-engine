"""Deterministic variant-by-fold execution with optional process parallelism."""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

BLAS_ENV_VARS = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS",
)
_FORK_EVALUATOR: Callable[["StudyJob"], Mapping] | None = None


def force_single_thread_blas() -> None:
    for name in BLAS_ENV_VARS:
        os.environ[name] = "1"


@dataclass(frozen=True)
class StudyJob:
    variant: str
    fold: int
    parameters: dict = field(compare=False)
    seed: int


@dataclass(frozen=True)
class RunBatch:
    results: tuple[dict, ...]
    worker_count: int

    @property
    def json_bytes(self) -> bytes:
        return (json.dumps({"results": self.results}, sort_keys=True, separators=(",", ":"),
                           allow_nan=False) + "\n").encode()


def _seed(master_seed: int, variant: str, fold: int) -> int:
    material = f"{master_seed}\0{variant}\0{fold}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def build_jobs(variants: Mapping[str, Mapping], folds: Iterable[object], *,
               master_seed: int) -> tuple[StudyJob, ...]:
    if type(master_seed) is not int or master_seed < 0:
        raise ValueError("master_seed must be a non-negative integer")
    indexes = sorted({int(getattr(fold, "index", fold)) for fold in folds})
    if not variants or not indexes:
        raise ValueError("at least one variant and fold are required")
    jobs = []
    for variant in sorted(variants):
        if not variant:
            raise ValueError("variant names cannot be empty")
        encoded = json.dumps(variants[variant], sort_keys=True, separators=(",", ":"),
                             allow_nan=False)
        parameters = json.loads(encoded)
        if not isinstance(parameters, dict):
            raise ValueError("variant parameters must be mappings")
        jobs.extend(StudyJob(variant, fold, parameters, _seed(master_seed, variant, fold))
                    for fold in indexes)
    return tuple(jobs)


def _execute(item: tuple[Callable[[StudyJob], Mapping], StudyJob]) -> dict:
    evaluator, job = item
    evaluated = evaluator(job)
    payload = evaluated.as_dict() if hasattr(evaluated, "as_dict") else dict(evaluated)
    result = {"variant": job.variant, "fold": job.fold, "seed": job.seed,
              "result": payload}
    return json.loads(json.dumps(result, sort_keys=True, separators=(",", ":"),
                                 allow_nan=False))


def _execute_forked(job: StudyJob) -> dict:
    if _FORK_EVALUATOR is None:
        raise RuntimeError("forked study worker has no inherited evaluator")
    return _execute((_FORK_EVALUATOR, job))


def run_jobs(variants: Mapping[str, Mapping], folds: Iterable[object],
             evaluator: Callable[[StudyJob], Mapping], *, master_seed: int,
             max_workers: int | None = None) -> RunBatch:
    """Run canonical jobs; worker count is metadata, never part of result bytes."""
    jobs = build_jobs(variants, folds, master_seed=master_seed)
    default_workers = min(16, os.cpu_count() or 1)
    workers = default_workers if max_workers is None else max_workers
    if type(workers) is not int or workers < 1:
        raise ValueError("max_workers must be a positive integer")
    force_single_thread_blas()
    if workers == 1:
        results = tuple(_execute((evaluator, job)) for job in jobs)
    else:
        global _FORK_EVALUATOR
        # Linux fork shares the immutable panel through copy-on-write and avoids temporary
        # memmap lifecycle/cleanup. Only tiny StudyJob values cross the process queues.
        context = multiprocessing.get_context("fork")
        _FORK_EVALUATOR = evaluator
        try:
            with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
                results = tuple(pool.map(_execute_forked, jobs))
        finally:
            _FORK_EVALUATOR = None
    return RunBatch(results, workers)


def run_simulate_jobs(variants: Mapping[str, Mapping], folds: Iterable[object],
                      simulator: Callable[[StudyJob], object], *, master_seed: int,
                      max_workers: int | None = None) -> RunBatch:
    """Schedule native ledger-producing jobs through the deterministic runner."""
    return run_jobs(variants, folds, simulator, master_seed=master_seed,
                    max_workers=max_workers)
