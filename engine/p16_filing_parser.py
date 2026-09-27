"""Pure W3 filing parsing; callers own HTTP, receipts, queues and persistence."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from engine.lib.provenance import canonical_sha256

PARSER_VERSION = "p16-filings-parser-v1"
MAX_BYTES = 2_000_000
EVENTS = {"2.02": "earnings", "2.01": "acquisition_disposition",
          "1.01": "material_agreement", "5.02": "management_change",
          "7.01": "regulation_fd", "8.01": "other_material"}
PRECEDENCE = ("2.02", "2.01", "1.01", "5.02", "7.01", "8.01")
BLOCKS = {"p", "div", "tr", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def timestamp(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp requires an explicit offset")
    return parsed.astimezone(timezone.utc)


def acceptance_time(value: str) -> datetime:
    """SEC's unzoned SGML header is Eastern; never reinterpret ISO offsets."""
    if not re.fullmatch(r"[0-9]{14}", value):
        return timestamp(value)
    local = datetime.strptime(value, "%Y%m%d%H%M%S")
    zone = ZoneInfo("America/New_York")
    first, second = (local.replace(tzinfo=zone, fold=fold) for fold in (0, 1))
    if first.utcoffset() != second.utcoffset():
        raise ValueError("ambiguous or nonexistent SEC acceptance time")
    return first.astimezone(timezone.utc)


def resolve_acceptance(
    *,
    json_value: str | None = None,
    sgml_value: str | None = None,
    index_value: str | None = None,
    reference_received_at: str | datetime | None = None,
) -> dict:
    """Resolve an EDGAR acceptance from an SGML or bounded index reference.

    The submissions JSON clock is diagnostic because SEC bulk JSON has appeared
    with both UTC and Eastern wall-clock semantics behind a ``Z`` suffix.
    """
    references = []
    if sgml_value is not None:
        references.append(("sgml", acceptance_time(sgml_value)))
    if index_value is not None:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", index_value):
            raise ValueError("invalid index acceptance")
        references.append(("index", acceptance_time(index_value.replace("-", "").replace(" ", "").replace(":", ""))))
    if not references:
        return {
            "status": "acceptance_pending_crosscheck",
            "accepted_at": None,
            "event_at": None,
            "published_at": None,
            "reference": None,
            "json_crosscheck": "unverified",
        }
    accepted_values = {accepted for _, accepted in references}
    if len(accepted_values) != 1:
        raise ValueError("acceptance reference conflict")
    accepted = accepted_values.pop()
    if reference_received_at is not None and accepted > timestamp(reference_received_at):
        raise ValueError("acceptance is later than reference receipt")
    crosscheck = "absent"
    if json_value is not None:
        try:
            literal = timestamp(json_value).replace(microsecond=0)
            wall = datetime.fromisoformat(json_value.replace("Z", "+00:00")).replace(tzinfo=None)
            eastern = acceptance_time(wall.strftime("%Y%m%d%H%M%S"))
            crosscheck = (
                "utc_matches"
                if literal == accepted
                else "eastern_clock_matches"
                if eastern == accepted
                else "mismatch"
            )
        except (TypeError, ValueError, AttributeError):
            crosscheck = "invalid_json_timestamp"
    return {
        "status": "resolved",
        "accepted_at": accepted.isoformat(),
        "event_at": accepted.isoformat(),
        "published_at": accepted.isoformat(),
        "reference": "+".join(source for source, _ in references),
        "json_crosscheck": crosscheck,
    }


def cik_id(value: str | int) -> str:
    if not re.fullmatch(r"[0-9]{1,10}", str(value)) or int(value) == 0:
        raise ValueError("invalid CIK")
    return str(int(value)).zfill(10)


