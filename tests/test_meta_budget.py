"""`_meta.json` stays a summary: per-ticker detail lives in data/reports/producer-detail/.

Before the split, the weekly verifier's `name_results` (~1.5 MB) and the intraday
archiver's `coverage` (~0.9 MB) made `_meta.json` 3.9 MB, rewritten and pushed on
every data commit. This drives both producers' real publishing paths at production
scale (4,062 weekly names, 174 nightly names, 928 intraday tickers) and holds the
resulting `_meta.json` to a byte budget and to bounded containers.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone

from engine import intraday, verify_prices

META_BUDGET_BYTES = 256 * 1024
# No list or object in `_meta.json` may be sized by the universe. Today's largest
# bounded ones are weekly disagreement rows (73) and not-checked names (19).
MAX_CONTAINER_ENTRIES = 500
NOW = datetime(2026, 10, 22, 1, tzinfo=timezone.utc)


def _name_result(index: int) -> dict:
    ticker = f"T{index:04d}"
    worst = {"ticker": ticker, "date": "2026-10-12", "field": "high",
             "store": 779.400024, "source": 779.397, "diff_bp": 0.04}
    return {"ticker": ticker, "sessions_compared": 5, "bars_compared": 5,
            "fields_compared": 17, "disagreements": [], "worst": worst,
            "store_missing": [], "newest_in_store": True, "newest_compared": True,
            "source_latest_session": "2026-10-16", "status": "agrees", "why": "liquid"}


def _accounting(names: int) -> dict:
    disagreements = [{"ticker": f"T{i:04d}", "date": "2026-10-14", "field": "low",
                      "store": 52.9, "source": 53.9, "diff_bp": 189.0} for i in range(73)]
    return {
        "last_run": NOW.isoformat(), "as_of": "2026-10-16", "names_selected": names,
        "names_checked": names, "names_agreeing": names, "names_disagreeing": 0,
        "names_not_checked": 0, "not_checked_reasons": {},
        "not_checked_names": [{"ticker": f"N{i}", "why": "sample", "reason": "fetch_failed",
                               "detail": "x" * 120} for i in range(19)],
        "disagreements": disagreements, "n_disagreements": len(disagreements),
        "name_results": [_name_result(i) for i in range(names)],
        "newest_session": {"session": "2026-10-16", "status": "checked"},
        "source_evidence": {"T0000": [{"body_base64": "Ym9keQ==", "body_sha256": "x"}]},
        "store_evidence": {"T0000": {"2026-10-16": {"close": 10.0}}},
    }


def _coverage(tickers: int) -> dict:
    def item(sessions: int) -> dict:
        days = {(NOW.date() - timedelta(days=d)).isoformat(): 390 for d in range(1, sessions + 1)}
        return {"through": "2026-10-21T00:00:00", "days": days}
    return {"1m": {f"T{i:04d}": item(6) for i in range(tickers)},
            "5m": {f"T{i:04d}": item(42) for i in range(tickers)}}


def _containers(value, path="$"):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _containers(child, f"{path}.{key}")
    elif isinstance(value, list):
        yield path, value
        for index, child in enumerate(value):
            yield from _containers(child, f"{path}[{index}]")


def test_meta_stays_a_summary_at_production_scale(monkeypatch, tmp_path):
    meta = tmp_path / "data" / "_meta.json"
    meta.parent.mkdir()
    accountings = {verify_prices.FULL_META_KEY: _accounting(4062),
                   verify_prices.META_KEY: _accounting(174)}
    for key, acc in accountings.items():
        monkeypatch.setattr(verify_prices, "run_connection_narrowed", lambda *_a, _acc=acc, **_k: _acc)
        monkeypatch.setattr(sys, "argv", ["verify_prices", "--meta", str(meta), "--meta-key", key])
        assert verify_prices.main() == 0
    coverage = _coverage(928)
    monkeypatch.setattr(intraday.rsc, "live_store_gb", lambda _path: 37.31)
    monkeypatch.setattr(intraday.rsc, "snapshots_gb", lambda _path: 0.0)
    intraday._pull_batches({}, lambda _frame: 0, meta, coverage, NOW)

    raw = meta.read_bytes()
    payload = json.loads(raw)
    detail = sum(len((meta.parent / path).read_bytes()) for path in (
        *verify_prices.DETAIL_REPORTS.values(), intraday.COVERAGE_REPORT))
    # The fixture is large enough that keeping the detail inline breaks the budget.
    assert detail > 4 * META_BUDGET_BYTES
    assert len(raw) <= META_BUDGET_BYTES, f"_meta.json is {len(raw)} bytes"
    oversized = {path: len(value) for path, value in _containers(payload)
                 if len(value) > MAX_CONTAINER_ENTRIES}
    assert oversized == {}, f"per-ticker containers in _meta.json: {oversized}"
    for key in accountings:
        assert "name_results" not in payload[key]
    assert "coverage" not in payload["intraday"]

    # Nothing is lost: each pointer names a report holding the complete detail.
    for key, acc in accountings.items():
        pointer = payload[key]["name_results_report"]
        report = json.loads((meta.parent / pointer["path"]).read_text())
        assert report["name_results"] == acc["name_results"]
        assert pointer["names"] == len(acc["name_results"])
        assert report["evidence_receipt"] == payload[key]["evidence_receipt"]["sha256"]
        assert (report["last_run"], report["as_of"]) == (acc["last_run"], acc["as_of"])
    pointer = payload["intraday"]["coverage_report"]
    assert pointer == {"path": intraday.COVERAGE_REPORT, "tickers": {"1m": 928, "5m": 928}}
    assert json.loads((meta.parent / pointer["path"]).read_text()) == {"coverage": coverage}
    assert intraday._saved_coverage(meta) == coverage


def test_receipt_still_holds_the_complete_accounting(monkeypatch, tmp_path):
    """The immutable receipt is unchanged by the split: it keeps every named result."""
    meta = tmp_path / "data" / "_meta.json"
    meta.parent.mkdir()
    acc = _accounting(3)
    monkeypatch.setattr(verify_prices, "run_connection_narrowed", lambda *_a, **_k: acc)
    monkeypatch.setattr(sys, "argv", ["verify_prices", "--meta", str(meta)])
    assert verify_prices.main() == 0
    summary = json.loads(meta.read_text())[verify_prices.META_KEY]
    receipt = json.loads((meta.parent / summary["evidence_receipt"]["path"]).read_text())
    assert receipt == acc
    assert summary["as_of"] == date(2026, 10, 16).isoformat()
