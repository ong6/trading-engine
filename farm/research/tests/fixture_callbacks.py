"""Importable callbacks used by research contract tests and examples."""

import os


def feature_recipe(inputs, parameters):
    rows = inputs.read_json("parts/0.json")
    return [
        {
            "session": row["session"],
            "score": float(row["close"]) / 100.0,
            "available_at": f"{row['session']}T21:00:00+00:00",
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
        "available_at": f"{row['session']}T21:00:00+00:00",
    } for row in inputs.read_json("parts/0.json")]


def future_feature_recipe(inputs, parameters):
    return [{
        "session": row["session"],
        "score": 999.0,
        "available_at": "2099-01-01T00:00:00+00:00",
    } for row in inputs.read_json("parts/0.json")]


def label_recipe(inputs, parameters):
    rows = inputs.read_json("parts/0.json")
    return [
        {
            "session": row["session"],
            "return_h1": float(row["return_h1"]),
            "available_at": f"{row['session']}T22:00:00+00:00",
        }
        for row in rows
    ]


def misaligned_label_recipe(inputs, parameters):
    return label_recipe(inputs, parameters)[:1]


def strategy(features, parameters, seed, mode):
    if "OUTCOME_ROOT" in os.environ:
        raise AssertionError("outcome namespace leaked into the strategy child")
    return {
        "features": features.read_json("nodes/fixture.json"),
        "mode": mode,
        "parameters": parameters,
        "pid": os.getpid(),
        "seed": seed,
    }


def evaluation_recipe(predictions, labels, evaluation):
    return {
        "metrics": {"score": 1.0},
        "statistics": {name: 1.0 for name in evaluation["statistics"]},
        "controls": {name: 0.0 for name in evaluation["controls"]},
        "cost_profile_hashes": {"fixture-zero": "2" * 64},
        "labels": labels.read_json("labels.json"),
        "job_count": len(predictions["jobs"]),
    }


def missing_control_evaluation(predictions, labels, evaluation):
    return {
        "metrics": {"score": 1.0},
        "statistics": {name: 1.0 for name in evaluation["statistics"]},
        "controls": {},
        "cost_profile_hashes": {"fixture-zero": "2" * 64},
    }


def strong_evaluation_recipe(predictions, labels, evaluation):
    return {
        "metrics": {"score": 2.0},
        "statistics": {name: 1.0 for name in evaluation["statistics"]},
        "controls": {name: 0.0 for name in evaluation["controls"]},
        "cost_profile_hashes": {"fixture-zero": "2" * 64},
    }


def deterministic_strategy(features, parameters, seed, mode):
    return {
        "features": features.read_json("nodes/fixture.json"),
        "mode": mode,
        "parameters": parameters,
        "seed": seed,
    }


def crashing_strategy(features, parameters, seed, mode):
    raise RuntimeError("synthetic strategy crash")


def slow_strategy(features, parameters, seed, mode):
    import time

    time.sleep(0.15)
    return {
        "features": features.read_json("nodes/fixture.json"),
        "job": parameters["_study_job"],
        "seed": seed,
    }


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
    return {"checks": checks, "feature": features.read_json("nodes/fixture.json")}
