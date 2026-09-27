import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from engine.p16_challenger_inputs import ablate, blind, memory_examples


def _payload():
    market = {
        "market_date": "2026-09-29", "spy_close": 500.0, "spy_daily_return": 0.01,
        "regime": "risk_on", "evidence_id": "a" * 64,
    }
    candidate = {
        "ticker": "ACME", "company_name": "Acme Corporation", "sector": "Technology",
        "close": 123.4, "daily_return": 0.05, "relative_volume_20d": 2.0,
        "baseline_score": 50, "standout_score": 12.0, "stratum": "mover", "held": False,
        "tradeable": True, "reason": "eligible", "evidence_id": "b" * 64,
        "earnings": {
            "status": "available", "next_date": "2026-10-28", "is_estimate": False,
        },
        "headlines": [{
            "title": "ACME: acme corporation raises its outlook",
            "evidence_id": "c" * 64, "url": "https://example.org/acme/results",
        }],
        "allowed_evidence_ids": ["a" * 64, "b" * 64, "c" * 64],
    }
    return {
        "schema_version": 1, "policy_id": "p15-scoring-v1",
        "market_date": "2026-09-29",
        "information_cutoff_at": "2026-09-29T21:00:00+00:00",
        "chunk_index": 0, "sample_index": 0, "permutation_seed": 42,
        "market": market, "market_headlines": [], "event_facts": [],
        "tradingview_quotes": [], "candidates": [candidate],
    }


def _aliases():
    return {
        "available_at": "2026-09-29T20:00:00+00:00",
        "names": {"ACME": ["ACME", "Acme Corporation", "Acme"]},
    }


def test_blinding_is_stable_removes_names_and_preserves_numbers_and_sector():
    original, aliases = _payload(), _aliases()
    saved = deepcopy(original)
    first = blind(original, aliases, decision_at="2026-09-29T22:00:00+00:00")
    second = blind(original, aliases, decision_at="2026-09-29T22:01:00+00:00")
    assert first == second and original == saved
    payload = first["payload"]
    assert "acme" not in json.dumps(payload).casefold()
    assert payload["candidates"][0]["ticker"] == first["asset_ids"]["ACME"]
    for key in ("close", "daily_return", "relative_volume_20d", "baseline_score", "sector"):
        assert payload["candidates"][0][key] == original["candidates"][0][key]
    assert "asset_ids" not in payload and "issuer_ids" not in payload
    original["market_date"] = "2026-09-30"
    changed = blind(original, aliases, decision_at="2026-09-30T22:00:00+00:00")
    assert changed["asset_ids"] != first["asset_ids"]


def test_share_classes_keep_distinct_assets_and_common_anonymous_issuer():
    payload, aliases = _payload(), _aliases()
    second = deepcopy(payload["candidates"][0])
    second["ticker"] = "ACMB"
    payload["candidates"].append(second)
    aliases["names"]["ACMB"] = ["ACMB", "Acme Corporation", "Acme"]
    result = blind(payload, aliases, decision_at="2026-09-29T22:00:00+00:00")
    assert result["asset_ids"]["ACME"] != result["asset_ids"]["ACMB"]
    assert result["issuer_ids"]["ACME"] == result["issuer_ids"]["ACMB"]


def test_blinding_removes_case_insensitive_symbol_from_nested_text():
    payload = _payload()
    payload["candidates"][0]["headlines"][0]["title"] = "acme announces results"
    result = blind(payload, _aliases(), decision_at="2026-09-29T22:00:00+00:00")
    assert "acme" not in json.dumps(result["payload"]).casefold()


def test_missing_or_future_aliases_cannot_claim_blinding():
    aliases = _aliases()
    aliases["available_at"] = "2026-09-30T20:00:00+00:00"
    with pytest.raises(ValueError, match="unavailable"):
        blind(_payload(), aliases, decision_at="2026-09-29T22:00:00+00:00")
    aliases["available_at"] = "2026-09-29T20:00:00+00:00"
    aliases["names"] = {}
    with pytest.raises(ValueError, match="incomplete"):
        blind(_payload(), aliases, decision_at="2026-09-29T22:00:00+00:00")


