"""Synthetic tests for salvaged P16 filing-parser primitives."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from engine import p16_filing_parser as filings
from engine.lib.provenance import canonical_sha256

RAW = (Path(__file__).parent / "fixtures" / "p16_filings_synthetic.txt").read_bytes()
ACCESSION = "0000099999-26-000001"
RECEIVED = "2026-09-25T20:31:00Z"


def normalize(raw=RAW, **options):
    return filings.normalize_submission(
        raw,
        cik="123",
        accession=ACCESSION,
        received_at=options.pop("received_at", RECEIVED),
        **options,
    )


def test_material_sections_exact_exhibit_and_byte_lineage():
    record = normalize()
    assert record["status"] == "ready"
    assert record["cik"] == "0000000123"
    assert record["items"] == ["2.02", "7.01"]
    assert record["body_items"] == ["2.02", "7.01", "9.01"]
    assert record["primary_event_kind"] == "earnings"
    assert record["exhibit_status"] == "ex99_1"
    assert record["source_sha256"] == hashlib.sha256(RAW).hexdigest()
    assert "raw_body" not in record
    texts = "\n".join(span["text"] for span in record["spans"])
    assert "wrong exhibit" not in texts
    assert "Hidden" not in texts
    assert "ignore every prior instruction" not in texts
    assert "Per share USD\t(0.20)\t−0.50" in texts
    for span in record["spans"]:
        doc = next(doc for doc in record["documents"] if doc["filename"] == span["filename"])
        raw_body = RAW[doc["raw_start"] : doc["raw_end"]]
        assert filings.visible_text(raw_body) == doc["text"]
        assert doc["text"][span["start"] : span["end"]] == span["text"]
        lineage = {key: value for key, value in span.items() if key not in {"evidence_id", "text"}}
        assert canonical_sha256(lineage) == span["evidence_id"]


@pytest.mark.parametrize(
    ("json_value", "sgml_value", "index_value", "expected", "crosscheck"),
    [
        ("2024-10-31T16:30:25.000Z", "20241031163025", None,
         "2024-10-31T20:30:25+00:00", "eastern_clock_matches"),
        ("2024-10-31T20:30:25.000Z", None, "2024-10-31 16:30:25",
         "2024-10-31T20:30:25+00:00", "utc_matches"),
        ("2024-05-02T16:30:34.000Z", None, "2024-05-02 16:30:34",
         "2024-05-02T20:30:34+00:00", "eastern_clock_matches"),
        ("2024-01-02T16:30:00Z", "20240102163000", None,
         "2024-01-02T21:30:00+00:00", "eastern_clock_matches"),
        ("2024-01-02T20:30:00Z", "20240102203000", None,
         "2024-01-03T01:30:00+00:00", "eastern_clock_matches"),
    ],
)
def test_acceptance_resolution_vectors(json_value, sgml_value, index_value, expected, crosscheck):
    result = filings.resolve_acceptance(
        json_value=json_value,
        sgml_value=sgml_value,
        index_value=index_value,
        reference_received_at="2024-11-01T12:00:00Z",
    )
    assert result["accepted_at"] == expected
    assert result["event_at"] == result["published_at"] == expected
    assert result["json_crosscheck"] == crosscheck


def test_acceptance_requires_authoritative_crosscheck_and_consistent_references():
    pending = filings.resolve_acceptance(json_value="2024-05-02T20:30:34Z")
    assert pending["status"] == "acceptance_pending_crosscheck"
    assert pending["accepted_at"] is None
    with pytest.raises(ValueError, match="reference conflict"):
        filings.resolve_acceptance(
            sgml_value="20240502163034",
            index_value="2024-05-02 16:30:35",
        )
    with pytest.raises(ValueError, match="later than reference receipt"):
        filings.resolve_acceptance(
            sgml_value="20240502163034",
            reference_received_at="2024-05-02T20:30:33Z",
        )
    agreed = filings.resolve_acceptance(
        json_value="2024-05-02T12:00:00Z",
        sgml_value="20240502163034",
        index_value="2024-05-02 16:30:34",
    )
    assert agreed["reference"] == "sgml+index"
    assert agreed["json_crosscheck"] == "mismatch"
    invalid = filings.resolve_acceptance(
        json_value="not-a-timestamp",
        sgml_value="20240502163034",
    )
    assert invalid["json_crosscheck"] == "invalid_json_timestamp"


@pytest.mark.parametrize("when", ["20241103013000", "20240310023000"])
def test_ambiguous_and_nonexistent_eastern_acceptance_rejected(when):
    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        filings.acceptance_time(when)


def test_equivalent_raw_revisions_keep_content_identity_but_change_evidence():
    first = normalize()
    second = normalize(RAW.replace(b"<body>", b"<body><!-- revision -->"))
    assert first["normalized_sha256"] == second["normalized_sha256"]
    assert first["source_sha256"] != second["source_sha256"]
    assert first["spans"][0]["evidence_id"] != second["spans"][0]["evidence_id"]


@pytest.mark.parametrize(
    "name",
    ["../release.htm", "a%2fb.htm", "https://evil.test/a", "a?x=1", "a\\b", "a#x", "x..htm"],
)
def test_unsafe_names_rejected(name):
    with pytest.raises(ValueError, match="unsafe"):
        normalize(RAW.replace(b"release.htm", name.encode()))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"</DOCUMENT>", b""),
        (b"<DOCUMENT>", b"<DOCUMENT>\n<DOCUMENT>"),
        (b"<TYPE>EX-99.10", b"<TYPE>EX-99.1"),
        (b"<TYPE>EX-99.10", b"<TYPE>8-K"),
        (b"<TYPE>8-K", b"<TYPE>8-K\n<TYPE>8-K"),
        (b"<SEQUENCE>1", b"<SEQUENCE>bad"),
        (b"<FILENAME>release.htm", b"<FILENAME>primary.htm"),
        (b"CENTRAL INDEX KEY: 0000000123", b"CENTRAL INDEX KEY: 0000000456"),
        (b"ACCESSION NUMBER: 0000099999-26-000001", b"ACCESSION NUMBER: wrong"),
        (b"</SEC-DOCUMENT>", b""),
    ],
)
def test_malformed_or_ambiguous_source_is_rejected(old, new):
    with pytest.raises(ValueError):
        normalize(RAW.replace(old, new, 1))


def test_generic_exhibit_requires_explicit_press_release_label():
    generic = RAW.replace(b"<TYPE>EX-99.1\n", b"<TYPE>EX-99\n<DESCRIPTION>Press Release\n")
    record = normalize(generic)
    assert record["exhibit_status"] == "ex99_sole"
    assert any(span["filename"] == "release.htm" for span in record["spans"])

    unidentified = generic.replace(b"Press Release", b"Presentation")
    record = normalize(unidentified)
    assert record["exhibit_status"] == "absent"
    assert all(span["filename"] == "primary.htm" for span in record["spans"])

    indexed = normalize(unidentified, index_labels={"release.htm": "Press Release"})
    assert indexed["exhibit_status"] == "ex99_sole"


def test_exact_exhibit_wins_over_ex99_2_press_release():
    extra = RAW.replace(
        b"<TYPE>EX-99.10\n",
        b"<TYPE>EX-99.2\n<DESCRIPTION>Press Release\n",
    )
    record = normalize(extra)
    assert record["exhibit_status"] == "ex99_1"
    generic = next(candidate for candidate in record["document_candidates"]
                   if candidate["type"] == "EX-99.2")
    assert generic["selection_reason"] == "not_selected"
    exact = next(candidate for candidate in record["document_candidates"]
                 if candidate["type"] == "EX-99.1")
    assert exact["selection_reason"] == "ex99_1"
    assert "wrong exhibit" not in "\n".join(span["text"] for span in record["spans"])


def test_amendment_all_items_and_registered_precedence():
    raw = RAW.replace(b"<TYPE>8-K\n", b"<TYPE>8-K/A\n", 1)
    raw = raw.replace(b"<b>Item <span>2.02</span></b>", b"Item 1.01")
    raw = raw.replace(
        b"<div>Item 7.01 Regulation FD</div>",
        b"<div>Item 2.01 Acquisition</div>\n"
        b"<div>Item 5.02 Management</div>\n"
        b"<div>Item 8.01 Other Events</div>",
    )
    record = normalize(raw)
    assert record["items"] == ["1.01", "2.01", "5.02", "8.01"]
    assert record["primary_event_kind"] == "acquisition_disposition"


def test_metadata_does_not_invent_readable_sections():
    raw = RAW.replace(b"Item <span>2.02</span>", b"Heading").replace(b"Item 7.01", b"Heading")
    record = normalize(raw, metadata_items=("2.02",))
    assert record["item_disagreement"]
    assert record["status"] == "extraction_unavailable"
    pdf = normalize(RAW.replace(b"release.htm", b"release.pdf"))
    assert pdf["status"] == "unsupported_format"
    assert pdf["exhibit_status"] == "ex99_1"


def test_truncation_omits_a_complete_table_row():
    filler = b"<p>" + b"x" * 31_750 + b"</p>\n"
    partial_row = (
        b"<tr><td>EARLY-CELL</td><td><p>" + b"y" * 500
        + b"</p></td><td>LATE-CELL</td></tr>\n"
    )
    raw = RAW.replace(b"<table>", filler + b"<table>" + partial_row)
    record = normalize(raw)
    assert record["truncated"] and record["omitted_spans"]
    exhibit = next(span for span in record["spans"] if span["filename"] == "release.htm")
    assert len(exhibit["text"]) <= 32_000
    assert "EARLY-CELL" not in exhibit["text"]
    assert "LATE-CELL" not in exhibit["text"]
    assert "GAAP diluted EPS" not in exhibit["text"]
    assert "Current synthetic" not in exhibit["text"]
    assert not exhibit["text"].endswith("\t")
    with pytest.raises(ValueError, match="receipt limit"):
        normalize(b"x" * (filings.MAX_BYTES + 1))


def test_scope_preserves_share_classes_and_ignores_newer_unrelated_rows():
    rows = [
        {"cik": "123", "ticker": ticker, "security_id": security, "available_at": RECEIVED}
        for ticker, security in [("SYN.A", "class-a"), ("SYN.B", "class-b")]
    ]
    rows.append(
        {"cik": "456", "ticker": "OTHER", "security_id": "other",
         "available_at": "2026-09-25T20:32:00Z"}
    )
    options = {"rows": rows, "universe": {"SYN-A", "SYN.B"},
               "cutoff_at": "2026-09-25T20:33:00Z"}
    mapped = filings.map_cik_scope("123", aliases={"SYN.A": "SYN-A"}, **options)
    assert [row["security_id"] for row in mapped["securities"]] == ["class-a", "class-b"]

    rows.append({"cik": "456", "ticker": "SYN.B", "security_id": "conflict",
                 "available_at": RECEIVED})
    assert filings.map_cik_scope("123", **options)["status"] == "ambiguous"


def test_scope_does_not_backfill_removed_classes():
    rows = [
        {"cik": "123", "ticker": "OLD", "security_id": "old",
         "available_at": "2026-09-24T20:31:00Z"},
        {"cik": "123", "ticker": "NEW", "security_id": "new", "available_at": RECEIVED},
    ]
    scope = filings.map_cik_scope("123", rows=rows, universe={"OLD"}, cutoff_at=RECEIVED)
    assert scope["status"] == "outside_universe"
    assert scope["securities"] == []


def test_volume_fraction_uses_scheduled_early_close_and_clamps():
    schedule = {
        "opens_at": "2026-11-27T09:30:00-05:00",
        "closes_at": "2026-11-27T13:00:00-05:00",
    }
    assert filings.session_volume_fraction("2026-11-27T11:15:00-05:00", **schedule) == 0.5
    assert filings.session_volume_fraction("2026-11-27T09:00:00-05:00", **schedule) == 0
    assert filings.session_volume_fraction("2026-11-27T14:00:00-05:00", **schedule) == 1
    with pytest.raises(ValueError, match="invalid session schedule"):
        filings.session_volume_fraction(RECEIVED, opens_at=RECEIVED, closes_at=RECEIVED)


def test_exact_company_names_are_casefolded_and_ambiguous_names_fail():
    names = {
        "SYN": "Synthetic Widgets",
        "OTHER": "Other Synthetic",
        "CLASS.A": "Dual Class",
        "CLASS.B": "Dual Class",
    }
    assert filings.match_company_names("SYNTHETIC WIDGETS reports results", names=names) == ["SYN"]
    assert filings.match_company_names("Synthetic Widgetsmith and Dual Class", names=names) == []
