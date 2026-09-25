"""Durability and replay tests for the P15 scoring store."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone

from engine.lib import db
from server import agent_model_client
from server import p15_scoring_store as store

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


def _result() -> dict:
    return asdict(agent_model_client.ConnectorResult(
        output={"schema_version": 1, "assessments": []}, response_id="resp-p15",
        model=agent_model_client.MODEL, model_version=agent_model_client.MODEL_VERSION,
        proxy_version="0.7", proxy_source_sha256="a" * 64, traecli_runtime="test",
        upstream_model_family=agent_model_client.UPSTREAM_MODEL_FAMILY,
        upstream_request_id="upstream-p15", model_catalog_entry_sha256="b" * 64,
        request_sha256="c" * 64,
        usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    ))


def test_scoring_store_retains_snapshot_samples_and_exact_replay(tmp_path):
    database = tmp_path / "market.duckdb"
    con = db.connect(database)
    store.init_schema(con)
    universe = {"market_date": "2026-09-24", "candidates": [{"ticker": "AAA"}]}
    context = {"news_status": "available"}
    receipt = {
        "ticker": "AAA", "endpoint": "https://example.test", "requested_at": NOW,
        "received_at": NOW, "http_status": 200, "content_type": "application/json",
        "response_sha256": "d" * 64, "response_body": b"{}", "receipt_sha256": "e" * 64,
    }
    run = store.create_run(
        con, market_date=date(2026, 9, 24), universe=universe, context=context,
        information_cutoff_at=NOW, started_at=NOW, news_receipts=[receipt],
    )
    replay = store.create_run(
        con, market_date=date(2026, 9, 24), universe=universe, context=context,
        information_cutoff_at=NOW, started_at=NOW, news_receipts=[receipt],
    )
    assert replay == {"run_id": run["run_id"], "replayed": True, "status": "running"}
    sample = store.start_sample(
        con, run_id=run["run_id"], chunk_index=0, sample_index=0,
        permutation_seed=123, ticker_order=["AAA"], request_payload={"input": "x"},
        started_at=NOW,
    )
    store.complete_sample(con, sample["sample_id"], response=_result(), completed_at=NOW)
    store.complete_sample(con, sample["sample_id"], response=_result(), completed_at=NOW)
    store.complete_run(con, run["run_id"], trace_sha256="f" * 64, completed_at=NOW)
    assert con.execute(
        "SELECT status,aggregate_trace_sha256 FROM p15_scoring_runs"
    ).fetchone() == ("completed", "f" * 64)
    assert con.execute(
        "SELECT status,permutation_seed,ticker_order FROM p15_scoring_samples"
    ).fetchone() == ("completed", 123, '["AAA"]')
    assert con.execute("SELECT COUNT(*) FROM p15_scoring_news_responses").fetchone() == (1,)
    con.close()


def test_started_sample_is_not_recreated_and_failure_is_terminal(tmp_path):
    con = db.connect(tmp_path / "market.duckdb")
    store.init_schema(con)
    run = store.create_run(
        con, market_date=date(2026, 9, 24), universe={"id": 1}, context={"id": 2},
        information_cutoff_at=NOW, started_at=NOW, news_receipts=[],
    )
    first = store.start_sample(
        con, run_id=run["run_id"], chunk_index=0, sample_index=0,
        permutation_seed=7, ticker_order=["AAA"], request_payload={"sample": 1},
        started_at=NOW,
    )
    replay = store.start_sample(
        con, run_id=run["run_id"], chunk_index=0, sample_index=0,
        permutation_seed=7, ticker_order=["AAA"], request_payload={"sample": 1},
        started_at=NOW,
    )
    assert replay == {"sample_id": first["sample_id"], "status": "started", "replayed": True}
    store.fail_sample(con, first["sample_id"], reason="interrupted", completed_at=NOW)
    store.fail_sample(con, first["sample_id"], reason="interrupted", completed_at=NOW)
    assert con.execute("SELECT status,error FROM p15_scoring_samples").fetchone() == (
        "failed", "interrupted"
    )
    con.close()
