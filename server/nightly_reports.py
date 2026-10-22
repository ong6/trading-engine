"""Validate generated nightly screen and paper-league reports."""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, datetime, time, timezone
from itertools import zip_longest
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from engine.lib.util import table_exists

from .file_utils import MAX_OPERATIONAL_FILE_BYTES, read_text

_SCREEN_REPORT_HEADER = re.compile(
    r"^# Screen — (?P<date>\d{4}-\d{2}-\d{2})  "
    r"\(universe: (?P<screened>\d+) · passing: (?P<passing>\d+) · "
    r"new today: (?P<new>\d+) · regime: (?P<regime>[^ ]+) · "
    r"policy: (?P<policy>[^)]+)\)$"
)
_LEAGUE_TABLE_HEADER = (
    "| # | Portfolio | Inception | Equity | Total ret | vs SPY | Max DD | "
    "Open | Fills | Last 5d |"
)
_LEAGUE_TABLE_SEPARATOR = "|---|---|---|---|---|---|---|---|---|---|"
_STALE_MARKS_TABLE_HEADER = (
    "| Book | Ticker | Qty | Last traded | Sessions stale | Frozen value | % of equity |"
)
_STALE_MARKS_TABLE_SEPARATOR = "|---|---|---|---|---|---|---|"
_PORTFOLIO_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
EQUITY_SCAN_BATCH_SIZE = 256
MAX_REPORT_FILE_BYTES = MAX_OPERATIONAL_FILE_BYTES
_MISSING_ROW = object()


def _public_portfolio_ids(con: duckdb.DuckDBPyConnection) -> list[str]:
    if not table_exists(con, "portfolio_accounts_v"):
        return [row[0] for row in con.execute(
            "SELECT id FROM portfolios ORDER BY id"
        ).fetchall()]
    return [row[0] for row in con.execute(
        "SELECT portfolio_id FROM portfolio_accounts_v "
        "WHERE pa_visibility='public' ORDER BY portfolio_id"
    ).fetchall()]


class EvidenceState(Exception):
    """Signal an expected non-current report state to the nightly projector."""

    def __init__(self, status: str, reason: str) -> None:
        self.payload = {"status": status, "reason": reason}
        super().__init__(reason)


def _league_portfolio_names(text: str) -> list[str]:
    """Extract the current-book names from the generated league standings."""
    lines = text.splitlines()
    headers = [i for i, line in enumerate(lines) if line == _LEAGUE_TABLE_HEADER]
    if len(headers) != 1:
        raise ValueError("league report must contain exactly one standings table")
    header = headers[0]
    if header + 1 >= len(lines) or lines[header + 1] != _LEAGUE_TABLE_SEPARATOR:
        raise ValueError("league report standings separator is invalid")

    portfolio_names: list[str] = []
    line_index = header + 2
    while line_index < len(lines) and lines[line_index].startswith("|"):
        cells = [cell.strip() for cell in lines[line_index].strip("|").split("|")]
        if len(cells) != 10 or cells[0] != str(len(portfolio_names) + 1):
            raise ValueError("league report standings row is malformed")
        if not cells[1]:
            raise ValueError("league report portfolio name is empty")
        portfolio_names.append(cells[1])
        line_index += 1
    if not portfolio_names:
        raise ValueError("league report standings table is empty")
    if len(portfolio_names) != len(set(portfolio_names)):
        raise ValueError("league report contains duplicate portfolio names")
    return portfolio_names


def _league_stale_positions(text: str) -> list[tuple[str, str]]:
    """Extract stale-mark identities so archived exposure cannot leak into the report."""
    lines = text.splitlines()
    headers = [i for i, line in enumerate(lines) if line == _STALE_MARKS_TABLE_HEADER]
    if not headers:
        return []
    if len(headers) != 1:
        raise ValueError("league report contains duplicate stale-mark tables")
    header = headers[0]
    if header + 1 >= len(lines) or lines[header + 1] != _STALE_MARKS_TABLE_SEPARATOR:
        raise ValueError("league report stale-mark separator is invalid")

    positions: list[tuple[str, str]] = []
    line_index = header + 2
    while line_index < len(lines) and lines[line_index].startswith("|"):
        cells = [cell.strip() for cell in lines[line_index].strip("|").split("|")]
        if len(cells) != 7 or _PORTFOLIO_ID.fullmatch(cells[0]) is None or not cells[1]:
            raise ValueError("league report stale-mark row is malformed")
        positions.append((cells[0], cells[1]))
        line_index += 1
    if not positions:
        raise ValueError("league report stale-mark table is empty")
    if len(positions) != len(set(positions)):
        raise ValueError("league report contains duplicate stale marks")
    return positions


