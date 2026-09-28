"""Generate the compact weekly P15/P16 operator digest."""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db, resources
from engine.lib.settings import DATA_DIR, DEFAULT_DB
from engine.lib.util import table_exists
from server import meta_projection, p16_filing_runner, p16_reporting

DEFAULT_EVALUATION = DATA_DIR / "reports" / "agent-evaluation.json"
DEFAULT_WEEKLY_DIR = DATA_DIR / "reports" / "weekly"
MODEL_VERSION_WARNING = "unversioned-catalog-alias"


def _status(value: object) -> str:
    return str(value.get("status", "unavailable")) if isinstance(value, dict) \
        else "unavailable"


def _number(value: object, *, digits: int = 3) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) \
            or not math.isfinite(value):
        return "unavailable"
    return f"{value:.{digits}g}"


def _load_evaluation(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"status": "unavailable", "reason": "evaluation_report_unavailable"}
    if not isinstance(value, dict):
        return {"status": "unavailable", "reason": "evaluation_report_invalid"}
    return value


def filing_activity(con, *, environ: dict[str, str] | None = None) -> dict:
    """Summarize W3 activity without initializing or changing its store."""
    ready = p16_filing_runner.readiness(environ=os.environ if environ is None else environ)
    if not table_exists(con, "p16_filing_scans"):
        return {**ready, "scan_count": 0, "accession_count": 0,
                "scored_count": 0, "unavailable_count": 0,
                "latest_session": None}
    scan_count, latest = con.execute(
        "SELECT COUNT(*),MAX(session_date) FROM p16_filing_scans"
    ).fetchone()
    accession_count = int(con.execute(
        "SELECT COUNT(*) FROM p16_filing_accessions"
    ).fetchone()[0]) if table_exists(con, "p16_filing_accessions") else 0
    scored = unavailable = 0
    if table_exists(con, "p16_filing_decisions"):
        scored, unavailable = con.execute(
            "SELECT COUNT(*) FILTER (WHERE status='scored'),"
            "COUNT(*) FILTER (WHERE status<>'scored') FROM p16_filing_decisions"
        ).fetchone()
    return {**ready, "scan_count": int(scan_count),
            "accession_count": accession_count, "scored_count": int(scored),
            "unavailable_count": int(unavailable),
            "latest_session": None if latest is None else latest.isoformat()}


def fill_quality(con) -> dict:
    """Compare the latest five measured sessions with the preceding five."""
    if not table_exists(con, "p16_fill_measurements"):
        return {"status": "collecting", "measurement_count": 0,
                "session_count": 0, "latest_session": None,
                "latest_median_abs_vwap_gap_bp": None,
                "prior_median_abs_vwap_gap_bp": None, "drift_bp": None}
    rows = con.execute(
        "SELECT session_date,payload_json FROM p16_fill_measurements "
        "ORDER BY session_date,measurement_sha256"
    ).fetchall()
    by_session: dict[date, list[float]] = {}
    for session, payload_json in rows:
        try:
            value = json.loads(payload_json).get("vwap_gap_bp")
            value = float(value)
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if math.isfinite(value):
            by_session.setdefault(session, []).append(abs(value))
    sessions = sorted(by_session)
    latest_sessions, prior_sessions = sessions[-5:], sessions[-10:-5]

    def window_median(selected: list[date]) -> float | None:
        values = [value for session in selected for value in by_session[session]]
        return None if not values else statistics.median(values)

    latest_value, prior_value = window_median(latest_sessions), window_median(prior_sessions)
    return {
        "status": "available" if latest_value is not None and prior_value is not None
        else "collecting",
        "measurement_count": len(rows), "session_count": len(sessions),
        "latest_session": None if not sessions else sessions[-1].isoformat(),
        "latest_median_abs_vwap_gap_bp": latest_value,
        "prior_median_abs_vwap_gap_bp": prior_value,
        "drift_bp": None if latest_value is None or prior_value is None
        else latest_value - prior_value,
    }


def _unavailable_p16(reason: str) -> dict:
    return {"status": "unavailable", "reason": reason, "family_report": None,
            "promotion_candidate_ids": [], "construction": {"status": "unavailable"}}


def _unavailable_health(reason: str) -> dict:
    return {key: {"status": "unavailable", "reason": reason} for key in (
        "nightly", "weekly_walkforward", "walkforward_evidence", "scheduler",
        "source_control", "queue",
    )}


