"""Frozen lexical guard for model-authored replay lessons."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence

from engine.lib.provenance import canonical_sha256

_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
MIN_LESSON_COUNT = 100
MAX_LESSON_REJECTION_RATE = Decimal("0.10")
LESSON_CORPUS_REGISTRATION = {
    "corpus_sha256": "df038a79116ccb6faebb0ee63435b1afde54945968f7371b7ca1a6f45c64433c",
    "count": 120,
}

DATE_WORDS = frozenset(
    "january february april june july august september october november december "
    "monday tuesday wednesday thursday friday saturday sunday jan feb mar apr jun "
    "jul aug sep sept oct nov dec mon tue tues thu thurs fri today tomorrow yesterday "
    "thanksgiving christmas juneteenth easter memorial independence presidents"
    .split()
)
NUMBER_WORDS = frozenset(
    "zero two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand million billion trillion third fourth fifth sixth "
    "seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth "
    "seventeenth eighteenth nineteenth twentieth thirtieth dozens hundreds thousands "
    "millions billions trillions"
    .split()
)
CONTEXTUAL_NUMBER_WORDS = frozenset({"one", "first", "second"})
AMBIGUOUS_DATE_WORDS = frozenset({"may", "march", "second", "sun", "sat", "wed"})
CALENDAR_NOUNS = frozenset({"earnings", "release", "results", "holiday", "meeting"})
DATE_CONTEXT = frozenset(
    {"on", "in", "until", "since", "before", "after", "during", "by", "from", "through", "next", "last", "every"}
)
UNIT_WORDS = frozenset(
    "day days week weeks month months quarter quarters year years session sessions hour hours minute minutes "
    "percent percentage point points basis dollar dollars cent cents euro euros yen pounds"
    .split()
)
ERROR_TYPES = frozenset(
    {"gap_risk", "headline_overweight", "sector_move_missed", "earnings_surprise",
     "regime", "data_issue", "noise", "correct"}
)
MAX_LESSONS = 12


class NotesValidationError(ValueError):
    """A lesson contains an identity or time/value anchor forbidden by W4."""


@dataclass(frozen=True)
class NotesFilterSpec:
    tickers: tuple[str, ...]
    company_names: tuple[str, ...]
    aliases: tuple[str, ...]
    spec_sha256: str


@dataclass(frozen=True)
class CorpusValidation:
    count: int
    rejected: int
    rejection_rate: Decimal
    maximum_rejection_rate: Decimal
    corpus_sha256: str
    filter_spec_sha256: str


def _normalized_words(text: str) -> tuple[str, list[str]]:
    if not isinstance(text, str) or not text.strip():
        raise NotesValidationError("notes_empty")
    if any(unicodedata.category(char) == "Cf" for char in text):
        raise NotesValidationError("notes_invisible_character")
    normalized = unicodedata.normalize("NFKC", text)
    if any(unicodedata.category(char) == "Cf" for char in normalized):
        raise NotesValidationError("notes_invisible_character")
    return normalized, _TOKEN.findall(normalized)


def freeze_filter_spec(
    *, tickers: Sequence[str], company_names: Sequence[str], aliases: Sequence[str]
) -> NotesFilterSpec:
    payload = {
        "aliases": sorted(set(aliases)),
        "ambiguous_date_words": sorted(AMBIGUOUS_DATE_WORDS),
        "company_names": sorted(set(company_names)),
        "contextual_number_words": sorted(CONTEXTUAL_NUMBER_WORDS),
        "date_context": sorted(DATE_CONTEXT),
        "date_words": sorted(DATE_WORDS),
        "number_words": sorted(NUMBER_WORDS),
        "tickers": sorted(set(tickers)),
        "unit_words": sorted(UNIT_WORDS),
    }
    return NotesFilterSpec(
        tickers=tuple(payload["tickers"]),
        company_names=tuple(payload["company_names"]),
        aliases=tuple(payload["aliases"]),
        spec_sha256=canonical_sha256(payload),
    )


def _date_like(words: list[str], index: int) -> bool:
    before = words[index - 1].casefold() if index else ""
    after = words[index + 1].casefold() if index + 1 < len(words) else ""
    return (
        before in DATE_CONTEXT
        or before in DATE_WORDS
        or before in AMBIGUOUS_DATE_WORDS
        or after in DATE_WORDS
        or after in AMBIGUOUS_DATE_WORDS
        or after in UNIT_WORDS
        or after.isnumeric()
    )


def _sentence_start(text: str, index: int) -> bool:
    prefix = text[:index].rstrip()
    while prefix and (
        unicodedata.category(prefix[-1]) in {"Ps", "Pi", "Pe", "Pf"}
        or prefix[-1] in "'\"—–-"
    ):
        prefix = prefix[:-1].rstrip()
    return not prefix or prefix[-1] in ".!?"


def validate_notes(text: str, *, filter_spec: NotesFilterSpec) -> str:
    """Return normalized safe prose or reject identity/time/value leakage."""
    normalized, words = _normalized_words(text)
    if any(char.isnumeric() or char in "$€£¥%" for char in normalized):
        raise NotesValidationError("notes_price_or_date_number")

    folded = [word.casefold() for word in words]
    if set(folded) & (DATE_WORDS | NUMBER_WORDS):
        raise NotesValidationError("notes_date_or_number_word")
    for index, word in enumerate(words):
        lower = word.casefold()
        if lower in AMBIGUOUS_DATE_WORDS and _date_like(words, index):
            raise NotesValidationError("notes_date_or_number_word")
        if (
            lower in {"march", "sun", "sat", "wed"} and word[:1].isupper()
            or lower == "may" and word == "May" and (
                (folded[index - 1] if index else "") in DATE_CONTEXT
                or (folded[index + 1] if index + 1 < len(folded) else "") in CALENDAR_NOUNS
            )
        ):
            raise NotesValidationError("notes_date_or_number_word")
        if lower in CONTEXTUAL_NUMBER_WORDS:
            before = folded[index - 1] if index else ""
            after = folded[index + 1] if index + 1 < len(folded) else ""
            if (
                before in DATE_WORDS | AMBIGUOUS_DATE_WORDS | UNIT_WORDS
                or after in DATE_WORDS | AMBIGUOUS_DATE_WORDS | UNIT_WORDS
            ):
                raise NotesValidationError("notes_date_or_number_word")

    for ticker in filter_spec.tickers:
        parts = _TOKEN.findall(ticker)
        if not parts:
            continue
        cash = r"(?<!\w)\$" + r"[.\-]".join(map(re.escape, parts)) + r"(?!\w)"
        if re.search(cash, normalized, re.IGNORECASE):
            raise NotesValidationError("notes_universe_identity")
        exact = r"(?<![\w$])" + r"[.\- ]".join(map(re.escape, parts)) + r"(?!\w)"
        for match in re.finditer(exact, normalized):
            if len(parts) == 1 and len(parts[0]) == 1 and _sentence_start(normalized, match.start()):
                continue
            raise NotesValidationError("notes_universe_identity")

    for value in (*filter_spec.company_names, *filter_spec.aliases):
        banned = _TOKEN.findall(unicodedata.normalize("NFKC", value))
        if len(banned) < 2:
            continue
        target = [word.casefold() for word in banned]
        for start in range(len(words) - len(banned) + 1):
            candidate = words[start : start + len(banned)]
            if [word.casefold() for word in candidate] == target and all(
                word[:1].isupper() for word in candidate
            ):
                raise NotesValidationError("notes_universe_identity")
    return normalized


def validate_lesson_corpus(
    lessons: Sequence[str],
    *,
    filter_spec: NotesFilterSpec,
) -> CorpusValidation:
    """Verify the one registered independent corpus under its fixed safety bound."""
    expected_count = LESSON_CORPUS_REGISTRATION["count"]
    if expected_count < MIN_LESSON_COUNT or len(lessons) != expected_count:
        raise NotesValidationError("lesson_corpus_too_small_or_count_mismatch")
    actual_sha256 = canonical_sha256({"lessons": list(lessons)})
    if actual_sha256 != LESSON_CORPUS_REGISTRATION["corpus_sha256"]:
        raise NotesValidationError("lesson_corpus_digest_mismatch")
    rejected = 0
    for lesson in lessons:
        try:
            validate_notes(lesson, filter_spec=filter_spec)
        except NotesValidationError:
            rejected += 1
    rate = lesson_rejection_rate(rejected, expected_count)
    if rate > MAX_LESSON_REJECTION_RATE:
        raise NotesValidationError("notes_design_rejected")
    return CorpusValidation(
        count=expected_count,
        rejected=rejected,
        rejection_rate=rate,
        maximum_rejection_rate=MAX_LESSON_REJECTION_RATE,
        corpus_sha256=actual_sha256,
        filter_spec_sha256=filter_spec.spec_sha256,
    )


def lesson_rejection_rate(rejected: int, count: int) -> Decimal:
    if type(rejected) is not int or type(count) is not int or not 0 <= rejected <= count:
        raise NotesValidationError("invalid_lesson_rejection_count")
    if count < MIN_LESSON_COUNT:
        raise NotesValidationError("lesson_corpus_too_small_or_count_mismatch")
    return Decimal(rejected) / Decimal(count)


def _iso(value: datetime, field: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise NotesValidationError(f"invalid_{field}")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def init_notes_schema(con) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS replay_labels (
            decision_id VARCHAR NOT NULL,
            decision_session DATE NOT NULL,
            horizon VARCHAR NOT NULL,
            visible_at VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            expected_excess_bp DOUBLE,
            realized_excess_bp DOUBLE,
            PRIMARY KEY(decision_id,horizon))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS replay_postmortems (
            decision_id VARCHAR PRIMARY KEY,
            decision_session DATE NOT NULL,
            written_at VARCHAR NOT NULL,
            payload_json VARCHAR NOT NULL)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS replay_notes (
            revision_sha256 VARCHAR PRIMARY KEY,
            source_session DATE NOT NULL,
            effective_at VARCHAR NOT NULL,
            previous_revision VARCHAR,
            lessons_json VARCHAR NOT NULL)"""
    )