def safe_filename(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value) or ".." in value:
        raise ValueError("unsafe SEC basename")
    return value


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = re.sub(r"\s+", "", attrs.get("style") or "").casefold()
        hidden = (tag in {"script", "style", "head", "ix:header", "ix:hidden", "template"}
                  or "display:none" in style or "visibility:hidden" in style or "hidden" in attrs)
        hidden = hidden or bool(self.stack and self.stack[-1][1])
        if not hidden:
            if tag in BLOCKS:
                inside_row = any(parent == "tr" for parent, _ in self.stack)
                self.parts.append(" " if inside_row and tag != "tr" else "\n")
            elif tag in {"td", "th"}:
                self.parts.append("\t")
        if tag not in VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                if tag in BLOCKS and not self.stack[index][1]:
                    inside_row = any(parent == "tr" for parent, _ in self.stack[:index + 1])
                    self.parts.append(" " if inside_row and tag != "tr" else "\n")
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(data)


def visible_text(body: bytes, *, encoding: str = "utf-8") -> str:
    parser = _VisibleText()
    parser.feed(body.decode(encoding))
    parser.close()
    lines = ["\t".join(" ".join(cell.split()) for cell in line.split("\t")).strip()
             for line in "".join(parser.parts).replace("\xa0", " ").splitlines()]
    return "\n".join(line for line in lines if line)


def _documents(raw: bytes) -> list[dict]:
    matches = list(re.finditer(rb"(?ims)^<DOCUMENT>[^\S\r\n]*\r?\n(.*?)^</DOCUMENT>[^\S\r\n]*\r?$", raw))
    if not matches or any(len(re.findall(pattern, raw)) != len(matches) for pattern in
                          (rb"(?im)^<DOCUMENT>", rb"(?im)^</DOCUMENT>")):
        raise ValueError("incomplete or nested document envelopes")
    documents = []
    for match in matches:
        block = match.group(1)
        text = re.search(rb"(?ims)^<TEXT>[^\S\r\n]*\r?\n(.*?)^</TEXT>[^\S\r\n]*\r?$", block)
        if text is None or len(re.findall(rb"(?im)^</?TEXT>", block)) != 2:
            raise ValueError("malformed document text envelope")
        header = block[:text.start()]
        fields = [re.findall(rb"(?im)^<" + name + rb">([^\r\n]+)", header)
                  for name in (b"TYPE", b"SEQUENCE", b"FILENAME")]
        if any(len(field) != 1 for field in fields):
            raise ValueError("missing or duplicate document metadata")
        kind, sequence, filename = [field[0].decode("ascii").strip() for field in fields]
        if not sequence.isascii() or not sequence.isdigit():
            raise ValueError("invalid document sequence")
        start, end = (match.start(1) + text.start(1), match.start(1) + text.end(1))
        descriptions = re.findall(rb"(?im)^<DESCRIPTION>([^\r\n]+)", header)
        if len(descriptions) > 1:
            raise ValueError("duplicate document description")
        description = descriptions[0].decode("utf-8").strip() if descriptions else ""
        documents.append({"type": kind.upper(), "sequence": int(sequence),
                          "filename": safe_filename(filename), "description": description,
                          "raw_start": start, "raw_end": end})
    if len({doc["filename"] for doc in documents}) != len(documents):
        raise ValueError("duplicate document basename")
    return documents


def _excerpt(doc: dict, start: int, end: int, budget: int, source_hash: str) -> dict:
    if end - start > budget:
        end = max(start, doc["text"].rfind("\n", start, start + budget + 1))
    lineage = {"source_sha256": source_hash, "filename": doc["filename"],
               "parser_version": PARSER_VERSION, "normalized_sha256": doc["normalized_sha256"],
               "start": start, "end": end}
    return {**lineage, "evidence_id": canonical_sha256(lineage), "text": doc["text"][start:end]}


