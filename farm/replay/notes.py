"""Frozen lexical guard for model-authored replay lessons."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
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
    "frozen_at": "2026-09-27T15:42:25Z",
    "bound_registered_at": "2026-09-27T15:42:52Z",
    "frozen_commit": "65a6dd2d7dfaca4b1434394c896bb6face522fcf",
    "authorship_evidence_sha256": "aeca4ca95ad7fb872a07f852452df153394f4805b62839aa8e420e891afe6fd9",
}

DATE_WORDS = frozenset(
    "january february april june july august september october november december "
    "monday tuesday wednesday thursday friday saturday sunday jan feb mar apr jun "
    "jul aug sep sept oct nov dec mon tue tues thu thurs fri today tomorrow yesterday"
    .split()
)
NUMBER_WORDS = frozenset(
    "zero two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand million billion trillion third fourth fifth sixth "
    "seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth "
    "seventeenth eighteenth nineteenth twentieth thirtieth"
    .split()
)
CONTEXTUAL_NUMBER_WORDS = frozenset({"one", "first", "second"})
AMBIGUOUS_DATE_WORDS = frozenset({"may", "march", "second", "sun", "sat", "wed"})
DATE_CONTEXT = frozenset(
    {"on", "in", "until", "since", "before", "after", "during", "by", "from", "through", "next", "last", "every"}
)
UNIT_WORDS = frozenset(
    "day days week weeks month months quarter quarters year years session sessions hour hours minute minutes "
    "percent percentage point points basis dollar dollars cent cents euro euros yen pounds"
    .split()
)


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
    authorship_evidence_sha256: str


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
    if set(folded) & (DATE_WORDS | NUMBER_WORDS | UNIT_WORDS):
        raise NotesValidationError("notes_date_or_number_word")
    for index, word in enumerate(words):
        lower = word.casefold()
        if lower in AMBIGUOUS_DATE_WORDS and _date_like(words, index):
            raise NotesValidationError("notes_date_or_number_word")
        if lower in {"may", "march", "sun", "sat", "wed"} and word[:1].isupper():
            raise NotesValidationError("notes_date_or_number_word")
        if lower in CONTEXTUAL_NUMBER_WORDS:
            before = folded[index - 1] if index else ""
            before_two = folded[index - 2] if index > 1 else ""
            after = folded[index + 1] if index + 1 < len(folded) else ""
            if (
                before in DATE_WORDS | AMBIGUOUS_DATE_WORDS | UNIT_WORDS
                or after in DATE_WORDS | AMBIGUOUS_DATE_WORDS | UNIT_WORDS
                or (before == "the" and before_two in DATE_CONTEXT)
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
    authorship_attestation: str,
) -> CorpusValidation:
    """Verify the one registered independent corpus under its fixed safety bound."""
    expected_count = LESSON_CORPUS_REGISTRATION["count"]
    if expected_count < MIN_LESSON_COUNT or len(lessons) != expected_count:
        raise NotesValidationError("lesson_corpus_too_small_or_count_mismatch")
    actual_sha256 = canonical_sha256({"lessons": list(lessons)})
    if actual_sha256 != LESSON_CORPUS_REGISTRATION["corpus_sha256"]:
        raise NotesValidationError("lesson_corpus_digest_mismatch")
    corpus_frozen_at = datetime.fromisoformat(
        LESSON_CORPUS_REGISTRATION["frozen_at"].replace("Z", "+00:00")
    )
    bound_registered_at = datetime.fromisoformat(
        LESSON_CORPUS_REGISTRATION["bound_registered_at"].replace("Z", "+00:00")
    )
    if corpus_frozen_at >= bound_registered_at:
        raise NotesValidationError("lesson_corpus_not_frozen_before_bound")
    import hashlib
    authorship_evidence_sha256 = hashlib.sha256(authorship_attestation.encode()).hexdigest()
    if authorship_evidence_sha256 != LESSON_CORPUS_REGISTRATION["authorship_evidence_sha256"]:
        raise NotesValidationError("lesson_corpus_authorship_unbound")

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
        authorship_evidence_sha256=authorship_evidence_sha256,
    )


def lesson_rejection_rate(rejected: int, count: int) -> Decimal:
    if type(rejected) is not int or type(count) is not int or not 0 <= rejected <= count:
        raise NotesValidationError("invalid_lesson_rejection_count")
    if count < MIN_LESSON_COUNT:
        raise NotesValidationError("lesson_corpus_too_small_or_count_mismatch")
    return Decimal(rejected) / Decimal(count)