def collect(
    con, *, generated_at: datetime, evaluation_path: Path,
    meta_path: Path, data_dir: Path, environ: dict[str, str] | None = None,
) -> dict:
    """Collect independent source projections; one unavailable source stays local."""
    try:
        p16 = p16_reporting.project(con, generated_at=generated_at)
    except (duckdb.Error, OSError, TypeError, ValueError):
        p16 = _unavailable_p16("p16_projection_unavailable")
    try:
        health = meta_projection.project(con, meta_path=meta_path, data_dir=data_dir)
    except (duckdb.Error, OSError, TypeError, ValueError):
        health = _unavailable_health("meta_projection_unavailable")
    try:
        filings = filing_activity(con, environ=environ)
    except (duckdb.Error, OSError, TypeError, ValueError):
        filings = {"status": "unavailable", "scan_count": 0, "accession_count": 0,
                   "scored_count": 0, "unavailable_count": 0, "latest_session": None}
    try:
        fills = fill_quality(con)
    except (duckdb.Error, TypeError, ValueError):
        fills = {"status": "unavailable", "measurement_count": 0,
                 "session_count": 0, "latest_session": None,
                 "latest_median_abs_vwap_gap_bp": None,
                 "prior_median_abs_vwap_gap_bp": None, "drift_bp": None}
    return {
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "evaluation": _load_evaluation(evaluation_path), "p16": p16,
        "filings": filings, "fills": fills, "health": health,
    }


