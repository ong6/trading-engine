"""Recorded provider responses replayed through the public ingest entry points."""
from __future__ import annotations

import inspect
import json
from datetime import date

import pytest

from engine import free_sources
from tools import free_sources as capture
from tools import provider_contracts as contracts

FIXTURES = contracts.FIXTURES_DIR
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())
# Items the replay still fails on this branch, each owned by another fix branch. Merging
# fix/massive-options-delayed-status empties this set and turns the strict xfail into a pass.
KNOWN_OPEN = {"massive_option_daily_delayed"}
DELAYED_OPEN = pytest.mark.xfail(
    "massive_option_daily_delayed" in KNOWN_OPEN, strict=True,
    raises=free_sources.FreeSourceError,
    reason="free-tier DELAYED option bars are rejected until the delayed-status fix lands",
)


@pytest.mark.parametrize("name", sorted(set(contracts.PROVIDER_CASES) - KNOWN_OPEN))
def test_recorded_provider_case_replays(name, tmp_path):
    assert contracts.PROVIDER_CASES[name](FIXTURES, tmp_path)


@DELAYED_OPEN
def test_recorded_delayed_option_daily_bars_load(tmp_path):
    assert contracts.case_massive_option_daily_delayed(FIXTURES, tmp_path) == "4 DELAYED bars"


def test_free_tier_option_daily_status_is_delayed_and_contracts_ok():
    options = MANIFEST["options"]
    daily = json.loads((FIXTURES / options["daily"]["file"]).read_bytes())
    pages = [json.loads((FIXTURES / page["file"]).read_bytes()) for page in options["contracts"]]

    assert daily["status"] == options["daily"]["status"] == "DELAYED"
    assert {page["status"] for page in pages} == {"OK"}


def test_split_chain_length_fits_the_page_bound():
    splits = MANIFEST["splits"]
    default = inspect.signature(capture.capture_massive_splits).parameters["max_pages"].default

    # Two full recorded pages, the second still pointing on: at least three pages exist.
    assert [page["source_rows"] for page in splits["pages"]] == [free_sources.MAX_SPLIT_RESULTS] * 2
    assert all(page["has_next_url"] for page in splits["pages"])
    assert splits["chain_length_lower_bound"] == 3
    assert default == capture.MASSIVE_SPLIT_PAGE_CAP >= splits["chain_length_lower_bound"]


def test_ohlc_geometry_share_stays_inside_the_reject_budget():
    archive = MANIFEST["grouped_daily_archive"]
    spec = MANIFEST["grouped_daily"]
    body = (FIXTURES / spec["file"]).read_bytes()
    rows, rejects = free_sources.parse_massive_grouped_daily_with_rejects(
        body, date.fromisoformat(spec["session_date"])
    )
    outside = [row for row in rows if not row["l"] <= row["vwap"] <= row["h"]]

    assert archive["rows"] > 0 and archive["invalid_numbers"] == 0
    assert archive["max_day_ohlc_share"] <= free_sources.MASSIVE_MAX_REJECTED_SHARE
    # Consolidated VWAP sits outside the regular-session high-low on up to ~9% of a day's
    # bars, above the 5% reject budget: it must never become a geometry reject.
    assert archive["max_day_vwap_outside_share"] > free_sources.MASSIVE_MAX_REJECTED_SHARE
    assert len(outside) == spec["vwap_outside_high_low"] > 0
    assert len(rejects) == spec["ohlc_violations"]


def test_replay_of_this_checkout_fails_only_on_known_open_items():
    results = contracts.replay(contracts.REPO_ROOT)

    assert set(results) == {*contracts.PROVIDER_CASES, "runtime_environment"}
    assert {name for name, result in results.items() if not result["ok"]} == KNOWN_OPEN