def visible_mature_labels(con, *, session: date, cutoff: datetime) -> list[dict]:
    """Expose only terminal h5 outcomes from sessions strictly before this one."""
    cutoff_at = datetime.fromisoformat(_iso(cutoff, "label_cutoff").replace("Z", "+00:00"))
    rows = con.execute(
        "SELECT decision_id,decision_session,horizon,visible_at,status,"
        "expected_excess_bp,realized_excess_bp FROM replay_labels "
        "WHERE decision_session<? AND horizon='h5' ORDER BY decision_session,decision_id",
        [session],
    ).fetchall()
    result = []
    for row in rows:
        visible = datetime.fromisoformat(row[3].replace("Z", "+00:00"))
        if row[4] == "terminal" and visible < cutoff_at:
            result.append(
                {
                    "decision_id": row[0], "decision_session": row[1].isoformat(),
                    "horizon": row[2], "visible_at": row[3], "status": row[4],
                    "expected_excess_bp": row[5], "realized_excess_bp": row[6],
                }
            )
    return result


def visible_notes(con, *, session: date, cutoff: datetime) -> list[dict]:
    """Return the latest notes revision from an earlier replay session."""
    cutoff_at = datetime.fromisoformat(_iso(cutoff, "notes_cutoff").replace("Z", "+00:00"))
    rows = con.execute(
        "SELECT revision_sha256,source_session,effective_at,lessons_json FROM replay_notes "
        "WHERE source_session<? ORDER BY effective_at DESC,revision_sha256",
        [session],
    ).fetchall()
    for revision, source_session, effective_at, lessons_json in rows:
        if datetime.fromisoformat(effective_at.replace("Z", "+00:00")) < cutoff_at:
            return [{
                "revision_sha256": revision,
                "source_session": source_session.isoformat(),
                "effective_at": effective_at,
                "lessons": json.loads(lessons_json),
            }]
    return []


