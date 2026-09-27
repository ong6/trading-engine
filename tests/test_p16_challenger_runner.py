"""Focused contracts for the timer-backed P16 challenger runner."""
from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from farm import p16_sequential, p16_trials
from server import p16_challenger_runner as runner
from server import p16_model_client, p16_registration

MARKET_DATE = date(2026, 9, 29)
NOW = datetime(2026, 9, 30, 3, 0, tzinfo=timezone.utc)
REGISTERED = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)


def _identity(policy_id):
    return {key: f"{policy_id}:{key}" for key in p16_trials.IDENTITY_FIELDS}


def _trial(policy_id, plan_id="P16"):
    identity = _identity(policy_id)
    trial_id, _payload = p16_trials.registration(
        policy_id=policy_id, policy_version="v1", plan_id=plan_id,
        registration_identity=identity, evidence_class="prospective",
        trial_kind="policy", parent_trial_ids=[], registered_at=REGISTERED,
        identity_status="verified",
    )
    return {
        "trial_id": trial_id, "policy_id": policy_id, "policy_version": "v1",
        "plan_id": plan_id, "registration_identity": identity,
        "evidence_class": "prospective", "trial_kind": "policy",
        "parent_trial_ids": [], "registered_at": REGISTERED.isoformat(),
        "identity_status": "verified",
    }


def _contract(model):
    body = {
        "schema_version": 1, "model": model, "catalog_entry": {"id": model},
        "catalog_entry_sha256": canonical_sha256({"id": model}),
        "upstream_model_family": f"family-{model}", "proxy_version": "fixture-v1",
        "proxy_source_sha256": "a" * 64, "runtime_sha256": "b" * 64,
        "prompt_sha256": canonical_sha256(p16_model_client.prompt()),
        "toolset_sha256": canonical_sha256([]),
        "identity_scope": "observable_catalog_alias", "provider_model_revision": None,
    }
    return {**body, "model_contract_sha256": canonical_sha256(body)}


def _registration(status="active"):
    control = _trial("p15-scoring-v1", plan_id="P15")
    trials = [_trial(policy_id) for policy_id in p16_registration.MEMBER_IDS]
    contracts = [_contract(model) for model in ("fixture-champion", "fixture-55", "fixture-terra")]
    by_model = {row["model"]: row["model_contract_sha256"] for row in contracts}
    treatment_ids = {
        "c-blind": "blind-v1", "c-memory": "champion-memory-v1",
        "c-model-gpt-5.5-max": "same-input-prompt-v2",
        "c-model-gpt-5.6-terra-max": "same-input-prompt-v2",
        "c-ensemble": "fieldwise-mean-v1", "c-price-only": "price-only-v1",
        "c-text-only": "text-only-v1", "c-prompt-v2": "prompt-v2-only",
    }
    members = []
    for trial in trials:
        policy_id = trial["policy_id"]
        model = (
            "fixture-55" if policy_id == "c-model-gpt-5.5-max" else
            "fixture-terra" if policy_id == "c-model-gpt-5.6-terra-max" else
            "fixture-champion"
        )
        members.append({
            "policy_id": policy_id, "comparison_id": policy_id,
            "trial_id": trial["trial_id"], "control_trial_id": control["trial_id"],
            "treatment_id": treatment_ids[policy_id],
            "model_contract_sha256": (
                None if policy_id == "c-ensemble" else by_model[model]),
        })
    body = {
        "schema_version": 1, "registration_id": "p16-challenger-lab-v1",
        "status": status,
        "authority": {
            "scope": "research_shadow_only", "broker_access": False,
            "real_capital": False, "execution_authority": "none",
            "promotion_authority": "owner_review_required",
        },
        "evaluation": {
            "policy_id": "p16-eval-v2", "family_id": "p16-challengers-f1",
            "epoch_session": MARKET_DATE.isoformat(),
            "alpha_allocation": {
                "allocation_id": p16_sequential.ALPHA_ALLOCATION_ID,
                "family_alpha": 0.04, "future_family_reserve": 0.01,
                "lifetime_fwer": 0.05, "family_size": 8,
                "e_bonferroni_threshold": 200.0,
            },
            "prior_mixture": p16_sequential.mixing_from_pre_activation([], []),
            "prior_reason": "fewer_than_20_eligible_preactivation_origins",
        },
        "challengers": {
            "policy_id": "p16-challengers-v1", "universe_version": "p15-universe-v1",
            "members": members,
        },
        "model_contracts": contracts, "trial_registrations": [control, *trials],
    }
    return {**body, "registration_sha256": canonical_sha256(body)}


