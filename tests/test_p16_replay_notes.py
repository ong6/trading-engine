"""W4 notes-filter acceptance and frozen-corpus tests."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from farm.replay.notes import (
    MAX_LESSON_REJECTION_RATE,
    MIN_LESSON_COUNT,
    NotesValidationError,
    freeze_filter_spec,
    lesson_rejection_rate,
    validate_lesson_corpus,
    validate_notes,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "p16_replay_lessons.json"
FILTER = freeze_filter_spec(
    tickers=("A", "ON", "IT", "BRK.B"),
    company_names=("Acme Holdings",),
    aliases=("Acme Group", "May"),
)
@pytest.mark.parametrize(
    "text",
    (
        "This may not generalize.",
        "A single headline rarely changes the thesis.",
        "Risk changed. A single headline rarely changes the thesis.",
        "The first signal needs corroboration.",
        "One signal is insufficient.",
        "The second signal conflicts.",
        "Second, seek contrary evidence.",
        "Results may improve.",
        "Rely on the first draft.",
        "After the first signal, wait.",
        "In the first pass, review assumptions.",
        "Use a per-share basis.",
        "Prefer ranges to point forecasts.",
    ),
)
def test_notes_filter_accepts_plain_prose_and_sentence_initial_ticker(text):
    assert validate_notes(text, filter_spec=FILTER) == text


@pytest.mark.parametrize(
    "text",
    (
        "Use A check.",
        "$A may improve.",
        "Wait one day.",
        "Review on May second.",
        "Compare Acme Holdings carefully.",
        "Inspect BRK-B after the release.",
        "The return was 4 percent.",
    ),
)
def test_notes_filter_rejects_identity_date_and_value_anchors(text):
    with pytest.raises(NotesValidationError):
        validate_notes(text, filter_spec=FILTER)


def test_independently_authored_corpus_is_frozen_before_bound_and_passes():
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["schema_version"] == 2
    result = validate_lesson_corpus(
        fixture["lessons"],
        filter_spec=FILTER,
    )
    assert result.count == 120
    assert result.rejected <= 12
    assert result.rejection_rate <= Decimal("0.10")


def test_registered_corpus_cannot_relax_count_or_digest():
    fixture = json.loads(FIXTURE.read_text())
    common = dict(filter_spec=FILTER)
    assert MIN_LESSON_COUNT == 100
    assert MAX_LESSON_REJECTION_RATE == Decimal("0.10")
    with pytest.raises(NotesValidationError, match="count_mismatch"):
        validate_lesson_corpus(fixture["lessons"][:-1], **common)
    with pytest.raises(NotesValidationError, match="digest_mismatch"):
        validate_lesson_corpus([*fixture["lessons"][:-1], "Changed principle."], **common)


def test_exact_ten_percent_rejection_passes_and_eleven_percent_fails():
    assert lesson_rejection_rate(10, 100) == MAX_LESSON_REJECTION_RATE
    assert lesson_rejection_rate(11, 100) > MAX_LESSON_REJECTION_RATE
    with pytest.raises(NotesValidationError, match="too_small"):
        lesson_rejection_rate(0, 99)


@pytest.mark.parametrize(
    "text",
    (
        "“A single headline rarely changes the thesis.”",
        "(A single headline rarely changes the thesis.)",
        "He said “Risk changed.” A single headline rarely changes the thesis.",
        "— A single headline rarely changes the thesis.",
    ),
)
def test_opening_punctuation_preserves_sentence_initial_one_letter_exception(text):
    assert validate_notes(text, filter_spec=FILTER) == text


@pytest.mark.parametrize(
    "text",
    (
        "The first quarter was noisy.",
        "May earnings were weak.",
        "Review on May second.",
        "Wait one session.",
    ),
)
def test_calendar_and_period_anchors_are_rejected(text):
    with pytest.raises(NotesValidationError, match="date_or_number"):
        validate_notes(text, filter_spec=FILTER)