def record_notes_output(
    con,
    *,
    session: date,
    written_at: datetime,
    postmortems: Sequence[dict],
    lessons: Sequence[dict],
    filter_spec: NotesFilterSpec,
) -> str | None:
    """Validate and append one post-mortem batch and optional weekly notes revision."""
    init_notes_schema(con)
    written = _iso(written_at, "notes_written_at")
    for row in postmortems:
        required = {
            "decision_id", "expected_excess_bp", "realized_excess_bp", "error_type",
            "explanation", "lesson", "evidence_ids",
        }
        if set(row) != required or row["error_type"] not in ERROR_TYPES:
            raise NotesValidationError("invalid_postmortem_schema")
        validate_notes(row["explanation"], filter_spec=filter_spec)
        validate_notes(row["lesson"], filter_spec=filter_spec)
        payload = json.dumps(row, sort_keys=True, separators=(",", ":"))
        prior = con.execute(
            "SELECT decision_session,written_at,payload_json FROM replay_postmortems "
            "WHERE decision_id=?", [row["decision_id"]],
        ).fetchone()
        expected = (session, written, payload)
        if prior is None:
            con.execute(
                "INSERT INTO replay_postmortems VALUES (?,?,?,?)",
                [row["decision_id"], session, written, payload],
            )
        elif prior != expected:
            raise NotesValidationError("postmortem_append_conflict")
    if not lessons:
        return None
    if len(lessons) > MAX_LESSONS or any(set(row) != {"rule", "uncertainty"} for row in lessons):
        raise NotesValidationError("invalid_lesson_count_or_shape")
    normalized = [
        {
            "rule": validate_notes(row["rule"], filter_spec=filter_spec),
            "uncertainty": validate_notes(row["uncertainty"], filter_spec=filter_spec),
        }
        for row in lessons
    ]
    previous = con.execute(
        "SELECT revision_sha256 FROM replay_notes ORDER BY effective_at DESC,revision_sha256 LIMIT 1"
    ).fetchone()
    body = {
        "source_session": session.isoformat(), "effective_at": written,
        "previous_revision": None if previous is None else previous[0],
        "lessons": normalized,
    }
    revision = canonical_sha256(body)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    prior = con.execute(
        "SELECT source_session,effective_at,previous_revision,lessons_json FROM replay_notes "
        "WHERE revision_sha256=?", [revision],
    ).fetchone()
    expected = (session, written, body["previous_revision"], encoded)
    if prior is None:
        con.execute(
            "INSERT INTO replay_notes VALUES (?,?,?,?,?)",
            [revision, *expected],
        )
    elif prior != expected:
        raise NotesValidationError("notes_append_conflict")
    return revision
