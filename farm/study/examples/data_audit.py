"""Offline fictional omission diagnostic; no real market or strategy evidence."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.lib.resources import write_text_atomic
from sim import nyse

from ..audit import (
    AuditContract,
    AuditExecutionError,
    AuditListing,
    AuditSnapshot,
    Availability,
    InputRequirement,
    audit_study,
)
from ..audit_report import AuditReportError, write_audit
from ..benchmark import Benchmark
from ..costs import CostSelection
from ..data import Bar, MarketData, PriceSource
from ..protocol import run_identity
from ..report import build_report, write_report
from ..simulate import simulate_events
from ..spec import EventStrategy, ExitRule, FillPoint, Order
from ..universe import ListingInterval, Universe

DECISION_SESSION = date(2024, 3, 28)
NAMES = ("GAIN_A", "GAIN_B", "ENDED_A", "ENDED_B")
COSTS = CostSelection("ibkr_tiered_auction_v1", ("ibkr_fixed_v1",))
CAPITAL = 40_000.0
EXPECTED = {
    "incomplete": {"trades": 2, "gross_pnl": 400.0, "costs": 10.37032,
                   "net_pnl": 389.62968, "net_return": 0.009740742},
    "complete": {"trades": 4, "gross_pnl": -800.0, "costs": 20.41616,
                 "net_pnl": -820.41616, "net_return": -0.020510404},
}


def fictional_orders(view, session: date) -> list[Order]:
    """Reference-backed attempts stay fixed; absent signal values are never filled."""
    orders = []
    for ticker in ("GAIN_A", "GAIN_B", "ENDED_A", "ENDED_B"):
        history = view.history(ticker, ("close",), before=session, limit=1)
        signal = {"previous_close": history[-1]["close"]} if history else None
        orders.append(Order(ticker, "long", FillPoint.open_auction(),
                            ExitRule.same_session_close(), 10_000, signal=signal))
    return orders


STRATEGY = EventStrategy(
    "fictional-coverage-diagnostic", "pre_open", fictional_orders, 4, 10_000,
    {"reference_names": list(NAMES), "signal_input": "previous-session close",
     "attempt_policy": "all four reference members; missing signals remain missing"})


def fixture() -> tuple[AuditContract, AuditSnapshot, dict[str, AuditSnapshot]]:
    """Explicit planted outcomes and omission transform; no seed search."""
    calendar = [DECISION_SESSION]
    current = DECISION_SESSION
    while len(calendar) < 61:
        current -= timedelta(days=1)
        if nyse.is_session(current):
            calendar.append(current)
    calendar.reverse()
    zone = ZoneInfo("America/New_York")
    known_at = datetime.combine(calendar[0], datetime.min.time(), zone)
    listings = tuple(AuditListing(ticker, calendar[0],
                                 DECISION_SESSION if ticker.startswith("ENDED") else None,
                                 available_at=known_at) for ticker in NAMES)
    bars = []
    for day in calendar:
        for ticker in NAMES:
            close = (102.0 if ticker.startswith("GAIN") else 94.0
                     ) if day == DECISION_SESSION else 100.0
            bars.append(Bar(ticker, day, 100.0, max(100.0, close), min(100.0, close),
                            close, 1_000_000.0))
    reference = AuditSnapshot("fictional-independent-reference", tuple(bars), listings,
                              membership_basis="observed_source")
    complete = AuditSnapshot("fictional-audited-source", tuple(bars))
    incomplete = replace(complete, bars=tuple(bar for bar in bars if bar.ticker in NAMES[:2]))
    late = replace(complete, availability=(Availability(
        "GAIN_A", calendar[-2], "close",
        datetime(2024, 3, 28, 10, tzinfo=zone)),))
    contract = AuditContract(
        "fictional-omission-diagnostic", (DECISION_SESSION,), DECISION_SESSION,
        requirements=(InputRequirement("close", lookback=1, offset=1),),
        window_sessions=60, min_history=60, evidence_limit=20)
    return contract, reference, {"incomplete": incomplete, "complete": complete,
                                "late_input": late}


def independent_arithmetic(names: tuple[str, ...]) -> dict:
    """Expand the frozen fee schedule without calling native cost calculation."""
    gross, total = 0.0, 0.0
    for ticker in names:
        close = 102.0 if ticker.startswith("GAIN") else 94.0
        shares, entry_value, exit_value = 100.0, 10_000.0, 100.0 * close
        entry_fee = 0.35 + 0.0020 * shares + 0.0002 * entry_value
        exit_fee = (0.35 + 0.0020 * shares + 0.0002 * exit_value
                    + 0.0000028 * exit_value + 0.000166 * shares)
        gross += shares * (close - 100.0)
        total += entry_fee + exit_fee
    return {"trades": len(names), "gross_pnl": gross, "costs": total,
            "net_pnl": gross - total, "net_return": (gross - total) / CAPITAL}


def evaluate(snapshot: AuditSnapshot, reference: AuditSnapshot) -> tuple[dict, object, object]:
    source = PriceSource.declared(source=snapshot.source, bars=snapshot.bars)
    data = MarketData(source)
    universe = Universe(source, tuple(ListingInterval(
        row.ticker, row.listed_from, row.listed_through) for row in reference.listings))
    ledger = simulate_events(STRATEGY, data, universe, (DECISION_SESSION,), COSTS, Benchmark("cash"))
    identity = run_identity(STRATEGY, COSTS, source.declaration.snapshot_sha256)
    native = {
        "trades": len(ledger.trades),
        "gross_pnl": sum(row.gross_return * row.notional for row in ledger.trades),
        "costs": sum(row.costs_by_profile[COSTS.primary]["total"] for row in ledger.trades),
        "net_pnl": sum(row.net_return * row.notional for row in ledger.trades),
        "net_return": float(ledger.calendar_returns()[0]),
    }
    report = build_report(
        identity=identity, data=data, costs=COSTS, benchmark=Benchmark("cash"),
        variants=[{"variant": STRATEGY.name, "net_return": native["net_return"],
                   "benchmark_return": 0.0, "excess_return": native["net_return"],
                   "absolute_net_positive": native["net_return"] > 0,
                   "trades": len(ledger.trades), "one_sided_t": None}],
        folds=[], hard_max_date=DECISION_SESSION, ledger=ledger,
        runtime_seconds=0.0, worker_count=1, job_count=1, cpu_count=1,
        serial_parallel_identical=None)
    return {"identity": identity.as_dict(), "result": native, "report": report}, ledger, data


def run_demo(output_dir: str | Path | None = None) -> dict:
    contract, reference, snapshots = fixture()
    results = {}
    for name, snapshot in snapshots.items():
        evaluation, ledger, _data = evaluate(snapshot, reference)
        included = NAMES[:2] if name == "incomplete" else NAMES
        independent = independent_arithmetic(included)
        expected = EXPECTED["incomplete" if name == "incomplete" else "complete"]
        for key, value in independent.items():
            if (not math.isclose(value, expected[key], abs_tol=1e-9, rel_tol=0)
                    or not math.isclose(evaluation["result"][key], value, abs_tol=1e-9, rel_tol=0)):
                raise ValueError(f"fictional known answer differs: {name}/{key}")
        bound = replace(contract, study_run_id=evaluation["identity"]["sha256"])
        audit = audit_study(bound, snapshot, reference, outcomes=ledger.as_dict())
        results[name] = {"audit": audit, "native": evaluation["result"],
                         "independent": independent, "study_identity": evaluation["identity"],
                         "attempts": ledger.as_dict()}
        if output_dir is not None:
            target = Path(output_dir) / name
            write_audit(target, audit)
            write_report(target, evaluation["report"])
    summary = {
        "schema_version": 1,
        "purpose": "Synthetic diagnostic — not a trading recommendation",
        "fault": "Hindsight omission retains only the two favorable fictional securities.",
        "limitations": ["One diagnostic decision session, not a historical screen or holdout.",
                        "Reference-backed orders remain attempted when audited signal input is missing.",
                        "Late availability evidence is audit-only; this does not trace arbitrary strategy access."],
        "capital": CAPITAL, "reference_sha256": reference.sha256, "results": results,
    }
    if output_dir is not None:
        write_text_atomic(Path(output_dir) / "demo.json",
                          json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n")
        write_text_atomic(Path(output_dir) / "demo.md", demo_markdown(summary))
    return summary


def demo_markdown(summary: dict) -> str:
    """Readable comparison derived exclusively from the exported summary."""
    lines = ["# Fictional market-data audit demonstration", "", summary["purpose"], "",
             "The frozen rule attempts all four reference members: $10,000 each, "
             "open-auction entry and same-session-close exit. Signal evidence is the "
             "previous-session close, available before the open. Both datasets use "
             "$40,000 capital, a cash benchmark, and the same named cost schedules.", "",
             "The incomplete dataset looks positive; restoring the omitted securities "
             "makes the identical rule negative after costs.", "",
             "| Dataset | Complete inputs / expected | Trades / missing entry | "
             "Primary costs | Net P&L | Return on $40,000 | Audit decision |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for name, result in summary["results"].items():
        audit, native = result["audit"], result["native"]
        session = audit["sessions"][0]
        missing = result["attempts"]["unfilled_counts"].get("missing_entry_bar", 0)
        lines.append(f"| {name} | {session['complete_inputs']}/{session['expected']} | "
                     f"{native['trades']}/{missing} | ${native['costs']:.5f} | "
                     f"${native['net_pnl']:.5f} | {native['net_return']:+.7%} | "
                     f"{audit['decision']} |")
    lines += ["", "Primary costs: `ibkr_tiered_auction_v1`; sensitivity: `ibkr_fixed_v1`. "
              "Missing attempts retain their native exclusion reason; unused capital "
              "stays in the $40,000 return denominator.", "",
              "The late-input variant changes one prior-close availability timestamp "
              "to after the decision. Its four later outcomes remain valid; the audit "
              "flags the unavailable signal input. This timestamp evidence is audit-only "
              "and does not prove that arbitrary strategy code respects it.", "",
              "## Inspect the evidence", "",
              "- [Canonical comparison and independent arithmetic](demo.json)"]
    for name in summary["results"]:
        lines.append(f"- {name}: [audit]({name}/audit.md), "
                     f"[canonical audit]({name}/audit.json), "
                     f"[native study report]({name}/report.md)")
    lines += ["", "## Limitations", "", summary["fault"], ""]
    lines.extend("- " + limitation for limitation in summary["limitations"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = run_demo(args.output_dir)
    except (AuditExecutionError, AuditReportError, ValueError) as exc:
        failure = exc.as_dict() if isinstance(exc, AuditExecutionError) else {
            "status": "execution_error", "error": str(exc)}
        print(json.dumps(failure, sort_keys=True))
        return 2
    print(json.dumps({"purpose": summary["purpose"], "results": {
        name: {"decision": row["audit"]["decision"], "net_return": row["native"]["net_return"]}
        for name, row in summary["results"].items()}}, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