def _candidate(ticker, evidence):
    return {
        "ticker": ticker, "company_name": f"{ticker} Incorporated",
        "sector": "Technology", "close": 100.0, "daily_return": 0.01,
        "overnight_gap": 0.0, "return_5d": 0.02, "relative_volume_20d": 2.0,
        "median_dollar_volume_20d": 2_000_000.0, "atr_14": 2.0,
        "rs_rank": 90, "template_score": 3.0, "passes_template": True,
        "new_screen_pass": True, "earnings": {
            "status": "available", "next_date": "2026-10-20", "is_estimate": False,
            "snapshot_date": MARKET_DATE.isoformat(),
        },
        "held": False, "tradeable": True, "reason": "eligible",
        "standout_score": 5.0, "stratum": "mover", "selection_ordinal": 1,
        "baseline_rank": 1, "baseline_score": 2, "baseline_version": "fixture",
        "evidence_id": evidence, "headlines": [{
            "title": f"{ticker} raises guidance", "evidence_id": evidence,
        }], "allowed_evidence_ids": [evidence],
    }


def _snapshot():
    candidates = [_candidate("AAA", "c" * 64), _candidate("BBB", "d" * 64)]
    samples = []
    for sample_index in range(3):
        ordered = candidates if sample_index != 1 else list(reversed(candidates))
        samples.append({
            "chunk_index": 0, "sample_index": sample_index,
            "p15_request_sha256": f"{sample_index + 1:064x}",
            "original": {
                "schema_version": 1, "policy_id": "p15-scoring-v1",
                "market_date": MARKET_DATE.isoformat(),
                "information_cutoff_at": "2026-09-29T20:00:00+00:00",
                "chunk_index": 0, "sample_index": sample_index,
                "permutation_seed": sample_index, "market": {
                    "market_date": MARKET_DATE.isoformat(), "spy_close": 500.0,
                    "spy_daily_return": 0.0, "regime": "neutral",
                    "evidence_id": "e" * 64,
                },
                "market_headlines": [], "event_facts": [], "tradingview_quotes": [],
                "candidates": deepcopy(ordered),
            },
        })
    envelope_body = {
        "schema_version": 1, "market_date": MARKET_DATE.isoformat(),
        "available_at": "2026-09-29T20:00:00+00:00",
        "entries": [{
            "ticker": row["ticker"], "company_name": row["company_name"],
            "aliases": [row["ticker"], row["company_name"]],
            "sector": "technology", "name_source": None, "sector_source": None,
        } for row in candidates],
        "name_basis": "latest_universe_snapshot_on_or_before_market_date",
        "sector_basis": "latest_fundamentals_fetched_by_information_cutoff",
    }
    champion = {row["ticker"]: {
        "ticker": row["ticker"], "p_outperform_5": 0.55,
        "expected_excess_bp_5": 20.0, "expected_excess_bp_10": 30.0,
        "action": "watch", "thesis": "Champion thesis.",
        "invalidation": "Champion invalidation.", "evidence_ids": [row["evidence_id"]],
        "scoring_status": "available",
    } for row in candidates}
    return {
        "market_date": MARKET_DATE,
        "cutoff": datetime(2026, 9, 29, 20, tzinfo=timezone.utc),
        "origin": {
            "p15_registration_sha256": "f" * 64,
            "decision_rows": [{"ticker": row["ticker"]} for row in candidates],
        },
        "tickers": [row["ticker"] for row in candidates],
        "candidates": {row["ticker"]: row for row in candidates},
        "chunks": [{"chunk_index": 0, "tickers": {"AAA", "BBB"}, "samples": samples}],
        "champion": champion,
        "metadata_envelope": {
            **envelope_body,
            "metadata_envelope_sha256": canonical_sha256(envelope_body),
        },
        "memory_history": [],
        "source_identity": {
            "p15_registration_sha256": "f" * 64, "p15_run_id": 1,
            "p15_run_trace_sha256": "1" * 64, "p15_bundle_sha256": "2" * 64,
            "p15_universe_sha256": "3" * 64, "p15_context_sha256": "4" * 64,
            "metadata_envelope_sha256": canonical_sha256(envelope_body),
        },
    }


