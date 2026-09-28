"""Deterministic, conservative record-to-security mapping against a caller's as-of name table."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
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


@dataclass(frozen=True)
class NameIndex:
    names: Mapping[str, frozenset[str]]
    tickers: Mapping[str, frozenset[str]]
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


def build_name_index(rows: Sequence[Mapping] | NameIndex) -> NameIndex:
    if isinstance(rows, NameIndex):
        return rows
    names: dict[str, set[str]] = {}
    tickers: dict[str, set[str]] = {}
    for row in rows:
        security_id = str(row["security_id"])
        for alias in (row.get("name"), *(row.get("aliases") or ())):
            key = normalize_name(alias)
            if len(key) >= _MIN_NAME_CHARS:
                names.setdefault(key, set()).add(security_id)
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker:
            tickers.setdefault(ticker, set()).add(security_id)
    return NameIndex(
        names={key: frozenset(ids) for key, ids in names.items()},
        tickers={key: frozenset(ids) for key, ids in tickers.items()},
        max_tokens=max((key.count(" ") + 1 for key in names), default=0),
    )


def match_securities(record: Mapping, name_table: Sequence[Mapping] | NameIndex) -> tuple[str, ...]:
    """Security ids named by a record's text, GKG organizations, cashtags or exchange tags."""
    index = build_name_index(name_table)
    found: set[str] = set()
    text = " ".join(str(record.get(field) or "") for field in ("headline", "body"))
    raw = _tokens(text)
    folded = [token.casefold() for token in raw]
    for start in range(len(folded)):
        for width in range(1, min(index.max_tokens, len(folded) - start) + 1):
            ids = index.names.get(" ".join(folded[start:start + width]))
            # A one-word name must look like a proper noun in the source ("Apple", not "apple").
            if ids and (width > 1 or not raw[start].islower()):
                found.update(ids)
    for organization in str(record.get("organizations") or "").split(";"):
        found.update(index.names.get(normalize_name(re.sub(r",\d+$", "", organization)), ()))
    for pattern in (_CASHTAG, _EXCHANGE):
        for ticker in pattern.findall(unicodedata.normalize("NFKC", text)):
            found.update(index.tickers.get(ticker, ()))
    return tuple(sorted(found))


def news_rows_by_ticker(records: Sequence[Mapping], name_table: Sequence[Mapping]) -> list[dict]:
    """One news row per mapped security, keyed by ticker as P15's context expects; unmapped rows drop."""
    tickers = {str(row["security_id"]): str(row["ticker"]) for row in name_table if row.get("ticker")}
    return [
        {**record, "ticker": tickers[security_id]}
        for record in records for security_id in record.get("security_ids") or ()
        if security_id in tickers
    ]
