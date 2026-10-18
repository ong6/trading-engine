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