def _generator(open_database=None, *, fail_first=False):
    calls = []

    def generate(payload, contract, *, registered_model_contract_sha256, instructions):
        if open_database is not None:
            con = db.connect(open_database, read_only=True, wait_s=0)
            con.execute("SELECT COUNT(*) FROM p16_challenger_runs").fetchone()
            con.close()
        request = p16_model_client.request_payload(
            payload, contract, instructions=instructions)
        assessments = [{
            "ticker": row["ticker"], "p_outperform_5": 0.6,
            "expected_excess_bp_5": 40.0, "expected_excess_bp_10": 60.0,
            "action": "watch", "thesis": "Fixture challenger thesis.",
            "invalidation": "Fixture challenger invalidation.",
            "evidence_ids": [row["allowed_evidence_ids"][0]],
        } for row in payload["candidates"]]
        if fail_first and not calls:
            assessments.pop()
        response = {"id": f"response-{len(calls)}"}
        calls.append(payload)
        return {
            "output": {"schema_version": 1, "assessments": assessments},
            "request": request, "request_sha256": canonical_sha256(request),
            "response": response, "response_sha256": canonical_sha256(response),
            "model_contract_sha256": registered_model_contract_sha256,
            "execution_authority": "none",
        }

    return calls, generate


def test_three_sample_aggregation_and_ensemble_tie_rule():
    samples = []
    for score, action in ((10.0, "ignore"), (30.0, "watch"), (50.0, "buy_candidate")):
        samples.append({"AAA": {
            "ticker": "AAA", "p_outperform_5": score / 100,
            "expected_excess_bp_5": score, "expected_excess_bp_10": score + 10,
            "action": action, "thesis": action, "invalidation": "invalid",
            "evidence_ids": [f"{int(score):064x}"],
        }})
    aggregate = runner._aggregate(["AAA"], samples)[0]
    assert aggregate["expected_excess_bp_5"] == 30.0
    assert aggregate["action"] == "watch"

    snapshot = _snapshot()
    snapshot["champion"]["AAA"]["action"] = "ignore"
    components = []
    for score, action in ((40.0, "watch"), (100.0, "buy_candidate")):
        row = deepcopy(snapshot["champion"]["AAA"])
        row.update(expected_excess_bp_5=score, action=action)
        second = deepcopy(row)
        second["ticker"] = "BBB"
        components.append({"data": {"rows": [row, second]}})
    ensemble = runner._ensemble_rows(snapshot, components)[0]
    assert ensemble["expected_excess_bp_5"] == pytest.approx(160 / 3)
    assert ensemble["action"] == "watch"
    assert ensemble["thesis"] == "Champion thesis."


