"""W4 notes-filter acceptance and frozen-corpus tests."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from farm.replay.notes import (
    MAX_LESSON_REJECTION_RATE,
    MIN_LESSON_COUNT,
    NotesValidationError,
    freeze_filter_spec,
    init_notes_schema,
    lesson_rejection_rate,
    record_notes_output,
    validate_lesson_corpus,
    validate_notes,
    visible_mature_labels,
    visible_notes,
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
        "May improve with broader evidence.",
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
        "Expect hundreds of outcomes.",
        "Wait dozens of sessions.",
        "Review after Thanksgiving.",
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


def test_pipeline_hides_future_and_immature_labels_and_future_notes():
    con = duckdb.connect(":memory:")
    init_notes_schema(con)
    session = date(2024, 1, 10)
    cutoff = datetime(2024, 1, 11, 2, tzinfo=timezone.utc)
    con.executemany(
        "INSERT INTO replay_labels VALUES (?,?,?,?,?,?,?)",
        [
            ("past", date(2024, 1, 2), "h5", "2024-01-10T20:15:00Z", "terminal", 10, -5),
            ("tomorrow", date(2024, 1, 11), "h5", "2024-01-20T20:15:00Z", "terminal", 10, -5),
            ("today-immature", session, "h5", "2024-01-18T20:15:00Z", "pending", 10, None),
        ],
    )
    assert [row["decision_id"] for row in visible_mature_labels(
        con, session=session, cutoff=cutoff
    )] == ["past"]
    revision = record_notes_output(
        con,
        session=date(2024, 1, 9),
        written_at=cutoff - timedelta(hours=2),
        postmortems=[{
            "decision_id": "past", "expected_excess_bp": 10,
            "realized_excess_bp": -5, "error_type": "noise",
            "explanation": "The thesis lacked support.",
            "lesson": "Seek independent support.", "evidence_ids": [],
        }],
        lessons=[{"rule": "Seek independent support.", "uncertainty": "Signals can conflict."}],
        filter_spec=FILTER,
    )
    assert visible_mature_labels(con, session=session, cutoff=cutoff) == []
    assert visible_notes(con, session=session, cutoff=cutoff)[0]["revision_sha256"] == revision
    con.execute(
        "UPDATE replay_notes SET effective_at='2024-01-11T03:00:00.000000Z'"
    )
    assert visible_notes(con, session=session, cutoff=cutoff) == []


def test_postmortem_must_copy_the_visible_h5_label_exactly():
    con = duckdb.connect(":memory:")
    init_notes_schema(con)
    con.execute(
        "INSERT INTO replay_labels VALUES (?,?,?,?,?,?,?)",
        ("past", date(2024, 1, 2), "h5", "2024-01-10T20:15:00Z", "terminal", 10, -5),
    )
    with pytest.raises(NotesValidationError, match="postmortem_label_mismatch"):
        record_notes_output(
            con, session=date(2024, 1, 11),
            written_at=datetime(2024, 1, 12, 2, tzinfo=timezone.utc),
            postmortems=[{
                "decision_id": "past", "expected_excess_bp": 10,
                "realized_excess_bp": -4, "error_type": "noise",
                "explanation": "The thesis lacked support.",
                "lesson": "Seek independent support.", "evidence_ids": [],
            }],
            lessons=[], filter_spec=FILTER,
        )


def test_notes_revision_has_twelve_lesson_cap():
    con = duckdb.connect(":memory:")
    init_notes_schema(con)
    with pytest.raises(NotesValidationError, match="lesson_count"):
        record_notes_output(
            con,
            session=date(2024, 1, 9),
            written_at=datetime(2024, 1, 10, tzinfo=timezone.utc),
            postmortems=[],
            lessons=[{"rule": "Seek support.", "uncertainty": "Signals conflict."}] * 13,
            filter_spec=FILTER,
        )


def test_committed_prompt_and_postmortem_schema_exist():
    prompt = (ROOT / "prompts" / "notes-v1.txt").read_text()
    schema = json.loads((ROOT / "schemas" / "postmortem-v1.json").read_text())
    assert len(prompt.encode()) < 1_500
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
