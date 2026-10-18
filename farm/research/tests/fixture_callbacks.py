"""Importable callbacks used by research contract tests and examples."""

import os


def feature_recipe(inputs, parameters):
    return {"rows": inputs, "parameters": parameters}


def strategy(features, parameters, seed, mode):
    if "OUTCOME_ROOT" in os.environ:
        raise AssertionError("outcome namespace leaked into the strategy child")
    return {
        "features": features.read_json("features.json"),
        "mode": mode,
        "parameters": parameters,
        "pid": os.getpid(),
        "seed": seed,
    }


def outcomes(predictions, labels, evaluation):
    return {
        "evaluation": evaluation["benchmark_mode"],
        "labels": labels.read_json("labels.json"),
        "predictions": predictions,
    }


def deterministic_strategy(features, parameters, seed, mode):
    return {
        "features": features.read_json("features.json"),
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
        "features": features.read_json("features.json"),
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
    return {"checks": checks, "feature": features.read_json("features.json")}
