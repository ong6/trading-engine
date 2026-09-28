"""Deterministic, conservative record-to-security mapping against a caller's as-of name table."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Mapping, Sequence

_TOKEN = re.compile(r"[^\W_]+")
_SUFFIXES = frozenset({
    "inc", "incorporated", "corp", "corporation", "co", "company", "companies", "ltd", "limited",
    "plc", "holdings", "holding", "group", "llc", "lp", "sa", "ag", "nv", "se", "the",
})
_CASHTAG = re.compile(r"(?<![\w$])\$([A-Z]{1,5}(?:\.[A-Z])?)\b")
_EXCHANGE = re.compile(
    r"\((?:NYSE(?: American| Arca)?|NASDAQ|Nasdaq|AMEX)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\)"
)
_MIN_NAME_CHARS = 3


# (security_id, valid_from inclusive, valid_to exclusive); a missing bound is open.
Entry = tuple[str, date | None, date | None]


@dataclass(frozen=True)
class NameIndex:
    names: Mapping[str, tuple[Entry, ...]]
    tickers: Mapping[str, tuple[Entry, ...]]
    max_tokens: int


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(unicodedata.normalize("NFKC", text))


def normalize_name(text: object) -> str:
    """Casefold, drop punctuation and leading/trailing legal suffixes ("The X Holdings Inc" -> "x")."""
    tokens = [token.casefold() for token in _tokens(str(text or ""))]
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    while tokens and tokens[0] == "the":
        tokens.pop(0)
    return " ".join(tokens)


def _day(value: object) -> date | None:
    """UTC calendar date of a date, datetime or ISO string; None when absent."""
    if value is None or value == "":
        return None
    if not isinstance(value, (date, datetime)):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if isinstance(value, datetime):
        return (value if value.tzinfo is None else value.astimezone(timezone.utc)).date()
    return value


def build_name_index(rows: Sequence[Mapping] | NameIndex) -> NameIndex:
    if isinstance(rows, NameIndex):
        return rows
    names: dict[str, set[Entry]] = {}
    tickers: dict[str, set[Entry]] = {}
    for row in rows:
        entry = (str(row["security_id"]), _day(row.get("valid_from")), _day(row.get("valid_to")))
        for alias in (row.get("name"), *(row.get("aliases") or ())):
            key = normalize_name(alias)
            if len(key) >= _MIN_NAME_CHARS:
                names.setdefault(key, set()).add(entry)
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker:
            tickers.setdefault(ticker, set()).add(entry)
    return NameIndex(
        names={key: tuple(sorted(entries, key=str)) for key, entries in names.items()},
        tickers={key: tuple(sorted(entries, key=str)) for key, entries in tickers.items()},
        max_tokens=max((key.count(" ") + 1 for key in names), default=0),
    )


def match_securities(record: Mapping, name_table: Sequence[Mapping] | NameIndex) -> tuple[str, ...]:
    """Security ids named by a record's text, GKG organizations, cashtags or exchange tags.

    Only names valid on the record's availability date count.  One-word names
    ("Target", "Apple") are too ambiguous for free text and match only through
    organizations, cashtags or exchange tags.
    """
    index = build_name_index(name_table)
    on = _day(record.get("available_at_replay"))
    found: set[str] = set()

    def add(entries: Sequence[Entry]) -> None:
        found.update(
            security_id for security_id, start, end in entries
            if on is None or ((start is None or start <= on) and (end is None or on < end))
        )

    text = " ".join(str(record.get(field) or "") for field in ("headline", "body"))
    folded = [token.casefold() for token in _tokens(text)]
    for start in range(len(folded)):
        for width in range(2, min(index.max_tokens, len(folded) - start) + 1):
            add(index.names.get(" ".join(folded[start:start + width]), ()))
    for organization in str(record.get("organizations") or "").split(";"):
        add(index.names.get(normalize_name(re.sub(r",\d+$", "", organization)), ()))
    for pattern in (_CASHTAG, _EXCHANGE):
        for ticker in pattern.findall(unicodedata.normalize("NFKC", text)):
            add(index.tickers.get(ticker, ()))
    return tuple(sorted(found))


def news_rows_by_ticker(records: Sequence[Mapping], name_table: Sequence[Mapping]) -> list[dict]:
    """One news row per mapped security, keyed by ticker as P15's context expects; unmapped rows drop."""
    tickers = {str(row["security_id"]): str(row["ticker"]) for row in name_table if row.get("ticker")}
    return [
        {**record, "ticker": tickers[security_id]}
        for record in records for security_id in record.get("security_ids") or ()
        if security_id in tickers
    ]