def _validate_screen(
    meta: dict,
    latest: date,
    summary: tuple[int, int, int, str],
    data_dir: Path,
) -> None:
    screen_count, passing_count, new_count, policy = summary
    dated_text = read_text(
        data_dir / "screens" / f"{latest.isoformat()}.md",
        max_bytes=MAX_REPORT_FILE_BYTES,
        label="nightly report",
    )
    latest_text = read_text(
        data_dir / "screens" / "latest.md",
        max_bytes=MAX_REPORT_FILE_BYTES,
        label="nightly report",
    )
    match = _SCREEN_REPORT_HEADER.fullmatch(dated_text.splitlines()[0])
    if latest_text != dated_text:
        raise ValueError("latest screen report differs from dated report")
    if match is None:
        raise ValueError("screen report header is invalid")
    expected = (
        latest.isoformat(),
        screen_count,
        passing_count,
        new_count,
        policy,
        meta.get("regime"),
    )
    published = (
        match["date"],
        int(match["screened"]),
        int(match["passing"]),
        int(match["new"]),
        match["policy"],
        match["regime"],
    )
    if published != expected:
        raise ValueError("screen report does not match stored evidence")


def _retired_after_session(con: duckdb.DuckDBPyConnection, latest: date) -> dict[str, str]:
    """{id: name} of books marked for ``latest`` and retired after that session's close.

    The report for ``latest`` was written while they were active, so listing them stays
    correct until the next session's report drops them. A book retired before the close,
    or inactive without a ``portfolio_retired`` audit row, is not excused.
    """
    if not table_exists(con, "audit_log"):
        return {}
    close = datetime.combine(latest, time(16), ZoneInfo("America/New_York"))
    return dict(con.execute(
        """
        SELECT p.id, ANY_VALUE(p.name)
        FROM portfolios p
        JOIN sim_equity e ON e.portfolio_id = p.id AND e.date = ?
        JOIN audit_log a ON a.action = 'portfolio_retired'
         AND json_extract_string(a.payload, '$.portfolio_id') = p.id
        WHERE NOT p.active
        GROUP BY p.id
        HAVING MIN(a.ts) > ?
        """,
        [latest, close.astimezone(timezone.utc).replace(tzinfo=None)],
    ).fetchall())


def _expected_league_books(
    con: duckdb.DuckDBPyConnection, latest: date, pending: tuple[str, ...] = (),
    published: tuple[str, ...] = (),
) -> dict[str, str]:
    """{id: name} of the public books the ``latest`` standings must list.

    A book retired after ``latest`` closed is expected only when ``published`` lists it.
    """
    # The league lists a book its publisher has not yet marked for ``latest`` at its
    # prior mark (flagged ‡), so a pending book is expected without a ``latest`` row.
    public_ids = set(_public_portfolio_ids(con))
    books = {
        row[0]: row[1]
        for row in con.execute(
            """
            SELECT p.id, p.name, e.portfolio_id IS NOT NULL
            FROM portfolios p
            LEFT JOIN sim_equity e ON e.portfolio_id = p.id AND e.date = ?
            WHERE p.active
            ORDER BY p.name
            """,
            [latest],
        ).fetchall()
        if row[0] in public_ids and (row[2] or row[0] in pending)
    }
    books.update({book_id: name for book_id, name in _retired_after_session(con, latest).items()
                  if book_id in public_ids and name in published})
    if len(books) != len(set(books.values())):
        raise ValueError("active portfolio names are not unique")
    return books


def _active_ids(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("SELECT id FROM portfolios WHERE active").fetchall()}


