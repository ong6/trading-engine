"""Contamination-labelled 2022 model replay with future outcomes withheld."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

import numpy as np

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import write_text_atomic
from engine.lib.settings import DATA_DIR, DEFAULT_DB, REPO_ROOT
from server import agent_model_client
from server.file_utils import read_bytes

REGISTRATION = REPO_ROOT / "farm/experiments/agent-2022-replay-v1.json"
OUTPUT = DATA_DIR / "reports/experiments/agent-2022-replay-v1"
FIELDS = {"schema_version", "asset", "direction", "expected_return_pct",
          "confidence", "thesis", "invalidation"}


class ReplayError(RuntimeError):
    """Historical replay input, output, or retained evidence is invalid."""


def registration() -> dict:
    return json.loads(read_bytes(REGISTRATION, label="2022 replay registration"))


def _rows(con, ticker: str, end: date, count: int) -> list[tuple]:
    return list(reversed(con.execute(
        "SELECT date, open, close, volume FROM prices WHERE ticker=? AND date<=? "
        "AND close>0 ORDER BY date DESC LIMIT ?", [ticker, end, count]
    ).fetchall()))


def _features(rows: list[tuple]) -> tuple[dict, str]:
    if len(rows) < 253:
        raise ReplayError("price history is incomplete")
    close = np.array([float(row[2]) for row in rows])
    volume = np.array([float(row[3]) for row in rows])
    daily = np.diff(close) / close[:-1]
    features = {
        "close": float(close[-1]),
        "return_5d": float(close[-1] / close[-6] - 1),
        "return_20d": float(close[-1] / close[-21] - 1),
        "return_60d": float(close[-1] / close[-61] - 1),
        "return_126d": float(close[-1] / close[-127] - 1),
        "return_252d": float(close[-1] / close[-253] - 1),
        "volatility_20d_annualized": float(np.std(daily[-20:], ddof=1) * math.sqrt(252)),
        "drawdown_from_252d_high": float(close[-1] / np.max(close[-252:]) - 1),
        "above_50d_average": bool(close[-1] > np.mean(close[-50:])),
        "above_200d_average": bool(close[-1] > np.mean(close[-200:])),
        "relative_volume_20d": float(volume[-1] / np.median(volume[-21:-1])),
    }
    prefix = [(row[0].isoformat(), *row[1:]) for row in rows]
    return features, canonical_sha256(prefix)


def build_input(con, config: dict, decision_date: date, variant: str) -> tuple[dict, dict]:
    aliases = {
        ticker: f"Asset {chr(65 + index)}"
        for index, ticker in enumerate(config["assets"])
    }
    named = variant == "price_named"
    assets = []
    for ticker in config["assets"]:
        features, digest = _features(_rows(con, ticker, decision_date, 253))
        assets.append({
            "asset": ticker if named else aliases[ticker],
            "features": features,
            "data_prefix_sha256": digest,
        })
    market, market_hash = _features(
        _rows(con, config["market_context_symbol"], decision_date, 253)
    )
    prompt = {
        "schema_version": 1,
        "task": "select one asset or cash for the next 20 sessions",
        "variant": variant,
        "decision_date": decision_date.isoformat() if named else "withheld",
        "choices": [item["asset"] for item in assets] + ["CASH"],
        "market_context": {
            "asset": "SPY" if named else "Market",
            "features": market,
            "data_prefix_sha256": market_hash,
        },
        "assets": assets,
        "known_limitations": [
            "possible_model_training_memory",
            "current_universe_survivorship_bias",
        ],
        "execution_authority": "none",
    }
    return prompt, aliases


def validate(output: object, choices: list[str]) -> dict:
    if not isinstance(output, dict) or set(output) != FIELDS:
        raise ReplayError("model decision shape is invalid")
    confidence = output.get("confidence")
    expected = output.get("expected_return_pct")
    numbers = (confidence, expected)
    if (
        output.get("schema_version") != 1
        or output.get("asset") not in choices
        or output.get("direction") not in {"up", "down", "flat"}
        or any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in numbers)
        or not 0 <= confidence <= 1
        or not -30 <= expected <= 30
        or (output["asset"] == "CASH"
            and (output["direction"] != "flat" or expected != 0))
    ):
        raise ReplayError("model decision value is invalid")
    if any(
        not isinstance(output.get(field), str)
        or not output[field].strip()
        or len(output[field]) > 1000
        for field in ("thesis", "invalidation")
    ):
        raise ReplayError("model decision text is invalid")
    return {**output, "confidence": float(confidence),
            "expected_return_pct": float(expected)}


def outcome(con, ticker: str | None, decision_date: date, horizon: int) -> dict:
    dates = [row[0] for row in con.execute(
        "SELECT date FROM prices WHERE ticker='SPY' AND date>? ORDER BY date LIMIT ?",
        [decision_date, horizon],
    ).fetchall()]
    if len(dates) != horizon:
        raise ReplayError("future outcome window is incomplete")
    if ticker is None:
        return {"entry_date": dates[0].isoformat(), "exit_date": dates[-1].isoformat(),
                "net_return": 0.0, "round_trip_cost_bps": 0}
    entry = con.execute(
        "SELECT open FROM prices WHERE ticker=? AND date=?", [ticker, dates[0]]
    ).fetchone()
    exit_row = con.execute(
        "SELECT close FROM prices WHERE ticker=? AND date=?", [ticker, dates[-1]]
    ).fetchone()
    if not entry or not exit_row or not entry[0] or not exit_row[0]:
        raise ReplayError("selected outcome bar is unavailable")
    gross = float(exit_row[0]) / float(entry[0]) - 1
    net = float(exit_row[0]) * 0.999 / (float(entry[0]) * 1.001) - 1
    return {"entry_date": dates[0].isoformat(), "exit_date": dates[-1].isoformat(),
            "entry_open": float(entry[0]), "exit_close": float(exit_row[0]),
            "gross_return": gross, "net_return": net, "round_trip_cost_bps": 20}


def summarize(rows: list[dict]) -> dict:
    values = [row["outcome"]["net_return"] for row in rows]
    correct = [
        (row["decision"]["direction"] == "up" and row["outcome"]["net_return"] > 0)
        or (row["decision"]["direction"] == "down" and row["outcome"]["net_return"] < 0)
        or (row["decision"]["direction"] == "flat" and row["outcome"]["net_return"] == 0)
        for row in rows
    ]
    wealth = peak = 1.0
    drawdown = 0.0
    for value in values:
        wealth *= 1 + value
        peak = max(peak, wealth)
        drawdown = min(drawdown, wealth / peak - 1)
    return {
        "decision_count": len(rows),
        "direction_accuracy": sum(correct) / len(correct),
        "mean_net_return": sum(values) / len(values),
        "cumulative_return": wealth - 1,
        "maximum_drawdown": drawdown,
        "turnover_round_trips": sum(row["selected_ticker"] != "CASH" for row in rows),
        "total_cost_bps": sum(row["outcome"]["round_trip_cost_bps"] for row in rows),
        "mean_excess_vs_spy": sum(row["excess_vs_spy"] for row in rows) / len(rows),
    }


def _generate_decisions(con, config: dict, decision_file: Path) -> list[dict]:
    decisions = json.loads(decision_file.read_text()) if decision_file.exists() else []
    expected = {(variant, raw_date) for variant in config["variants"]
                for raw_date in config["decision_dates"]}
    observed = [(item.get("variant"), item.get("decision_date")) for item in decisions]
    if len(observed) != len(set(observed)) or not set(observed) <= expected:
        raise ReplayError("retained decision set is invalid")
    for variant in config["variants"]:
        for raw_date in config["decision_dates"]:
            if (variant, raw_date) in observed:
                continue
            prompt, aliases = build_input(con, config, date.fromisoformat(raw_date), variant)
            response = agent_model_client.generate_historical_replay_json(prompt)
            decisions.append({
                "variant": variant, "decision_date": raw_date, "prompt": prompt,
                "decision": validate(response.output, prompt["choices"]),
                "alias_map": aliases if variant == "price_blinded" else None,
                "model": response.model, "model_version": response.model_version,
                "response_id": response.response_id,
                "request_sha256": response.request_sha256, "usage": response.usage,
                "proxy_version": response.proxy_version,
                "proxy_source_sha256": response.proxy_source_sha256,
                "traecli_runtime": response.traecli_runtime,
                "upstream_model_family": response.upstream_model_family,
                "upstream_request_id": response.upstream_request_id,
                "model_catalog_entry_sha256": response.model_catalog_entry_sha256,
            })
            write_text_atomic(
                decision_file, json.dumps(decisions, indent=2, sort_keys=True) + "\n"
            )
    return decisions


def _reveal(con, config: dict, decisions: list[dict]) -> list[dict]:
    results = []
    for record in decisions:
        chosen = record["decision"]["asset"]
        ticker = chosen
        if record["alias_map"] is not None:
            ticker = {alias: symbol for symbol, alias in record["alias_map"].items()}.get(
                chosen, chosen
            )
        decision_date = date.fromisoformat(record["decision_date"])
        selected = outcome(
            con, None if ticker == "CASH" else ticker,
            decision_date, config["holding_sessions"],
        )
        spy = outcome(con, "SPY", decision_date, config["holding_sessions"])
        results.append({
            **record, "selected_ticker": ticker, "outcome": selected,
            "spy_net_return": spy["net_return"],
            "excess_vs_spy": selected["net_return"] - spy["net_return"],
        })
    return results


def _render(report: dict) -> str:
    lines = [
        "# 2022 agent replay",
        "",
        "**CONTAMINATED RETROSPECTIVE DIAGNOSTIC - NOT ALPHA EVIDENCE.**",
        "",
        "The current model may remember 2022 and the current-symbol archive is "
        "survivor-biased. No 2022 point-in-time fundamentals or timestamped news "
        "exist locally, so those variants are unavailable.",
        "",
        "| Variant | Date | Choice | Prediction | Expected | Net return | SPY excess |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for row in report["results"]:
        decision = row["decision"]
        lines.append(
            f"| {row['variant']} | {row['decision_date']} | {row['selected_ticker']} | "
            f"{decision['direction']} | {decision['expected_return_pct']:+.2f}% | "
            f"{row['outcome']['net_return']:+.2%} | {row['excess_vs_spy']:+.2%} |"
        )
    lines.extend([
        "", "## Summary", "",
        "| Variant | Decisions | Accuracy | Mean net | Cumulative | Max DD | Mean excess vs SPY |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for variant, item in report["summary"].items():
        lines.append(
            f"| {variant} | {item['decision_count']} | {item['direction_accuracy']:.0%} | "
            f"{item['mean_net_return']:+.2%} | {item['cumulative_return']:+.2%} | "
            f"{item['maximum_drawdown']:+.2%} | {item['mean_excess_vs_spy']:+.2%} |"
        )
    return "\n".join(lines) + "\n"


def run(*, database: Path = DEFAULT_DB, output: Path = OUTPUT) -> dict:
    config = registration()
    output.mkdir(parents=True, exist_ok=True)
    decision_file = output / "decisions.json"
    con = db.connect(database, read_only=True, wait_s=0)
    try:
        decisions = _generate_decisions(con, config, decision_file)
        required = len(config["variants"]) * len(config["decision_dates"])
        if len(decisions) != required:
            raise ReplayError("historical decisions are incomplete; outcomes remain withheld")
        results = _reveal(con, config, decisions)
    finally:
        con.close()
    summary = {
        variant: summarize([row for row in results if row["variant"] == variant])
        for variant in config["variants"]
    }
    report = {
        "experiment_id": config["experiment_id"],
        "interpretation": config["interpretation"],
        "known_contamination": config["known_contamination"],
        "unavailable_variants": config["unavailable_variants"],
        "results": results,
        "summary": summary,
    }
    write_text_atomic(
        output / "result.json", json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    write_text_atomic(output / "README.md", _render(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = run(database=args.database, output=args.output)
    print(json.dumps({
        "status": "complete", "decisions": len(report["results"]),
        "summary": report["summary"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
