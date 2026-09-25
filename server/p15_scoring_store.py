"""Durable P15 scoring runs, model samples, and retained news receipts."""
from __future__ import annotations

import json
from datetime import date, datetime

import duckdb

from engine.lib.provenance import canonical_sha256

SCHEMA_VERSION = 1
POLICY_ID = "p15-scoring-v1"
_TABLES = {"p15_scoring_runs", "p15_scoring_samples"}


class ScoringStoreError(ValueError):
    """P15 scoring state is invalid or inconsistent with replay."""


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _next_id(con: duckdb.DuckDBPyConnection, table: str) -> int:
    if table not in _TABLES:
        raise ScoringStoreError("P15 scoring table is invalid")
    return int(con.execute(f"SELECT COALESCE(MAX(id),0)+1 FROM {table}").fetchone()[0])


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_scoring_runs (
        id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, policy_id VARCHAR NOT NULL,
        market_date DATE NOT NULL, universe_payload VARCHAR NOT NULL,
        universe_sha256 VARCHAR NOT NULL, context_payload VARCHAR NOT NULL,
        context_sha256 VARCHAR NOT NULL, status VARCHAR NOT NULL, reason VARCHAR,
        information_cutoff_at TIMESTAMP NOT NULL, started_at TIMESTAMP NOT NULL,
        completed_at TIMESTAMP, aggregate_trace_sha256 VARCHAR,
        UNIQUE(policy_id,market_date), UNIQUE(universe_sha256))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_scoring_samples (
        id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, run_id BIGINT NOT NULL,
        chunk_index INTEGER NOT NULL, sample_index INTEGER NOT NULL,
        permutation_seed BIGINT NOT NULL, ticker_order VARCHAR NOT NULL,
        request_payload VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL,
        status VARCHAR NOT NULL, response_id VARCHAR, response_payload VARCHAR,
        response_sha256 VARCHAR, model VARCHAR, model_version VARCHAR,
        proxy_version VARCHAR, proxy_source_sha256 VARCHAR, traecli_runtime VARCHAR,
        upstream_model_family VARCHAR, upstream_request_id VARCHAR,
        model_catalog_entry_sha256 VARCHAR, input_tokens INTEGER, output_tokens INTEGER,
        total_tokens INTEGER, error VARCHAR, started_at TIMESTAMP NOT NULL,
        completed_at TIMESTAMP, UNIQUE(run_id,chunk_index,sample_index),
        UNIQUE(request_sha256))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_scoring_news_responses (
        run_id BIGINT NOT NULL, ticker VARCHAR NOT NULL, endpoint VARCHAR NOT NULL,
        requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL,
        http_status INTEGER NOT NULL, content_type VARCHAR NOT NULL,
        response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL,
        receipt_sha256 VARCHAR NOT NULL, UNIQUE(run_id,ticker),
        UNIQUE(receipt_sha256))"""
    )


def find_run(
    con: duckdb.DuckDBPyConnection, market_date: date
) -> dict | None:
    cursor = con.execute(
        "SELECT * FROM p15_scoring_runs WHERE policy_id=? AND market_date=?",
        [POLICY_ID, market_date],
    )
    row = cursor.fetchone()
    return None if row is None else dict(
        zip((item[0] for item in cursor.description), row, strict=True)
    )


def create_run(
    con: duckdb.DuckDBPyConnection,
    *,
    market_date: date,
    universe: dict,
    context: dict,
    information_cutoff_at: datetime,
    started_at: datetime,
    news_receipts: list[dict],
) -> dict:
    universe_payload, context_payload = _json(universe), _json(context)
    universe_sha = canonical_sha256(universe)
    context_sha = canonical_sha256(context)
    existing = find_run(con, market_date)
    if existing is not None:
        if (
            existing["universe_sha256"] != universe_sha
            or existing["context_sha256"] != context_sha
        ):
            raise ScoringStoreError("P15 scoring run replay differs from retained snapshot")
        return {"run_id": int(existing["id"]), "replayed": True,
                "status": existing["status"]}
    run_id = _next_id(con, "p15_scoring_runs")
    con.execute(
        "INSERT INTO p15_scoring_runs VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,NULL,NULL)",
        [run_id, SCHEMA_VERSION, POLICY_ID, market_date, universe_payload,
         universe_sha, context_payload, context_sha, "running",
         information_cutoff_at, started_at],
    )
    for receipt in news_receipts:
        con.execute(
            "INSERT INTO p15_scoring_news_responses VALUES (?,?,?,?,?,?,?,?,?,?)",
            [run_id, receipt["ticker"], receipt["endpoint"], receipt["requested_at"],
             receipt["received_at"], receipt["http_status"], receipt["content_type"],
             receipt["response_sha256"], receipt["response_body"],
             receipt["receipt_sha256"]],
        )
    return {"run_id": run_id, "replayed": False, "status": "running"}


def start_sample(
    con: duckdb.DuckDBPyConnection,
    *,
    run_id: int,
    chunk_index: int,
    sample_index: int,
    permutation_seed: int,
    ticker_order: list[str],
    request_payload: dict,
    started_at: datetime,
) -> dict:
    request_text = _json(request_payload)
    request_sha = canonical_sha256(request_payload)
    row = con.execute(
        "SELECT id,status,request_sha256,permutation_seed,ticker_order "
        "FROM p15_scoring_samples WHERE run_id=? AND chunk_index=? AND sample_index=?",
        [run_id, chunk_index, sample_index],
    ).fetchone()
    order_text = _json(ticker_order)
    if row is not None:
        if row[2:] != (request_sha, permutation_seed, order_text):
            raise ScoringStoreError("P15 scoring sample replay differs")
        return {"sample_id": int(row[0]), "status": row[1], "replayed": True}
    sample_id = _next_id(con, "p15_scoring_samples")
    con.execute(
        "INSERT INTO p15_scoring_samples VALUES (?,?,?,?,?,?,?,?,?,'started',"
        "NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?,NULL)",
        [sample_id, SCHEMA_VERSION, run_id, chunk_index, sample_index,
         permutation_seed, order_text, request_text, request_sha, started_at],
    )
    return {"sample_id": sample_id, "status": "started", "replayed": False}


def complete_sample(
    con: duckdb.DuckDBPyConnection,
    sample_id: int,
    *,
    response: dict,
    completed_at: datetime,
) -> None:
    row = con.execute(
        "SELECT status,response_sha256 FROM p15_scoring_samples WHERE id=?",
        [sample_id],
    ).fetchone()
    if row is None:
        raise ScoringStoreError("P15 scoring sample is missing")
    response_sha = canonical_sha256(response)
    if row[0] == "completed":
        if row[1] != response_sha:
            raise ScoringStoreError("P15 scoring response replay differs")
        return
    if row[0] != "started":
        raise ScoringStoreError("P15 scoring sample is terminal")
    usage = response["usage"]
    con.execute(
        "UPDATE p15_scoring_samples SET status='completed',response_id=?,"
        "response_payload=?,response_sha256=?,model=?,model_version=?,proxy_version=?,"
        "proxy_source_sha256=?,traecli_runtime=?,upstream_model_family=?,"
        "upstream_request_id=?,model_catalog_entry_sha256=?,input_tokens=?,output_tokens=?,"
        "total_tokens=?,completed_at=? WHERE id=? AND status='started'",
        [response["response_id"], _json(response), response_sha, response["model"],
         response["model_version"], response["proxy_version"],
         response["proxy_source_sha256"], response["traecli_runtime"],
         response["upstream_model_family"], response["upstream_request_id"],
         response["model_catalog_entry_sha256"], usage["input_tokens"],
         usage["output_tokens"], usage["total_tokens"], completed_at, sample_id],
    )


def fail_sample(
    con: duckdb.DuckDBPyConnection,
    sample_id: int,
    *,
    reason: str,
    completed_at: datetime,
    response: dict | None = None,
    metadata: dict | None = None,
) -> None:
    if not reason.strip():
        raise ScoringStoreError("P15 scoring failure reason is empty")
    metadata = metadata or {}
    usage = (response or {}).get("usage") or metadata.get("usage") or {}
    response_payload = None if response is None else _json(response)
    response_sha = metadata.get("response_sha256") or (
        None if response is None else canonical_sha256(response)
    )
    changed = con.execute(
        "UPDATE p15_scoring_samples SET status='failed',response_id=?,response_payload=?,"
        "response_sha256=?,model=?,model_version=?,proxy_version=?,proxy_source_sha256=?,"
        "traecli_runtime=?,upstream_model_family=?,upstream_request_id=?,"
        "model_catalog_entry_sha256=?,input_tokens=?,output_tokens=?,total_tokens=?,"
        "error=?,completed_at=? WHERE id=? AND status='started' RETURNING id",
        [metadata.get("response_id") or (response or {}).get("response_id"),
         response_payload, response_sha, (response or {}).get("model"),
         (response or {}).get("model_version"), (response or {}).get("proxy_version"),
         (response or {}).get("proxy_source_sha256"), (response or {}).get("traecli_runtime"),
         (response or {}).get("upstream_model_family"),
         (response or {}).get("upstream_request_id"),
         (response or {}).get("model_catalog_entry_sha256"), usage.get("input_tokens"),
         usage.get("output_tokens"), usage.get("total_tokens"), reason[:512],
         completed_at, sample_id],
    ).fetchone()
    if changed is None:
        status = con.execute(
            "SELECT status FROM p15_scoring_samples WHERE id=?", [sample_id]
        ).fetchone()
        if status is None or status[0] != "failed":
            raise ScoringStoreError("P15 scoring sample cannot fail")


def complete_run(
    con: duckdb.DuckDBPyConnection,
    run_id: int,
    *,
    trace_sha256: str,
    completed_at: datetime,
) -> None:
    terminal = con.execute(
        "SELECT COUNT(*) FROM p15_scoring_samples WHERE run_id=? AND status='started'",
        [run_id],
    ).fetchone()[0]
    if terminal:
        raise ScoringStoreError("P15 scoring run has nonterminal samples")
    changed = con.execute(
        "UPDATE p15_scoring_runs SET status='completed',completed_at=?,"
        "aggregate_trace_sha256=? WHERE id=? AND status='running' RETURNING id",
        [completed_at, trace_sha256, run_id],
    ).fetchone()
    if changed is None:
        row = con.execute(
            "SELECT status,aggregate_trace_sha256 FROM p15_scoring_runs WHERE id=?",
            [run_id],
        ).fetchone()
        if row != ("completed", trace_sha256):
            raise ScoringStoreError("P15 scoring run completion differs")
