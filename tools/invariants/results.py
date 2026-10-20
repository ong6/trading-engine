"""Result invariants: no NaN or infinity in experiment and walk-forward results.

Experiment rows come from the snapshot's ``experiment_results``; walk-forward and experiment
result files come from the engine checkout's committed ``data/reports`` (they are not in the
store). JSON allows neither NaN nor infinity, so a strict reader rejects such a file.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .registry import CannotEvaluate, Context, register, violation

WALKFORWARD_RESULTS = Path("data") / "reports" / "walkforward" / "results"
EXPERIMENT_REPORTS = Path("data") / "reports" / "experiments"
NONFINITE_TOKENS = ("NaN", "Infinity", "-Infinity")


def _nonfinite_paths(value, path: str = "$"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _nonfinite_paths(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _nonfinite_paths(item, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        yield path, str(value)


@register("experiment_results_finite", "results", tables=("experiment_results",))
def experiment_results_finite(ctx: Context) -> tuple[dict, list[dict]]:
    """Every numeric column and the ``meta_json`` payload of every experiment row is finite."""
    columns = [name for name, kind in ctx.con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'experiment_results' ORDER BY ordinal_position").fetchall()
        if kind in {"DOUBLE", "FLOAT", "REAL"}]
    keys = "experiment_id, config_hash, partition, CAST(trade_date AS VARCHAR)"
    rows = ctx.con.execute(
        f"SELECT {keys}, [{', '.join(repr(name) for name in columns)}], "
        f"[{', '.join(f'NOT isfinite({name})' for name in columns)}], meta_json "
        f"FROM experiment_results ORDER BY ALL").fetchall() if columns else []
    total = ctx.con.execute("SELECT COUNT(*) FROM experiment_results").fetchone()[0]
    found = []
    for experiment, config, partition, trade_date, names, bad, meta in rows:
        subject = " ".join(str(part) for part in (experiment, (config or "")[:12], partition,
                                                    trade_date) if part)
        flagged = [name for name, is_bad in zip(names, bad, strict=True) if is_bad]
        if flagged:
            found.append(violation(subject, "nonfinite_column", columns=flagged))
        if meta:
            try:
                paths = list(_nonfinite_paths(json.loads(meta)))
            except ValueError:
                found.append(violation(subject, "unreadable_meta"))
                continue
            if paths:
                found.append(violation(subject, "nonfinite_meta",
                                       paths=[path for path, _value in paths][:20]))
    return {"rows": total, "numeric_columns": len(columns)}, found


@register("walkforward_results_finite", "results")
def walkforward_results_finite(ctx: Context) -> tuple[dict, list[dict]]:
    """Every walk-forward and experiment result file parses without a non-finite number."""
    walkforward = ctx.engine_root / WALKFORWARD_RESULTS
    if not walkforward.is_dir():
        raise CannotEvaluate("walk-forward results directory is missing")
    files = sorted(walkforward.glob("*.json"))
    experiments = ctx.engine_root / EXPERIMENT_REPORTS
    files += sorted(experiments.rglob("*.json")) if experiments.is_dir() else []
    found = []
    for path in files:
        name = path.relative_to(ctx.engine_root / "data" / "reports").with_suffix("")
        label = name.as_posix().replace("/", ":")
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            found.append(violation(label, "unreadable"))
            continue
        found += [violation(f"{label} {where}", "nonfinite", value=value)
                  for where, value in _nonfinite_paths(payload)]
    return {"files": len(files), "files_with_nonfinite": len(
        {item["subject"].split(" ")[0] for item in found})}, found