def markdown(report: dict) -> str:
    """Render a bounded weekly decision surface from the collected projections."""
    evaluation = report.get("evaluation", {})
    p15 = evaluation.get("p15", {}) if isinstance(evaluation, dict) else {}
    primary = p15.get("primary", {}) if isinstance(p15, dict) else {}
    books = p15.get("books", {}) if isinstance(p15, dict) else {}
    events = p15.get("events", {}) if isinstance(p15, dict) else {}
    p16 = report.get("p16", {})
    family = p16.get("family_report") if isinstance(p16, dict) else None
    comparisons = family.get("comparisons", []) if isinstance(family, dict) else []
    ranked = sorted(
        comparisons,
        key=lambda row: row.get("deflated_sharpe", {}).get("probability")
        if isinstance(row.get("deflated_sharpe", {}).get("probability"), (int, float))
        else float("-inf"),
        reverse=True,
    )
    cohorts = evaluation.get("cohorts", []) if isinstance(evaluation, dict) else []
    models = sorted({str(row.get("model")) for row in cohorts
                     if isinstance(row, dict) and row.get("model")})
    versions = sorted({str(row.get("model_version")) for row in cohorts
                       if isinstance(row, dict) and row.get("model_version")})
    model_text = ", ".join(models) or "unavailable"
    version_text = ", ".join(versions) or MODEL_VERSION_WARNING
    next_look = primary.get("next_look")
    next_date = primary.get("earliest_next_look_date")
    lines = [
        f"# Weekly operator digest — {report['generated_at'][:10]}", "",
        f"> **MODEL IDENTITY WARNING — `{MODEL_VERSION_WARNING}`.** The current model "
        "name is a catalogue alias, not an immutable provider revision. It may collect paper "
        "evidence but is not eligible for real-capital authority.", "",
        f"Generated: `{report['generated_at']}`  ",
        f"Observed model: `{model_text}`; reported version: `{version_text}`", "",
        "## Gates and next looks", "",
        "| Gate | Status | Evidence / next look |", "|---|---|---|",
        f"| P15 primary | {_status(p15)} | {primary.get('scored_session_count', 0)} scored; "
        f"next {next_look if next_look is not None else 'complete'}; "
        f"earliest {next_date or 'unavailable'} |",
        f"| P8 rule | {_status(evaluation.get('p8_evaluation'))} | "
        f"{evaluation.get('p8_evaluation', {}).get('completed_session_count', 0)} sessions |",
        f"| P16 family | {_status(p16)} | {len(comparisons)} comparisons; "
        f"{len(p16.get('promotion_candidate_ids', [])) if isinstance(p16, dict) else 0} candidates |",
        "", "## Books against controls", "",
        "| Challenger | Status | Paired returns | Positive lower bound |",
        "|---|---|---:|---|",
    ]
    book_comparisons = books.get("comparisons", []) if isinstance(books, dict) else []
    if book_comparisons:
        for row in book_comparisons:
            lines.append(
                f"| {row.get('challenger', 'unavailable')} vs control | {_status(books)} | "
                f"{row.get('paired_return_count', 0)} | "
                f"{'yes' if row.get('positive_lower_bound') else 'no'} |")
    else:
        lines.append("| unavailable | unavailable | 0 | no |")
    lines.extend(["", "## Challenger leaderboard (deflated)", "",
                  "| Rank | Comparison | DSR probability | Max log-e | Promotion |",
                  "|---:|---|---:|---:|---|"])
    if ranked:
        for index, row in enumerate(ranked, 1):
            primary_test = row.get("sequential", {}).get("primary", {})
            lines.append(
                f"| {index} | {row.get('comparison_id', 'unavailable')} | "
                f"{_number(row.get('deflated_sharpe', {}).get('probability'))} | "
                f"{_number(primary_test.get('max_log_e'))} | "
                f"{'yes' if row.get('candidate_for_promotion') else 'no'} |")
    else:
        lines.append(f"| — | {_status(p16)} | unavailable | unavailable | no |")
    filings, fills = report.get("filings", {}), report.get("fills", {})
    lines.extend([
        "", "## Filing, event, and fill activity", "",
        f"- P15 event shadow: **{_status(events)}**; {events.get('window_count', 0)} windows, "
        f"{events.get('decision_count', 0)} decisions.",
        f"- P16 filing reader: **{_status(filings)}**; {filings.get('scan_count', 0)} scans, "
        f"{filings.get('accession_count', 0)} accessions, {filings.get('scored_count', 0)} scored, "
        f"{filings.get('unavailable_count', 0)} unavailable.",
        f"- Fill quality: **{_status(fills)}**; {fills.get('measurement_count', 0)} measurements "
        f"over {fills.get('session_count', 0)} sessions; latest/prior median |VWAP-open| "
        f"{_number(fills.get('latest_median_abs_vwap_gap_bp'))}/"
        f"{_number(fills.get('prior_median_abs_vwap_gap_bp'))} bp; drift "
        f"{_number(fills.get('drift_bp'))} bp.",
        "", "## Producer health", "",
        "| Producer | Status |", "|---|---|",
    ])
    health = report.get("health", {})
    for key in ("nightly", "weekly_walkforward", "walkforward_evidence", "scheduler",
                "source_control", "queue"):
        lines.append(f"| {key.replace('_', ' ')} | {_status(health.get(key))} |")
    owner_items = [
        "Provide a provider-issued immutable model revision before any real-capital decision."
    ]
    if _status(filings) == "unconfigured":
        owner_items.append("Provide the SEC contact string before activating the filing reader.")
    if any(row.get("candidate_for_promotion") for row in comparisons):
        owner_items.append("Review any P16 promotion candidate; the report grants no authority.")
    lines.extend(["", "## Owner needed", ""])
    lines.extend(f"- {item}" for item in owner_items)
    lines.extend(["", "Execution authority: **none**.", ""])
    return "\n".join(lines)


def run(
    *, database: Path = DEFAULT_DB, evaluation_path: Path = DEFAULT_EVALUATION,
    meta_path: Path = DATA_DIR / "_meta.json", data_dir: Path = DATA_DIR,
    output: Path | None = None, generated_at: datetime | None = None,
) -> Path:
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("digest generation time must be timezone-aware")
    generated_at = generated_at.astimezone(timezone.utc)
    destination = output or DEFAULT_WEEKLY_DIR / f"{generated_at.date().isoformat()}.md"
    con = db.connect(database, read_only=True, wait_s=0)
    try:
        report = collect(con, generated_at=generated_at, evaluation_path=evaluation_path,
                         meta_path=meta_path, data_dir=data_dir)
    finally:
        con.close()
    resources.write_text_atomic(destination, markdown(report))
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--meta-path", type=Path, default=DATA_DIR / "_meta.json")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--generated-at", type=datetime.fromisoformat)
    args = parser.parse_args(argv)
    output = run(database=args.database, evaluation_path=args.evaluation,
                 meta_path=args.meta_path, data_dir=args.data_dir,
                 output=args.output, generated_at=args.generated_at)
    print(json.dumps({"status": "complete", "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