def test_blind_output_is_reversed_and_evidence_is_bounded():
    snapshot = _snapshot()
    member = next(row for row in _registration()["challengers"]["members"]
                  if row["policy_id"] == "c-blind")
    original = snapshot["chunks"][0]["samples"][0]["original"]
    treatment = runner._treatment(member, original, snapshot, NOW)
    treated = treatment["payload"]["candidates"]
    output = {"schema_version": 1, "assessments": [{
        "ticker": row["ticker"], "p_outperform_5": 0.5,
        "expected_excess_bp_5": 10.0, "expected_excess_bp_10": 20.0,
        "action": "watch", "thesis": "A bounded view.",
        "invalidation": "The supplied evidence changes.",
        "evidence_ids": [row["allowed_evidence_ids"][0]],
    } for row in treated]}
    assert set(runner._validate_output(output, treated, treatment)) == {"AAA", "BBB"}
    output["assessments"][0]["evidence_ids"] = ["0" * 64]
    with pytest.raises(runner.ChallengerRunError, match="evidence"):
        runner._validate_output(output, treated, treatment)


def test_source_snapshot_uses_only_the_completed_retained_p15_grid(tmp_path, monkeypatch):
    database = tmp_path / "source.duckdb"
    con = db.connect(database)
    con.execute("CREATE TABLE universe (ticker VARCHAR,active BOOLEAN,liquid BOOLEAN)")
    con.execute("CREATE TABLE prices (ticker VARCHAR,date DATE,open DOUBLE,high DOUBLE,"
                "low DOUBLE,close DOUBLE,volume DOUBLE)")
    con.execute("INSERT INTO universe VALUES ('AAA',TRUE,TRUE),('BBB',TRUE,TRUE)")
    con.execute("INSERT INTO prices VALUES "
                "('AAA',?,100,101,99,100,1000),('BBB',?,100,101,99,100,1000)",
                [MARKET_DATE, MARKET_DATE])
    candidates = [_candidate("AAA", "c" * 64), _candidate("BBB", "d" * 64)]
    universe = {"candidates": candidates, "bundle_sha256": "2" * 64}
    con.execute("CREATE TABLE p15_scoring_runs (id BIGINT,policy_id VARCHAR,market_date DATE,"
                "status VARCHAR,universe_payload VARCHAR,aggregate_trace_sha256 VARCHAR)")
    con.execute("INSERT INTO p15_scoring_runs VALUES (1,'p15-scoring-v1',?,'completed',?,?)",
                [MARKET_DATE, json.dumps(universe), "1" * 64])
    con.execute("CREATE TABLE p15_scoring_samples (run_id BIGINT,chunk_index INTEGER,"
                "sample_index INTEGER,request_payload VARCHAR,request_sha256 VARCHAR,"
                "status VARCHAR)")
    for sample in _snapshot()["chunks"][0]["samples"]:
        request = {"input": json.dumps(sample["original"], sort_keys=True)}
        con.execute("INSERT INTO p15_scoring_samples VALUES (1,0,?,?,?,'completed')", [
            sample["sample_index"], json.dumps(request), canonical_sha256(request)])
    champion = list(_snapshot()["champion"].values())
    output = {"schema_version": 1, "assessments": champion}
    con.execute("CREATE TABLE agent_evaluation_traces (id BIGINT,policy_id VARCHAR,"
                "market_date DATE,source_kind VARCHAR,source_identifier VARCHAR,"
                "terminal_status VARCHAR,output_payload VARCHAR,output_sha256 VARCHAR,"
                "trace_sha256 VARCHAR,observed_at TIMESTAMP)")
    con.execute("INSERT INTO agent_evaluation_traces VALUES "
                "(1,'p15-scoring-v1',?,'p15_scoring_run','1','completed',?,?,?,?)", [
                    MARKET_DATE, json.dumps(output), canonical_sha256(output), "1" * 64,
                    NOW.replace(tzinfo=None)])
    con.execute("CREATE TABLE agent_evaluation_decisions (id BIGINT,trace_id BIGINT,"
                "ticker VARCHAR,decision_sha256 VARCHAR,decision_payload VARCHAR)")
    con.execute("CREATE TABLE agent_evaluation_labels_v2 (id BIGINT,decision_id BIGINT,"
                "horizon_sessions INTEGER,label_basis VARCHAR,exit_date DATE,labeled_at TIMESTAMP,"
                "net_excess_return DOUBLE)")
    con.execute("CREATE TABLE universe_snapshot "
                "(snapshot_date DATE,ticker VARCHAR,name VARCHAR)")
    con.execute("INSERT INTO universe_snapshot VALUES "
                "(?,'AAA','AAA Incorporated'),(?,'BBB','BBB Incorporated')",
                [MARKET_DATE, MARKET_DATE])
    con.execute("CREATE TABLE fundamentals (ticker VARCHAR,as_of DATE,fetched_at TIMESTAMP,"
                "sector VARCHAR,source VARCHAR)")
    con.execute("INSERT INTO fundamentals VALUES "
                "('AAA',?,?,'Technology','fixture'),('BBB',?,?,'Industrials','fixture')", [
                    MARKET_DATE, datetime(2026, 9, 29, 19),
                    MARKET_DATE, datetime(2026, 9, 29, 19)])
    con.close()
    origin = {
        "source": {
            "run_id": 1, "trace_sha256": "1" * 64, "bundle_sha256": "2" * 64,
            "universe_sha256": "3" * 64, "context_sha256": "4" * 64,
        },
        "scoring_information_cutoff_at": "2026-09-29T20:00:00Z",
        "p15_registration_sha256": "f" * 64, "decision_rows": [],
    }
    monkeypatch.setattr(
        runner.p16_eval_inputs, "load_origin", lambda *_args, **_kwargs: origin)

    snapshot = runner._source_snapshot(database, MARKET_DATE, NOW)

    assert snapshot["tickers"] == ["AAA", "BBB"]
    assert len(snapshot["chunks"]) == 1 and len(snapshot["chunks"][0]["samples"]) == 3
    assert snapshot["metadata_envelope"]["entries"][1]["sector"] == "industrials"
    assert snapshot["source_identity"]["p15_run_trace_sha256"] == "1" * 64