def test_price_only_removes_text_and_hidden_text_citations():
    original = _payload()
    result = ablate(original, "price_only")["payload"]
    row = result["candidates"][0]
    assert "headlines" not in row and "company_name" not in row
    assert "market_headlines" not in result and result["event_facts"] == []
    assert row["close"] == original["candidates"][0]["close"]
    assert row["allowed_evidence_ids"] == ["a" * 64, "b" * 64]


def test_text_only_removes_price_derived_ranks_and_market_regime():
    result = ablate(_payload(), "text_only")["payload"]
    row = result["candidates"][0]
    assert "market" not in result
    assert not {
        "close", "daily_return", "relative_volume_20d", "standout_score", "baseline_score",
        "stratum", "held", "tradeable", "reason",
    }.intersection(row)
    assert row["sector"] == "Technology" and row["headlines"]
    assert row["earnings"]["next_date"] == "2026-10-28"
    assert row["allowed_evidence_ids"] == ["b" * 64, "c" * 64]


def test_intraday_mover_facts_are_price_evidence_only():
    original = _payload()
    mover = {
        "ticker": "ACME", "fact_type": "p15.event.intraday_mover",
        "evidence_id": "d" * 64,
        "payload": {"session_return": 0.1, "relative_volume": 3.0},
    }
    news = {
        "ticker": "ACME", "fact_type": "news.headline", "evidence_id": "e" * 64,
        "payload": {"title": "ACME wins a contract"},
    }
    original["event_facts"] = [mover, news]
    original["candidates"][0]["allowed_evidence_ids"].extend(["d" * 64, "e" * 64])
    price = ablate(original, "price_only")["payload"]
    text = ablate(original, "text_only")["payload"]
    assert price["event_facts"] == [mover] and text["event_facts"] == [news]
    assert "d" * 64 in price["candidates"][0]["allowed_evidence_ids"]
    assert "d" * 64 not in text["candidates"][0]["allowed_evidence_ids"]


def _history(count=25):
    first = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return [{
        "decision_id": f"d{index:02}", "policy_sha256": "a" * 64,
        "horizon_sessions": 5, "evidence_class": "prospective_forward",
        "decision_at": (first + timedelta(days=index)).isoformat(),
        "label_mature_at": (first + timedelta(days=index + 8)).isoformat(),
        "label_available_at": (first + timedelta(days=index + 9)).isoformat(),
        "standout_score": float(index), "stratum": "mover", "sector": "Technology",
        "net_excess_return": (-1) ** index * 0.05, "thesis": "Fixture thesis.",
    } for index in range(count)]


def _memory(history):
    return memory_examples(
        _payload()["candidates"], history, champion_policy_sha256="a" * 64,
        decision_at="2026-09-29T22:00:00+00:00",
    )


def test_memory_selection_is_bounded_and_independent_of_outcomes():
    history = _history()
    first = _memory(history)
    assert first["eligible_count"] == 25 and len(first["examples"]) == 20
    assert first["examples"][0]["decision_id"] == "d12"
    for row in history:
        row["net_excess_return"] = 100.0
    second = _memory(history)
    assert [row["decision_id"] for row in first["examples"]] == [
        row["decision_id"] for row in second["examples"]
    ]


@pytest.mark.parametrize("field,value", [
    ("policy_sha256", "b" * 64), ("horizon_sessions", 10),
    ("evidence_class", "historical_replay"),
    ("label_mature_at", "2026-09-29T22:00:00+00:00"),
    ("label_available_at", "2026-09-29T22:00:00+00:00"),
])
def test_memory_excludes_wrong_policy_replay_and_not_yet_known_labels(field, value):
    history = _history(1)
    history[0][field] = value
    assert _memory(history)["examples"] == []


def test_memory_matches_stratum_then_sector_before_numeric_distance():
    history = _history(3)
    history[0].update(stratum="trend", standout_score=12.0)
    history[1].update(sector="Energy", standout_score=12.0)
    history[2].update(standout_score=100.0)
    assert [row["decision_id"] for row in _memory(history)["examples"]] == [
        "d02", "d01", "d00",
    ]


def test_treatment_hashes_bind_original_payload_and_transformed_payload():
    treatment = ablate(_payload(), "text_only")
    assert treatment["original_sha256"] == canonical_sha256(_payload())
    assert treatment["payload_sha256"] == canonical_sha256(treatment["payload"])
    assert treatment["treatment_sha256"] == canonical_sha256({
        key: value for key, value in treatment.items() if key != "treatment_sha256"
    })
