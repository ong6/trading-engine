"""Reduced W4 text-lab contracts without torch or real SEC requests."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from farm.textlab.corpus import (
    build_corpus_inventory,
    first_open_strictly_after,
    label_clock,
)
from farm.textlab.report import render_textlab_report
from farm.textlab.ridge import (
    checkpoint_for_year,
    inference_readiness,
    issuer_in_reduced_sample,
    ridge_predict,
    training_indices,
)


def test_acceptance_enters_first_open_strictly_after_and_uses_early_close():
    preopen = datetime(2024, 11, 29, 8, tzinfo=ZoneInfo("America/New_York"))
    at_open = preopen.replace(hour=9, minute=30)
    assert first_open_strictly_after(preopen).isoformat() == "2024-11-29T14:30:00+00:00"
    assert first_open_strictly_after(at_open).isoformat() == "2024-12-02T14:30:00+00:00"
    assert label_clock(datetime(2024, 11, 29).date(), 1).isoformat() == (
        "2024-11-29T18:15:00+00:00"
    )


def test_inventory_keeps_full_year_grid_before_labels_and_deduplicates_accession():
    rows = [{
        "form": "8-K",
        "items": "2.02,9.01",
        "accession": "a1",
        "cik": "1",
        "accepted_at": "2015-01-02T13:00:00Z",
        "language": "en",
        "content_sha256": "a" * 64,
    }]
    inventory = build_corpus_inventory([*rows, *rows, {**rows[0], "items": "1.01"}])
    assert len(inventory["records"]) == 1
    assert inventory["year_counts"]["2015"] == 1
    assert set(inventory["year_counts"]) == {str(year) for year in range(2015, 2026)}


def test_reduced_sample_and_checkpoint_schedule_are_fixed():
    decisions = [issuer_in_reduced_sample(str(cik)) for cik in range(100)]
    assert 10 < sum(decisions) < 40
    assert checkpoint_for_year(2015) == "chrono-bert-2014"
    assert checkpoint_for_year(2025) == "chrono-bert-2023"
    with pytest.raises(ValueError, match="outside"):
        checkpoint_for_year(2014)


def test_ridge_scaling_is_train_only_and_labels_are_strictly_visible():
    prediction = ridge_predict([[-1], [1]], [-2, 2], [[2]], 1)
    assert prediction.tolist() == [2]
    assert ridge_predict([[-1], [1]], [-2, 2], [[2], [999999]], 1)[0] == prediction[0]
    rows = [{
        "accepted_at": "2020-01-01T12:00:00Z",
        "label_visible_at": "2020-01-10T12:00:00Z",
        "checkpoint": "chrono-bert-2017",
        "label_status": "terminal",
    }]
    assert training_indices(
        rows,
        fit_at=datetime(2020, 1, 10, 12, tzinfo=timezone.utc),
        checkpoint="chrono-bert-2017",
    ) == []
    assert training_indices(
        rows,
        fit_at=datetime(2020, 1, 10, 12, 0, 1, tzinfo=timezone.utc),
        checkpoint="chrono-bert-2017",
    ) == [0]


def test_unapproved_dependency_produces_explicit_reduced_report():
    readiness = inference_readiness()
    report = render_textlab_report(
        {"year_counts": {"2015": 2, "2025": 3}}, readiness
    )
    assert readiness["status"] == "inference_unconfigured"
    assert "2015: 2" in report and "2025: 3" in report
    assert "look-ahead control: unavailable" in report