def test_runner_closes_writer_during_calls_records_all_members_and_replays(
    tmp_path, monkeypatch,
):
    database = tmp_path / "market.duckdb"
    con = db.connect(database)
    con.close()
    snapshot, registration = _snapshot(), _registration()
    monkeypatch.setattr(runner, "_source_snapshot", lambda *_args, **_kwargs: snapshot)
    preentries = []

    def record_preentry(con, **kwargs):
        preentries.append(kwargs)
        assert con.execute(
            "SELECT COUNT(*) FROM p16_evaluation_artifacts "
            "WHERE artifact_kind='policy_scores'"
        ).fetchone() == (8,)
        return {"preentry_sha256": "9" * 64}

    monkeypatch.setattr(runner.p16_preentry, "record_preentry", record_preentry)
    calls, generate = _generator(database, fail_first=True)
    first = runner._run(
        database=database, registration=registration, now=NOW,
        generate=generate, clock=lambda: NOW, isolated=True,
    )
    second = runner._run(
        database=database, registration=registration, now=NOW,
        generate=generate, clock=lambda: NOW, isolated=True,
    )

    assert first["member_count"] == 8 and first["model_call_count"] == 21
    assert first["execution_authority"] == "none"
    assert second["model_call_count"] == 0
    assert len(calls) == 21 and len(preentries) == 2
    con = db.connect(database, read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM p16_challenger_outputs").fetchone() == (8,)
        assert con.execute("SELECT COUNT(*) FROM p16_challenger_attempts").fetchone() == (21,)
        blind = con.execute(
            "SELECT o.payload FROM p16_challenger_outputs o "
            "JOIN p16_challenger_runs r ON r.record_id=json_extract_string(o.payload,'$.key.run_id') "
            "WHERE json_extract_string(r.payload,'$.key.policy_id')='c-blind'"
        ).fetchone()[0]
        assert json.loads(blind)["data"]["unavailable_count"] == 2
        assert con.execute(
            "SELECT COUNT(*) FROM p16_challenger_receipts "
            "WHERE json_extract_string(payload,'$.data.status')='unavailable'"
        ).fetchone() == (1,)
        ensemble = con.execute(
            "SELECT o.payload FROM p16_challenger_outputs o "
            "JOIN p16_challenger_runs r ON r.record_id=json_extract_string(o.payload,'$.key.run_id') "
            "WHERE json_extract_string(r.payload,'$.key.policy_id')='c-ensemble'"
        ).fetchone()[0]
        assert len(json.loads(ensemble)["data"]["dependency_output_ids"]) == 2
    finally:
        con.close()


def test_interrupted_memory_attempt_reuses_retained_timestamped_request(tmp_path):
    database = tmp_path / "market.duckdb"
    con = db.connect(database)
    con.close()
    snapshot, registration = _snapshot(), _registration()
    member = next(row for row in registration["challengers"]["members"]
                  if row["policy_id"] == "c-memory")
    contract = next(row for row in registration["model_contracts"]
                    if row["model_contract_sha256"] == member["model_contract_sha256"])
    run = runner._start_member_run(database, registration, member, snapshot, NOW)
    sample = snapshot["chunks"][0]["samples"][0]
    treatment = runner._treatment(member, sample["original"], snapshot, NOW)
    request = p16_model_client.request_payload(
        treatment["payload"], contract, instructions=p16_model_client.prompt())
    con = db.connect(database)
    try:
        with db.transaction(con):
            runner.p16_challenger_store.start_attempt(
                con, run["record_id"], chunk_index=0, sample_index=0,
                request_payload=request, treatment=treatment, started_at=NOW)
    finally:
        con.close()
    later = datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc)
    calls, generate = _generator()

    output, call_count = runner._run_member(
        database, registration, member, contract, snapshot, later,
        generate=generate, clock=lambda: later, instructions=p16_model_client.prompt())

    assert call_count == 2 and len(calls) == 2
    assert output["data"]["unavailable_count"] == 2
    con = db.connect(database, read_only=True)
    try:
        retained = con.execute(
            "SELECT payload FROM p16_challenger_receipts "
            "WHERE json_extract_string(payload,'$.data.reason') "
            "LIKE 'interrupted before durable%'"
        ).fetchone()
        assert retained is not None
    finally:
        con.close()


