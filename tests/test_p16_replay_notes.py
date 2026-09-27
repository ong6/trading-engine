"""W4 notes-filter acceptance and frozen-corpus tests."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from engine.lib.provenance import canonical_sha256
from farm.replay.notes import (
    NotesValidationError,
    freeze_filter_spec,
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
FROZEN = datetime(2026, 9, 27, 15, 12, tzinfo=timezone.utc)
REGISTERED = datetime(2026, 9, 27, 15, 20, tzinfo=timezone.utc)


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
    attestation_sha = hashlib.sha256(
        fixture["authorship_attestation"].encode()
    ).hexdigest()
    assert attestation_sha == fixture["authorship_evidence_sha256"]
    result = validate_lesson_corpus(
        fixture["lessons"],
        filter_spec=FILTER,
        expected_sha256=fixture["corpus_sha256"],
        expected_count=120,
        corpus_frozen_at=datetime.fromisoformat(fixture["frozen_at"]),
        bound_registered_at=datetime.fromisoformat(fixture["bound_registered_at"]),
        authorship_evidence_sha256=fixture["authorship_evidence_sha256"],
    )
    assert result.count == 120
    assert result.rejected <= 12
    assert result.rejection_rate <= Decimal("0.10")


def _validate_boundary(lessons, maximum=Decimal("0.10")):
    return validate_lesson_corpus(
        lessons,
        filter_spec=FILTER,
        expected_sha256=canonical_sha256({"lessons": lessons}),
        expected_count=len(lessons),
        corpus_frozen_at=FROZEN,
        bound_registered_at=REGISTERED,
        authorship_evidence_sha256="a" * 64,
        max_rejection_rate=maximum,
    )


def test_exact_ten_percent_rejection_passes_and_eleven_percent_fails():
    ten_rejected = ["General principle."] * 90 + ["Wait one day."] * 10
    assert _validate_boundary(ten_rejected).rejected == 10
    eleven_rejected = ["General principle."] * 89 + ["Wait one day."] * 11
    with pytest.raises(NotesValidationError, match="notes_design_rejected"):
        _validate_boundary(eleven_rejected)


def test_corpus_count_digest_and_freeze_order_are_fail_closed():
    lessons = ["General principle."] * 100
    digest = canonical_sha256({"lessons": lessons})
    common = dict(
        filter_spec=FILTER,
        expected_sha256=digest,
        expected_count=100,
        corpus_frozen_at=FROZEN,
        bound_registered_at=REGISTERED,
        authorship_evidence_sha256="a" * 64,
    )
    with pytest.raises(NotesValidationError, match="count_mismatch"):
        validate_lesson_corpus(lessons[:-1], **common)
    with pytest.raises(NotesValidationError, match="digest_mismatch"):
        validate_lesson_corpus([*lessons[:-1], "Changed principle."], **common)
    with pytest.raises(NotesValidationError, match="not_frozen_before_bound"):
        validate_lesson_corpus(
            lessons,
            **{**common, "corpus_frozen_at": REGISTERED},
        )
