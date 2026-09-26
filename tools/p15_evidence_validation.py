"""Read-only integrity checks for P15 pre-open and event evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timezone

import duckdb

from engine import p15_event_sources
from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256

MAX_AUDIT_ROWS = 100_000


def enforce_bounds(con: duckdb.DuckDBPyConnection, error_type) -> None:
    tables = (
        "agent_evaluation_traces", "agent_evaluation_decisions", "agent_evaluation_labels_v2",
        "p15_scoring_runs", "p15_scoring_samples", "p15_scoring_news_responses",
        "p15_order_intents", "p15_limit_attempts", "p15_book_windows", "p15_book_fills",
        "p15_limit_labels", "p15_preopen_runs", "p15_preopen_decisions",
        "p15_preopen_news_responses", "p15_event_triggers", "p15_event_windows",
        "p15_event_calls", "p15_event_decisions", "p15_event_labels",
    )
    for table in tables:
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name=?", [table]
        ).fetchone()[0]
        if exists and con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > MAX_AUDIT_ROWS:
            raise error_type(f"P15 evidence exceeds bounded audit size: {table}")
    for table in ("sim_orders", "sim_fills", "sim_equity"):
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name=?", [table]
        ).fetchone()[0]
        if exists and con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE portfolio_id IN "
            "('p15_ai_ranked','p15_rule_control','p15_hybrid_veto')"
        ).fetchone()[0] > MAX_AUDIT_ROWS:
            raise error_type(f"P15 evidence exceeds bounded audit size: {table}")


def validate_links(con: duckdb.DuckDBPyConnection, error_type) -> None:
    if con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='p15_scoring_runs'"
    ).fetchone()[0]:
        bad = con.execute(
            "SELECT COUNT(*) FROM p15_scoring_runs r LEFT JOIN agent_evaluation_traces t "
            "ON t.trace_sha256=r.aggregate_trace_sha256 AND t.policy_id=r.policy_id "
            "AND t.source_kind='p15_scoring_run' AND t.source_identifier=CAST(r.id AS VARCHAR) "
            "WHERE r.status='completed' AND t.id IS NULL"
        ).fetchone()[0]
        if bad:
            raise error_type("P15 completed scoring run has no canonical trace")
    if con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='agent_evaluation_decisions'"
    ).fetchone()[0]:
        orphan_decisions = con.execute(
            "SELECT COUNT(*) FROM agent_evaluation_decisions d LEFT JOIN agent_evaluation_traces t "
            "ON t.id=d.trace_id WHERE t.id IS NULL AND "
            "json_extract_string(d.decision_payload,'$.scoring_status') IS NOT NULL"
        ).fetchone()[0]
        orphan_labels = con.execute(
            "SELECT COUNT(*) FROM agent_evaluation_labels_v2 l LEFT JOIN "
            "agent_evaluation_decisions d ON d.id=l.decision_id WHERE d.id IS NULL"
        ).fetchone()[0]
        if orphan_decisions or orphan_labels:
            raise error_type("P15 scoring evidence has orphan rows")


def validate_common_labels(con, generated_at: datetime, error_type, _label_outcome) -> None:
    if not con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name='agent_evaluation_labels_v2'"
    ).fetchone()[0]:
        return
    rows = con.execute(
        "SELECT l.*,d.ticker FROM agent_evaluation_labels_v2 l "
        "JOIN agent_evaluation_decisions d ON d.id=l.decision_id "
        "WHERE l.label_basis='common_entry' AND l.labeled_at<=? ORDER BY l.id",
        [generated_at.replace(tzinfo=None)],
    )
    columns = [item[0] for item in rows.description]
    for values in rows.fetchall():
        row = dict(zip(columns, values, strict=True))
        body = {key: row[key] for key in (
            "schema_version", "decision_id", "horizon_sessions", "label_basis", "entry_open",
            "exit_close", "asset_return", "spy_return", "excess_return",
            "maximum_adverse_excursion", "maximum_favorable_excursion", "price_prefix_sha256",
            "missing_bar_status", "round_trip_cost_bps", "net_return", "net_excess_return",
        )}
        body.update(entry_date=row["entry_date"].isoformat(), exit_date=row["exit_date"].isoformat())
        close = datetime.combine(
            row["exit_date"], p15_event_sources.session_close(row["exit_date"]),
            p15_event_sources.ET,
        ).astimezone(timezone.utc).replace(tzinfo=None)
        if (canonical_sha256(body) != row["label_sha256"]
                or row["labeled_at"] < close):
            raise error_type("common-entry label evidence differs")


def validate_preopen(con: duckdb.DuckDBPyConnection, generated_at: datetime, error_type) -> None:
    from server import p15_preopen

    orphans = con.execute(
        "SELECT (SELECT COUNT(*) FROM p15_preopen_decisions d LEFT JOIN p15_preopen_runs r "
        "ON r.id=d.run_id WHERE r.id IS NULL)+(SELECT COUNT(*) FROM p15_preopen_news_responses n "
        "LEFT JOIN p15_preopen_runs r ON r.id=n.run_id WHERE r.id IS NULL)"
    ).fetchone()[0]
    if orphans:
        raise error_type("P15 pre-open evidence has orphan rows")
    for run_id, run_status in con.execute(
        "SELECT id,status FROM p15_preopen_runs WHERE status<>'running' ORDER BY id"
    ).fetchall():
        try:
            p15_preopen._replay_run(con, int(run_id), run_status)
        except p15_preopen.PreopenError as exc:
            raise error_type("P15 pre-open evidence differs") from exc
    for intent_id, intent_status, session_date, outcome in con.execute(
        "SELECT d.intent_id,i.status,r.session_date,a.outcome "
        "FROM p15_preopen_decisions d JOIN p15_preopen_runs r ON r.id=d.run_id "
        "JOIN p15_order_intents i ON i.id=d.intent_id LEFT JOIN "
        "(SELECT intent_id,outcome FROM p15_limit_attempts WHERE outcome LIKE 'cancelled_%' "
        "QUALIFY ROW_NUMBER() OVER (PARTITION BY intent_id ORDER BY attempt_date DESC)=1) a "
        "ON a.intent_id=d.intent_id WHERE d.decision='cancel' ORDER BY d.id"
    ).fetchall():
        closed = generated_at.astimezone(p15_preopen.ET).date() > session_date
        if intent_status != "cancelled" or outcome not in {
            None, "cancelled_would_fill", "cancelled_limit_not_reached"
        } or (closed and outcome is None):
            raise error_type(f"P15 cancelled intent {intent_id} evidence differs")


def validate_book_links(con: duckdb.DuckDBPyConnection, error_type) -> None:
    missing = con.execute(
        "SELECT (SELECT COUNT(*) FROM sim_fills f LEFT JOIN p15_book_fills p "
        "ON p.order_id=f.order_id WHERE f.portfolio_id IN "
        "('p15_ai_ranked','p15_rule_control','p15_hybrid_veto') AND p.order_id IS NULL)+"
        "(SELECT COUNT(*) FROM sim_orders o LEFT JOIN p15_order_intents i "
        "ON i.sim_order_id=o.id WHERE o.portfolio_id IN "
        "('p15_ai_ranked','p15_rule_control','p15_hybrid_veto') AND i.id IS NULL)+"
        "(SELECT COUNT(*) FROM p15_book_fills f LEFT JOIN p15_order_intents i "
        "ON i.id=f.intent_id WHERE i.id IS NULL)+"
        "(SELECT COUNT(*) FROM sim_equity e LEFT JOIN p15_book_windows w "
        "ON w.portfolio_id=e.portfolio_id AND w.market_date=e.date WHERE e.portfolio_id IN "
        "('p15_ai_ranked','p15_rule_control','p15_hybrid_veto') AND w.portfolio_id IS NULL "
        "AND e.date<>(SELECT MIN(e2.date) FROM sim_equity e2 WHERE e2.portfolio_id=e.portfolio_id))"
    ).fetchone()[0]
    if missing:
        raise error_type("P15 book evidence has orphan rows")


def _event_label_expected(con, row: dict, label_outcome, event_runner):
    ticker, decision_at = con.execute(
        "SELECT ticker,decision_at FROM p15_event_decisions WHERE id=?", [row["decision_id"]]
    ).fetchone()
    labeled_at = row["labeled_at"].replace(tzinfo=timezone.utc)
    if row["label_basis"] == "next_session_open":
        sessions = [item[0] for item in con.execute(
            f"SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>? "
            f"AND fetched_at<=? AND {REAL_BAR_SQL} ORDER BY date LIMIT ?",
            [decision_at.date(), row["labeled_at"], row["horizon_sessions"]],
        ).fetchall()]
        outcome = label_outcome(con, ticker, sessions, labeled_at) \
            if len(sessions) == row["horizon_sessions"] else None
        entry_at = None if outcome is None else datetime.combine(
            outcome["entry_date"], time(9, 30), p15_event_sources.ET
        ).astimezone(timezone.utc).replace(tzinfo=None)
        entry_px = None if outcome is None else float(outcome["entry_open"])
        spy_return = None if outcome is None else float(outcome["spy_return"])
    elif row["missing_bar_status"] == "missing_next_bar_last_available_close":
        missing = event_runner._missing_next_bar(con, ticker, decision_at, labeled_at)
        entry_at, entry_px, outcome = (None, None, None) if missing is None else missing
        spy_return = 0.0
    else:
        end = datetime.combine(
            decision_at.replace(tzinfo=timezone.utc).astimezone(
                p15_event_sources.ET
            ).date(), p15_event_sources.session_close(decision_at.date()),
            p15_event_sources.ET,
        ).astimezone(timezone.utc).replace(tzinfo=None)
        intraday = con.execute(
            "WITH known AS (SELECT security_id,event_at,normalized_payload,fact_sha256 "
            "FROM bitemporal_facts WHERE fact_type='intraday.ohlcv.5m' AND event_at>? "
            "AND event_at<? AND available_at<=? AND ingested_at<=? QUALIFY revision=MAX(revision) "
            "OVER (PARTITION BY entity_id,fact_type,event_at)) SELECT a.event_at,"
            "a.normalized_payload,a.fact_sha256,s.normalized_payload,s.fact_sha256 FROM known a "
            "JOIN known s ON s.security_id='SPY' AND s.event_at=a.event_at "
            "WHERE a.security_id=? ORDER BY a.event_at LIMIT 1",
            [decision_at, end, row["labeled_at"], row["labeled_at"], ticker],
        ).fetchone()
        day = decision_at.date()
        sessions = [item[0] for item in con.execute(
            f"SELECT DISTINCT date FROM prices WHERE ticker='SPY' AND date>=? "
            f"AND fetched_at<=? AND {REAL_BAR_SQL} ORDER BY date LIMIT ?",
            [day, row["labeled_at"], row["horizon_sessions"]],
        ).fetchall()]
        outcome = label_outcome(con, ticker, sessions, labeled_at) \
            if intraday is not None and len(sessions) == row["horizon_sessions"] else None
        if outcome is not None:
            entry_at, asset_raw, asset_sha, spy_raw, spy_sha = intraday
            asset, spy = json.loads(asset_raw), json.loads(spy_raw)
            spy_exit = con.execute(
                f"SELECT close FROM prices WHERE ticker='SPY' AND date=? "
                f"AND fetched_at<=? AND {REAL_BAR_SQL}",
                [outcome["exit_date"], row["labeled_at"]],
            ).fetchone()
            if spy_exit is None:
                outcome = None
            else:
                outcome = {**outcome, "price_prefix_sha256": canonical_sha256({
                    "daily": outcome["price_prefix_sha256"],
                    "entry_facts": [asset_sha, spy_sha]})}
                entry_px = float(asset["open"])
                spy_return = float(spy_exit[0]) / float(spy["open"]) - 1
        else:
            entry_at = entry_px = spy_return = None
    if outcome is None:
        return None
    asset_return = float(outcome["exit_close"]) / entry_px - 1
    net_return = float(outcome["exit_close"]) * 0.999 / (entry_px * 1.001) - 1
    spy_net = (1 + spy_return) * 0.999 / 1.001 - 1
    return {"decision_id": row["decision_id"], "horizon_sessions": row["horizon_sessions"],
            "label_basis": row["label_basis"], "entry_at": entry_at.isoformat(),
            "exit_date": outcome["exit_date"].isoformat(), "entry_px": entry_px,
            "exit_close": outcome["exit_close"], "asset_return": asset_return,
            "spy_return": spy_return, "net_return": net_return,
            "net_excess_return": net_return - spy_net,
            "missing_bar_status": outcome["missing_bar_status"],
            "price_prefix_sha256": outcome["price_prefix_sha256"]}


def validate_events(con: duckdb.DuckDBPyConnection, error_type, label_outcome) -> None:
    from farm import p15_event_runner

    orphans = con.execute(
        "SELECT (SELECT COUNT(*) FROM p15_event_calls c LEFT JOIN p15_event_windows w "
        "ON w.window_id=c.window_id WHERE w.id IS NULL)+"
        "(SELECT COUNT(*) FROM p15_event_decisions d LEFT JOIN p15_event_windows w "
        "ON w.window_id=d.window_id WHERE w.id IS NULL)+"
        "(SELECT COUNT(*) FROM p15_event_labels l LEFT JOIN p15_event_decisions d "
        "ON d.id=l.decision_id WHERE d.id IS NULL)"
    ).fetchone()[0]
    if orphans:
        raise error_type("P15 event evidence has orphan rows")
    for (window_id,) in con.execute(
        "SELECT window_id FROM p15_event_windows WHERE status<>'running' ORDER BY id"
    ).fetchall():
        try:
            p15_event_runner._replay_window(con, window_id)
        except p15_event_runner.EventRunError as exc:
            raise error_type("P15 event evidence differs") from exc
    for values in con.execute(
        "SELECT session_date,ticker,source,event_type,fact_sha256,triggered_at,trigger_sha256 "
        "FROM p15_event_triggers ORDER BY id"
    ).fetchall():
        identity = {"session_date": values[0].isoformat(), "ticker": values[1],
                    "source": values[2], "event_type": values[3], "fact_sha256": values[4],
                    "triggered_at": values[5].replace(tzinfo=timezone.utc).isoformat()}
        fact = con.execute(
            "SELECT schema_version,entity_id,security_id,fact_type,event_at,published_at,"
            "available_at,ingested_at,revision,normalized_payload,normalized_sha256,source,"
            "source_version,receipt_sha256,previous_fact_sha256,fact_sha256 "
            "FROM bitemporal_facts WHERE fact_sha256=?", [values[4]]
        ).fetchone()
        if fact is None:
            raise error_type("P15 event trigger evidence differs")
        fact_identity = {
            "schema_version": fact[0], "entity_id": fact[1], "security_id": fact[2],
            "fact_type": fact[3], "event_at": fact[4].isoformat(),
            "published_at": None if fact[5] is None else fact[5].isoformat(),
            "available_at": fact[6].isoformat(), "ingested_at": fact[7].isoformat(),
            "revision": fact[8], "normalized_sha256": fact[10], "source": fact[11],
            "source_version": fact[12], "receipt_sha256": fact[13],
            "previous_fact_sha256": fact[14],
        }
        if (canonical_sha256(identity) != values[6]
                or canonical_sha256(json.loads(fact[9])) != fact[10]
                or canonical_sha256(fact_identity) != fact[15]):
            raise error_type("P15 event trigger evidence differs")
        receipt = con.execute(
            "SELECT schema_version,source,dataset,endpoint,request_payload,request_sha256,"
            "requested_at,received_at,http_status,content_type,response_size_bytes,"
            "response_sha256,response_body,license_class,receipt_sha256 "
            "FROM source_response_receipts WHERE receipt_sha256=?", [fact[13]]
        ).fetchone()
        if receipt is None:
            raise error_type("P15 event source receipt is missing")
        receipt_identity = {
            "schema_version": receipt[0], "source": receipt[1], "dataset": receipt[2],
            "endpoint": receipt[3], "request_sha256": receipt[5],
            "requested_at": receipt[6].isoformat(), "received_at": receipt[7].isoformat(),
            "http_status": receipt[8], "content_type": receipt[9],
            "response_size_bytes": receipt[10], "response_sha256": receipt[11],
            "license_class": receipt[13],
        }
        if (hashlib.sha256(receipt[4].encode()).hexdigest() != receipt[5]
                or hashlib.sha256(bytes(receipt[12])).hexdigest() != receipt[11]
                or canonical_sha256(receipt_identity) != receipt[14]):
            raise error_type("P15 event source receipt differs")
    labels = con.execute("SELECT * FROM p15_event_labels ORDER BY id")
    columns = [item[0] for item in labels.description]
    for values in labels.fetchall():
        row = dict(zip(columns, values, strict=True))
        body = {key: row[key] for key in (
            "decision_id", "horizon_sessions", "label_basis", "entry_px", "exit_close",
            "asset_return", "spy_return", "net_return", "net_excess_return",
            "missing_bar_status", "price_prefix_sha256",
        )}
        body.update(entry_at=row["entry_at"].isoformat(), exit_date=row["exit_date"].isoformat())
        expected = _event_label_expected(con, row, label_outcome, p15_event_runner)
        if canonical_sha256(body) != row["label_sha256"] or expected is None \
                or canonical_sha256(expected) != row["label_sha256"]:
            raise error_type("P15 event label evidence differs")