def normalize_submission(
    raw: bytes, *, cik: str | int, accession: str, received_at: str | datetime,
    primary_filename: str | None = None, metadata_items: tuple[str, ...] = (),
    index_labels: dict[str, str] | None = None,
    json_acceptance: str | None = None,
    index_acceptance: str | None = None,
    encoding: str = "utf-8",
) -> dict:
    """Normalize a complete SGML receipt without returning its private raw bytes.

    This is the complete-submission path, not an index/component downloader. Live
    availability covers this receipt only; a runner also gates map/index ingestion.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("submission must be complete bytes within the receipt limit")
    if not re.search(rb"(?im)^<SEC-DOCUMENT>", raw) or not re.search(rb"(?i)</SEC-DOCUMENT>\s*$", raw):
        raise ValueError("incomplete submission envelope")
    issuer = cik_id(cik)
    if not isinstance(accession, str) or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
        raise ValueError("invalid accession")
    header = re.split(rb"(?im)^<DOCUMENT>", raw, maxsplit=1)[0]
    numbers = [value.strip() for value in re.findall(rb"(?im)^\s*ACCESSION NUMBER:\s*([^\r\n]+)", header)]
    issuers = re.findall(rb"(?im)^\s*CENTRAL INDEX KEY:\s*([0-9]+)", header)
    if numbers != [accession.encode()] or not issuers or any(cik_id(value.decode()) != issuer for value in issuers):
        raise ValueError("submission header identity differs")
    acceptances = re.findall(rb"(?im)^<ACCEPTANCE-DATETIME>([0-9]{14})\s*$", header)
    if len(acceptances) != 1:
        raise ValueError("missing or ambiguous acceptance header")
    received = timestamp(received_at)
    acceptance = resolve_acceptance(
        json_value=json_acceptance,
        sgml_value=acceptances[0].decode(),
        index_value=index_acceptance,
        reference_received_at=received,
    )
    documents, source_hash = _documents(raw), hashlib.sha256(raw).hexdigest()
    primaries = [doc for doc in documents if doc["type"] in {"8-K", "8-K/A"}]
    if primary_filename is not None:
        primaries = [doc for doc in primaries if doc["filename"] == safe_filename(primary_filename)]
    exhibits = [doc for doc in documents if doc["type"] == "EX-99.1"]
    if len(primaries) != 1 or len(exhibits) > 1:
        raise ValueError("missing or ambiguous primary/exhibit 99.1")
    exhibit_status = "ex99_1" if exhibits else "absent"
    if not exhibits:
        generic = [doc for doc in documents if doc["type"] == "EX-99"]
        if len(generic) > 1:
            raise ValueError("ambiguous generic EX-99 exhibits")
        if generic:
            candidate = generic[0]
            index_label = (index_labels or {}).get(candidate["filename"], "")
            if re.search(r"\bpress\s+release\b", f"{candidate['description']} {index_label}", re.I):
                exhibits = [candidate]
                exhibit_status = "ex99_sole"
    primary, selected = primaries[0], [primaries[0], *exhibits]
    unsupported = False
    for doc in selected:
        body = raw[doc["raw_start"]:doc["raw_end"]]
        supported = doc["filename"].lower().endswith((".htm", ".html", ".txt")) and not body.lstrip().startswith(b"%PDF")
        unsupported |= not supported
        doc.update(text=visible_text(body, encoding=encoding) if supported else "")
        doc["normalized_sha256"] = hashlib.sha256(doc["text"].encode()).hexdigest()
    headings = list(re.finditer(r"(?im)^\s*item\s+(\d\.\d{2})\s*(?!\d)", primary["text"]))
    body_items, declared = {match[1] for match in headings}, set(metadata_items)
    items = sorted((body_items | declared) & EVENTS.keys())
    spans, omitted, remaining = [], [], 8_000
    for index, match in enumerate(headings):
        if match[1] not in EVENTS:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(primary["text"])
        span = _excerpt(primary, match.start(), end, remaining, source_hash)
        if span["end"] < end:
            omitted.append({"filename": primary["filename"], "start": span["end"], "end": end})
        if span["text"]:
            spans.append(span)
            remaining -= len(span["text"])
    primary_readable = bool(spans)
    if exhibits:
        span = _excerpt(exhibits[0], 0, len(exhibits[0]["text"]), 32_000, source_hash)
        if span["end"] < len(exhibits[0]["text"]):
            omitted.append({"filename": exhibits[0]["filename"], "start": span["end"], "end": len(exhibits[0]["text"])})
        if span["text"]:
            spans.append(span)
    status = "ready" if items and primary_readable else "extraction_unavailable"
    if unsupported or exhibits and not exhibits[0]["text"]:
        status = "unsupported_format" if unsupported else "extraction_unavailable"
    identity = {"cik": issuer, "accession": accession, "accepted_at": acceptance["accepted_at"],
                "parser_version": PARSER_VERSION, "items": items,
                "documents": [{key: doc[key] for key in ("type", "filename", "normalized_sha256")}
                              for doc in selected]}
    selection_reasons = {
        primary["filename"]: "primary",
        **({exhibits[0]["filename"]: exhibit_status} if exhibits else {}),
    }
    return {**identity, "status": status, "source_sha256": source_hash,
            "normalized_sha256": canonical_sha256(identity), "documents": documents,
            "received_at": received.isoformat(), "acceptance": acceptance, "encoding": encoding,
            "exhibit_status": exhibit_status, "spans": spans,
            "document_candidates": [{"type": doc["type"], "sequence": doc["sequence"],
                                     "filename": doc["filename"], "description": doc["description"],
                                     "selection_reason": selection_reasons.get(doc["filename"], "not_selected")}
                                    for doc in documents],
            "allowed_event_kinds": [EVENTS[item] for item in EVENTS if item in items],
            "primary_event_kind": next((EVENTS[item] for item in PRECEDENCE if item in items), None),
            "item_disagreement": bool(declared and declared != body_items),
            "body_items": sorted(body_items), "metadata_items": sorted(declared),
            "omitted_spans": omitted, "truncated": bool(omitted)}


def map_cik_scope(cik, *, rows: list[dict], universe: set[str], cutoff_at, aliases: dict[str, str] | None = None) -> dict:
    """Rows are an as-known security-master snapshot, each with CIK/ticker/security_id/available_at."""
    cutoff, issuer, aliases = timestamp(cutoff_at), cik_id(cik), aliases or {}
    known = [row for row in rows if cik_id(row["cik"]) == issuer
             and timestamp(row["available_at"]) <= cutoff]
    if not known:
        return {"status": "unmapped", "cik": issuer, "securities": []}
    latest = max(timestamp(row["available_at"]) for row in known)
    current = [row for row in rows if timestamp(row["available_at"]) == latest]
    selected = {}
    for row in current:
        ticker = aliases.get(row["ticker"], row["ticker"])
        if cik_id(row["cik"]) == issuer and ticker in universe:
            conflicts = {(cik_id(other["cik"]), other["security_id"]) for other in current
                         if aliases.get(other["ticker"], other["ticker"]) == ticker}
            if len(conflicts) != 1:
                return {"status": "ambiguous", "cik": issuer, "securities": []}
            selected[ticker] = {"ticker": ticker, "security_id": row["security_id"]}
    status = "outside_universe" if any(cik_id(row["cik"]) == issuer for row in current) else "unmapped"
    return {"status": "mapped" if selected else status, "cik": issuer,
            "map_available_at": latest.isoformat(), "securities": [selected[key] for key in sorted(selected)]}


def session_volume_fraction(observed_at, *, opens_at, closes_at) -> float:
    """Use caller-supplied admitted exchange schedule, including early closes."""
    opened, closed, observed = timestamp(opens_at), timestamp(closes_at), timestamp(observed_at)
    if closed <= opened:
        raise ValueError("invalid session schedule")
    return min(1.0, max(0.0, (observed - opened) / (closed - opened)))


def match_company_names(text: str, *, names: dict[str, str]) -> list[str]:
    """Exact casefolded whole-name matching; ambiguous names map to no security."""
    by_name = {}
    for ticker, name in names.items():
        if isinstance(name, str) and name.strip():
            by_name.setdefault(name.strip().casefold(), set()).add(ticker)
    return sorted({next(iter(tickers)) for name, tickers in by_name.items()
                   if len(tickers) == 1 and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text.casefold())})