def test_model_call_is_not_started_after_deadline_crossing(tmp_path):
    database = tmp_path / "market.duckdb"
    con = db.connect(database)
    con.close()
    snapshot, registration = _snapshot(), _registration()
    member = next(row for row in registration["challengers"]["members"]
                  if row["policy_id"] == "c-prompt-v2")
    contract = next(row for row in registration["model_contracts"]
                    if row["model_contract_sha256"] == member["model_contract_sha256"])
    after_open = runner._next_open(MARKET_DATE)
    values = iter([NOW, after_open])

    def clock():
        return next(values, after_open)

    def must_not_generate(*_args, **_kwargs):
        raise AssertionError("model call crossed the next-open deadline")

    output, call_count = runner._run_member(
        database, registration, member, contract, snapshot, NOW,
        generate=must_not_generate, clock=clock, instructions=p16_model_client.prompt())

    assert call_count == 0
    assert output["data"]["unavailable_count"] == 2


def test_completed_preentry_identity_is_recognized_only_as_the_full_family(tmp_path):
    database = tmp_path / "market.duckdb"
    registration = _registration()
    con = db.connect(database)
    try:
        with db.transaction(con):
            runner._ensure_trials(con, registration)
            for member in registration["challengers"]["members"]:
                body = {
                    "policy_id": member["comparison_id"],
                    "market_date": MARKET_DATE.isoformat(),
                    "information_cutoff_at": "2026-09-29T20:00:00+00:00",
                    "scores": {"AAA": 1.0},
                }
                payload = {**body, "score_snapshot_sha256": canonical_sha256(body)}
                artifact = runner.p16_store.record_policy_scores(
                    con, registration_sha256=registration["registration_sha256"],
                    payload=payload, recorded_at=NOW)
                runner.p16_store.record_origin_decision(
                    con, registration_sha256=registration["registration_sha256"],
                    family_id="p16-challengers-f1",
                    comparison_id=member["comparison_id"], trial_id=member["trial_id"],
                    control_trial_id=member["control_trial_id"],
                    epoch_session=MARKET_DATE, session_index=0, market_date=MARKET_DATE,
                    status="eligible", reason=None, decided_at=NOW,
                    forward_entry_at=runner._next_open(MARKET_DATE),
                    source_artifact_sha256=artifact, recorded_at=NOW,
                )
        assert runner._existing_preentry(con, registration, MARKET_DATE) is True
        con.execute("DELETE FROM p16_sequential_origin_events WHERE comparison_id='c-blind'")
        with pytest.raises(runner.ChallengerRunError, match="partially retained"):
            runner._existing_preentry(con, registration, MARKET_DATE)
    finally:
        con.close()