def _expected_stale_positions(
    con: duckdb.DuckDBPyConnection, latest: date, retired_listed: tuple[str, ...] = ()
) -> list[tuple[str, str]]:
    """Stale marks of the active public books and of ``retired_listed`` books."""
    public_ids = set(_public_portfolio_ids(con))
    return [row for row in con.execute(
        """
        SELECT pos.portfolio_id, pos.ticker
        FROM sim_positions pos
        JOIN portfolios p ON p.id = pos.portfolio_id
        JOIN prices pr ON pr.ticker = pos.ticker
        WHERE (p.active OR list_contains(?, p.id)) AND pos.qty > 0
        GROUP BY pos.portfolio_id, pos.ticker, pos.qty
        HAVING MAX(pr.date) FILTER (WHERE pr.volume > 0) < ?
        ORDER BY pos.portfolio_id, pos.ticker
        """,
        [list(retired_listed), latest],
    ).fetchall() if row[0] in public_ids]


def _validate_league_markdown(
    con: duckdb.DuckDBPyConnection,
    latest: date,
    data_dir: Path,
    pending: tuple[str, ...] = (),
) -> None:
    league_text = read_text(
        data_dir / "reports" / "league.md",
        max_bytes=MAX_REPORT_FILE_BYTES,
        label="nightly report",
    )
    if league_text.splitlines()[0] != f"# Paper League — {latest.isoformat()}":
        raise EvidenceState("stale", "league-report-behind")
    published_names = _league_portfolio_names(league_text)
    books = _expected_league_books(con, latest, pending, tuple(published_names))
    if sorted(published_names) != sorted(books.values()):
        raise ValueError("league report portfolios do not match active equity")

    published_stale = _league_stale_positions(league_text)
    retired_listed = tuple(sorted(set(books) - _active_ids(con)))
    if sorted(published_stale) != _expected_stale_positions(con, latest, retired_listed):
        raise ValueError("league report stale marks do not match active exposure")


def _validate_league_csv(con: duckdb.DuckDBPyConnection, data_dir: Path) -> None:
    public_ids = _public_portfolio_ids(con)
    if public_ids:
        placeholders = ",".join("?" for _ in public_ids)
        cursor = con.execute(
            "SELECT portfolio_id,date,equity FROM sim_equity "
            f"WHERE portfolio_id IN ({placeholders}) ORDER BY portfolio_id,date",
            public_ids,
        )
    else:
        cursor = con.execute(
            "SELECT portfolio_id,date,equity FROM sim_equity WHERE FALSE"
        )

    def expected_rows():
        while batch := cursor.fetchmany(EQUITY_SCAN_BATCH_SIZE):
            yield from batch

    csv_text = read_text(
        data_dir / "reports" / "league.csv",
        max_bytes=MAX_REPORT_FILE_BYTES,
        label="nightly report",
    )
    with io.StringIO(csv_text, newline="") as handle:
        published_rows = csv.DictReader(handle)
        for published, expected in zip_longest(
            published_rows, expected_rows(), fillvalue=_MISSING_ROW
        ):
            if published is _MISSING_ROW or expected is _MISSING_ROW:
                raise ValueError("league CSV row count does not match stored equity")
            portfolio_id, equity_date, equity = expected
            identity = {
                "portfolio_id": portfolio_id,
                "date": equity_date.isoformat(),
                "equity": published.get("equity"),
            }
            if published != identity or not math.isclose(
                float(published["equity"]), float(equity), rel_tol=1e-12
            ):
                raise ValueError("league CSV does not match stored equity")


def validate(
    meta: dict,
    latest: date,
    summary: tuple[int, int, int, str],
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    *,
    pending: tuple[str, ...] = (),
) -> None:
    """Require generated screen and league reports to match their source state.

    ``pending`` names active books whose ``latest`` mark is not yet due from their
    publisher; the caller has already checked each one is marked through the prior
    session, which is how the league renders it.
    """
    _validate_screen(meta, latest, summary, data_dir)
    _validate_league_markdown(con, latest, data_dir, pending)
    _validate_league_csv(con, data_dir)
