"""Importable callbacks used by research contract tests and examples."""

import os


def feature_recipe(inputs, parameters):
    rows = inputs.read_json("parts/0.json")
    return [
        {
            "session": row["session"],
            "score": float(row["close"]) / 100.0,
            "available_at": f"{row['session']}T16:00:00-05:00",
        }
        for row in rows
    ]


def malformed_feature_recipe(inputs, parameters):
    return [{"scores": [1, 2, 3], "future_return": 9.0}]


def probing_feature_recipe(inputs, parameters):
    try:
        inputs.read_bytes("parts/1.json")
    except Exception:
        blocked = True
    else:
        blocked = False
    return [{
        "session": row["session"],
        "score": float(row["close"]) / 100.0,
        "outcome_probe_blocked": blocked,
        "available_at": f"{row['session']}T16:00:00-05:00",
    } for row in inputs.read_json("parts/0.json")]


def future_feature_recipe(inputs, parameters):
    return [{
        "session": row["session"],
        "score": 999.0,
        "available_at": "2099-01-01T00:00:00+00:00",
    } for row in inputs.read_json("parts/0.json")]


def same_day_late_feature_recipe(inputs, parameters):
    return [{
        "session": row["session"],
        "score": 999.0,
        "available_at": f"{row['session']}T23:59:59-05:00",
    } for row in inputs.read_json("parts/0.json")]


def date_only_feature_recipe(inputs, parameters):
    return [{
        "session": row["session"],
        "score": float(row["close"]) / 100.0,
        "available_at": row["session"],
    } for row in inputs.read_json("parts/0.json")]


def ticker_feature_recipe(inputs, parameters):
    return [{
        "session": row["session"],
        "ticker": row["ticker"],
        "score": float(row["close"]) / 100.0,
        "available_at": f"{row['session']}T16:00:00-05:00",
    } for row in inputs.read_json("parts/0.json")]


def label_recipe(inputs, parameters):
    rows = inputs.read_json("parts/0.json")
    return [
        {
            "session": row["session"],
            "entry_at": row["entry_at"],
            "entry_price": float(row["entry_price"]),
            "exit_at": row["exit_at"],
            "exit_price": float(row["exit_price"]),
            "available_at": row["exit_at"],
        }
        for row in rows
    ]


def misaligned_label_recipe(inputs, parameters):
    return label_recipe(inputs, parameters)[:1]


def same_bar_label_recipe(inputs, parameters):
    rows = label_recipe(inputs, parameters)
    rows[0]["entry_at"] = "2024-01-02T16:00:00-05:00"
    return rows


def wrong_horizon_label_recipe(inputs, parameters):
    rows = label_recipe(inputs, parameters)
    rows[0]["exit_at"] = "2024-01-04T16:00:00-05:00"
    return rows


def strategy(features, parameters, seed, mode):
    if "OUTCOME_ROOT" in os.environ:
        raise AssertionError("outcome namespace leaked into the strategy child")
    rows = features.read_json("nodes/fixture.json")
    positions = [] if parameters["_study_job"]["kind"] == "control" else [
        {"session": row["session"], "weight": 1.0} for row in rows
    ]
    return {"positions": positions}


def deterministic_strategy(features, parameters, seed, mode):
    return strategy(features, parameters, seed, mode)


def variant_direction_strategy(features, parameters, seed, mode):
    rows = features.read_json("nodes/fixture.json")
    if parameters["_study_job"]["kind"] == "control":
        return {"positions": []}
    direction = 1.0 if parameters["variant_value"] == 0 else -1.0
    return {"positions": [
        {"session": row["session"], "weight": direction} for row in rows
    ]}


def crashing_strategy(features, parameters, seed, mode):
    raise RuntimeError("synthetic strategy crash")


def invented_return_strategy(features, parameters, seed, mode):
    return {"positions": [], "gross_return": 99.0}


def slow_strategy(features, parameters, seed, mode):
    import time

    time.sleep(0.15)
    return strategy(features, parameters, seed, mode)


def single_decision_strategy(features, parameters, seed, mode):
    rows = features.read_json("nodes/fixture.json")
    if len(rows) != 1 or rows[0]["session"] != parameters["_study_job"]["decision_session"]:
        raise ValueError("strategy received later or unrelated decision rows")
    return strategy(features, parameters, seed, mode)


def adversarial_strategy(features, parameters, seed, mode):
    import glob
    import importlib
    import socket
    import subprocess
    from pathlib import Path

    checks = {}

    def blocked(name, function):
        try:
            value = function()
        except Exception as exc:
            checks[name] = {"blocked": True, "error": type(exc).__name__}
        else:
            checks[name] = {"blocked": False, "value": str(value)[:100]}

    blocked("absolute", lambda: Path(parameters["absolute_outcome"]).read_text())
    blocked("module_relative", lambda: Path(__file__).with_name("outcome_secret.txt").read_text())
    blocked(
        "import",
        lambda: importlib.import_module("farm.research.tests.secret_module").SECRET,
    )
    blocked(
        "glob",
        lambda: (_ for _ in ()).throw(RuntimeError("not found"))
        if not glob.glob("/**/outcome_secret.txt", recursive=True)
        else glob.glob("/**/outcome_secret.txt", recursive=True),
    )
    blocked("proc", lambda: Path("/proc/self/cmdline").read_bytes())
    blocked("network", lambda: socket.socket())
    blocked("process", lambda: subprocess.run(["/usr/bin/true"], check=True))
    return {"positions": []}