def test_preentry_transaction_rolls_back_if_open_arrives_before_commit(
    tmp_path, monkeypatch,
):
    database = tmp_path / "market.duckdb"
    con = db.connect(database)
    con.close()
    snapshot, registration = _snapshot(), _registration()
    monkeypatch.setattr(runner, "_source_snapshot", lambda *_args, **_kwargs: snapshot)
    state = {"crossed": False}

    def clock():
        return runner._next_open(MARKET_DATE) if state["crossed"] else NOW

    def record_preentry(_con, **_kwargs):
        state["crossed"] = True
        return {"preentry_sha256": "9" * 64}

    monkeypatch.setattr(runner.p16_preentry, "record_preentry", record_preentry)
    _calls, generate = _generator()

    with pytest.raises(runner.ChallengerRunError, match="crossed the next-open"):
        runner._run(
            database=database, registration=registration, now=NOW,
            generate=generate, clock=clock, isolated=True)

    con = db.connect(database, read_only=True)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM p16_evaluation_artifacts"
        ).fetchone() == (0,)
        assert con.execute("SELECT COUNT(*) FROM p16_challenger_outputs").fetchone() == (8,)
    finally:
        con.close()


def test_live_run_refuses_inactive_registration_before_reading_source(tmp_path):
    with pytest.raises(runner.ChallengerRunError, match="not active"):
        runner._run(
            database=tmp_path / "absent.duckdb",
            registration=_registration(status="registered_inactive"),
            now=NOW,
        )


def test_copied_store_dry_run_never_mutates_source(tmp_path, monkeypatch):
    source = tmp_path / "source.duckdb"
    con = db.connect(source)
    con.execute("CREATE TABLE sentinel (value INTEGER)")
    con.execute("INSERT INTO sentinel VALUES (7)")
    con.close()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    registration = _registration(status="registered_inactive")
    registration_path = tmp_path / "registration.json"
    registration_path.write_text(json.dumps(registration, sort_keys=True))
    snapshot = _snapshot()
    monkeypatch.setattr(runner, "_source_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(
        runner.p16_preentry, "record_preentry",
        lambda _con, **_kwargs: {"preentry_sha256": "9" * 64},
    )
    _calls, generate = _generator()

    result = runner.dry_run(
        database=source, registration_path=registration_path, now=NOW,
        generate=generate, clock=lambda: NOW,
        copier=lambda src, dst: shutil.copy2(src, dst),
    )

    assert result["status"] == "completed" and result["dry_run"] is True
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    con = db.connect(source, read_only=True)
    try:
        assert con.execute("SELECT * FROM sentinel").fetchall() == [(7,)]
        assert not table_exists(con, "p16_challenger_runs")
    finally:
        con.close()
