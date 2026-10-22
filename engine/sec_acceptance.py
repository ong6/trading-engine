"""EDGAR acceptance clocks and the conservative availability rule.

SEC's ``acceptanceDateTime`` in the submissions JSON (nightly bulk ZIP and the
live API) carries a ``Z`` suffix, but the value is not reliably UTC. Against
the SGML header ``<ACCEPTANCE-DATETIME>`` (Eastern wall time, identical to the
filing index "Accepted" field), the label's wall clock has been observed equal
to the true Eastern time, to true UTC, and to Eastern time plus twice the New
York offset, varying by filing and even by the CIK listing of one accession.
It has never been observed earlier than the true acceptance.

The rule every engine path uses:

1. A filing's SGML header acceptance, read as America/New_York, is the
   acceptance instant whenever it is available.
2. Otherwise the JSON label's wall clock is read as America/New_York and its
   ``Z`` is ignored. That instant is at or after the true acceptance under
   every observed convention (late by 0, 4-5 or 8-10 hours).
3. When the label came in a response received at a known instant, the filing
   was accepted no later than that receipt, so the instant is capped there.

Wall clocks that are ambiguous or skipped at a daylight-saving change resolve
to the later of the two readings, which keeps rule 2 conservative.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SGML_CLOCK = re.compile(r"^[0-9]{14}$")


def _later_eastern(wall: datetime) -> datetime:
    """Read a naive wall clock as New York time, taking the later DST reading."""
    readings = (wall.replace(tzinfo=ET, fold=fold).astimezone(timezone.utc) for fold in (0, 1))
    return max(readings)


def sgml_acceptance(value: str) -> datetime:
    """Return the UTC instant of an SGML ``ACCEPTANCE-DATETIME`` (Eastern wall time)."""
    if not isinstance(value, str) or SGML_CLOCK.fullmatch(value) is None:
        raise ValueError("SGML acceptance must be 14 digits")
    return _later_eastern(datetime.strptime(value, "%Y%m%d%H%M%S"))


def label_wall_clock(label: str) -> datetime:
    """Return the naive wall clock written in a JSON ``acceptanceDateTime`` label."""
    if not isinstance(label, str) or not label.strip():
        raise ValueError("acceptance label is empty")
    parsed = datetime.fromisoformat(label.strip().replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("acceptance label has no zone designator")
    return parsed.replace(tzinfo=None)


def label_available_at(label: str, *, received_at: datetime | None = None) -> datetime:
    """Conservative availability of a JSON acceptance label (rules 2 and 3)."""
    instant = _later_eastern(label_wall_clock(label))
    if received_at is not None:
        if received_at.utcoffset() is None:
            raise ValueError("receipt time must be timezone-aware")
        instant = min(instant, received_at.astimezone(timezone.utc))
    return instant


def available_at(
    *, sgml: str | None = None, label: str | None = None,
    received_at: datetime | None = None,
) -> datetime | None:
    """Apply the rule: SGML header first, then the capped conservative label."""
    if sgml is not None:
        return sgml_acceptance(sgml)
    if label in {None, ""}:
        return None
    return label_available_at(label, received_at=received_at)
