"""Importable callbacks used by research contract tests and examples."""


def feature_recipe(inputs, parameters):
    return {"rows": inputs, "parameters": parameters}


def strategy(features, parameters, seed, mode):
    return {
        "features": features.read_json("features.json"),
        "mode": mode,
        "parameters": parameters,
        "seed": seed,
    }


def outcomes(predictions, labels, evaluation):
    return {
        "evaluation": evaluation["benchmark_mode"],
        "labels": labels.read_json("labels.json"),
        "predictions": predictions,
    }
