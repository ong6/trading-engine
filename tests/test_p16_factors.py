from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from engine.lib.provenance import canonical_sha256
from engine.p16_features import EXPOSURES
from farm.p16_factors import CHAMPION, evaluate_origin, mean_neutral_ic
from sim import nyse


def _fixtures(count=25):
    rows, exposures = [], []
    for index in range(count):
        ticker = f"T{index:02d}"
        base = float(index // 2)
        residual = (-1 if index % 2 == 0 else 1) * (base + 1)
        outcome = 3 * base + residual
        rows.append({"ticker": ticker, "net_excess_return": outcome,
                     "champion_score": outcome if index != 0 else None,
                     "rule_score": -float(index)})
        exposures.append({"ticker": ticker, "status": "available",
                          "missing_exposures": [], "sector": "technology",
                          "exposures": dict.fromkeys(EXPOSURES, base)})
    origin = {
        "status": "available", "market_date": "2026-09-22",
        "report_cutoff": "2026-10-01T00:00:00Z",
        "scoring_information_cutoff_at": "2026-09-22T20:00:00Z",
        "input_snapshot_sha256": "a" * 64,
        "source": {"trace_sha256": "b" * 64, "universe_sha256": "c" * 64},
        "rows": rows,
    }
    origin["input_snapshot_sha256"] = canonical_sha256({
        key: value for key, value in origin.items() if key != "input_snapshot_sha256"
    })
    body = {"market_date": origin["market_date"],
            "information_cutoff_at": origin["scoring_information_cutoff_at"],
            "exposure_names": list(EXPOSURES), "candidates": exposures}
    body["information_cutoff_at"] = "2026-09-22T20:00:00+00:00"
    snapshot = {**body, "snapshot_sha256": canonical_sha256(body)}
    return origin, snapshot


def test_factor_fit_keeps_unscored_names_and_uses_one_common_pair_mask():
    origin, exposures = _fixtures()
    challenger = {f"T{index:02d}": float(index) if index >= 5 else None
                  for index in range(25)}
    challenger_identity = {
        "policy_id": "challenger", "market_date": origin["market_date"],
        "information_cutoff_at": origin["scoring_information_cutoff_at"],
        "scores": challenger,
    }

    result = evaluate_origin(origin, exposures, challenger_scores={
        "challenger": {"scores": challenger,
                       "score_snapshot_sha256": canonical_sha256(challenger_identity)},
    })

    assert result["factor_fit"]["fit_count"] == 25
    assert result["comparisons"][CHAMPION]["full_sample_raw"]["pair_count"] == 24
    comparison = result["comparisons"]["challenger"]
    assert comparison["factor_common_raw"]["pair_count"] == 20
    assert comparison["factor_neutral"]["pair_count"] == 20
    assert result["factor_report_sha256"] == canonical_sha256({
        key: value for key, value in result.items() if key != "factor_report_sha256"
    })


def test_missing_exposure_is_counted_without_changing_full_sample_raw_ic():
    origin, exposures = _fixtures()
    exposures["candidates"][0].update(
        status="unavailable", missing_exposures=["momentum_12_1"],
        exposures=dict.fromkeys(EXPOSURES),
    )
    exposures["snapshot_sha256"] = canonical_sha256({
        key: value for key, value in exposures.items() if key != "snapshot_sha256"
    })

    result = evaluate_origin(origin, exposures)

    comparison = result["comparisons"][CHAMPION]
    assert result["exposure_exclusions"] == {"T00": ["momentum_12_1"]}
    assert comparison["full_sample_raw"]["pair_count"] == 24
    assert comparison["factor_common_raw"]["pair_count"] == 24


def test_pending_origin_cannot_reach_factor_fit():
    origin = {
        "status": "pending", "market_date": "2026-09-22",
        "report_cutoff": "2026-10-01T00:00:00Z",
        "unresolved_h5_tickers": ["AAA"],
    }
    origin["input_snapshot_sha256"] = canonical_sha256(origin)
    result = evaluate_origin(origin, {})
    assert result["status"] == "pending"
    assert "factor_fit" not in result

    origin["input_snapshot_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="origin identity"):
        evaluate_origin(origin, {})


def test_challenger_score_snapshot_is_bound_to_values_and_cutoff():
    origin, exposures = _fixtures()
    scores = {row["ticker"]: row["champion_score"] for row in origin["rows"]}
    identity = {"policy_id": "challenger", "market_date": origin["market_date"],
                "information_cutoff_at": origin["scoring_information_cutoff_at"],
                "scores": scores}
    digest = canonical_sha256(identity)
    scores["T24"] = -99.0

    with pytest.raises(ValueError, match="snapshot is incomplete"):
        evaluate_origin(origin, exposures, challenger_scores={
            "challenger": {"scores": scores,
                           "score_snapshot_sha256": digest},
        })


def test_mean_neutral_ic_uses_equal_sessions_and_twenty_session_floor():
    reports = []
    day, sessions = date(2026, 9, 1), []
    while len(sessions) < 20:
        if nyse.is_session(day):
            sessions.append(day)
        day += timedelta(days=1)
    for index, session in enumerate(sessions, 1):
        body = {"market_date": session.isoformat(),
                "report_cutoff": datetime.combine(
                    session, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
                "comparisons": {
            "challenger": {"factor_neutral": {
                "status": "scored", "challenger_ic": index / 100,
            }},
        }}
        reports.append({**body, "factor_report_sha256": canonical_sha256(body)})
    result = mean_neutral_ic(
        list(reversed(reports)), "challenger", activation_date=date(2026, 9, 1),
        report_cutoff=datetime.combine(
            sessions[-1], datetime.max.time(), tzinfo=timezone.utc),
    )
    assert result["status"] == "available"
    assert result["valid_session_count"] == 20
    assert result["mean_neutral_ic"] == np.mean(np.arange(1, 21) / 100)
    assert result["first_valid_date"] == sessions[0].isoformat()
    assert result["last_valid_date"] == sessions[-1].isoformat()
    assert result["aggregate_sha256"] == canonical_sha256({
        key: value for key, value in result.items() if key != "aggregate_sha256"
    })
    reports[-1]["comparisons"] = {}
    reports[-1]["factor_report_sha256"] = canonical_sha256({
        key: value for key, value in reports[-1].items() if key != "factor_report_sha256"
    })
    assert mean_neutral_ic(
        reports, "challenger", activation_date=date(2026, 9, 1),
        report_cutoff=datetime.combine(
            sessions[-1], datetime.max.time(), tzinfo=timezone.utc),
    )["status"] == "insufficient"


def test_mean_neutral_ic_excludes_reports_created_after_cutoff():
    reports = []
    day = date(2026, 9, 1)
    while len(reports) < 20:
        if nyse.is_session(day):
            body = {"market_date": day.isoformat(), "report_cutoff": "2099-01-01T00:00:00Z",
                    "comparisons": {"challenger": {"factor_neutral": {
                        "status": "scored", "challenger_ic": 0.5}}}}
            reports.append({**body, "factor_report_sha256": canonical_sha256(body)})
        day += timedelta(days=1)
    result = mean_neutral_ic(
        reports, "challenger", activation_date=date(2026, 9, 1),
        report_cutoff=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    assert result["status"] == "insufficient" and result["valid_session_count"] == 0


def test_mean_neutral_ic_uses_new_york_cutoff_date():
    result = mean_neutral_ic(
        [], CHAMPION, activation_date=date(2026, 9, 28),
        report_cutoff=datetime(2026, 9, 28, 0, 30, tzinfo=timezone.utc),
    )
    assert result["scheduled_session_count"] == 0
