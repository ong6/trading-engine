"""Repository documentation integrity checks."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote

from engine.lib.db import MARKET_DATE_MIN_COVERAGE, MARKET_DATE_MIN_NAMES
from server.driver_monitor import DRIVER_SCHEDULES
from server.risk import RISK_CONTROL_NAMES
from server.scheduler_monitor import expected_auxiliary_cron_entries, expected_cron_entries

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTATION_TREES = ("archive", "data", "docs", "ui")
IGNORED_PARTS = frozenset(
    {
        ".git",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
URI_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
ATX_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*$")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
BUILDLOG_TAIL_MARKER = "<!-- append-only-tail: insert new verified entries immediately above this line -->"


def _markdown_files(root: Path = REPO_ROOT) -> list[Path]:
    candidates = list(root.glob("*.md"))
    for tree_name in DOCUMENTATION_TREES:
        tree = root / tree_name
        if tree.is_dir():
            candidates.extend(tree.rglob("*.md"))

    return sorted(
        path for path in candidates if not IGNORED_PARTS.intersection(path.relative_to(root).parts)
    )


def test_buildlog_recent_records_are_ordered_and_end_at_unique_tail_marker():
    legacy = (REPO_ROOT / "docs" / "history" / "buildlog-2026-07-15-to-2026-09-17.md").read_text()
    buildlog = (REPO_ROOT / "BUILDLOG.md").read_text()
    markers = (
        "- Completed the structured local-upstream boundary.",
        "- Bounded host-probe cleanup no longer contains an unbounded reap after failure.",
        "- Tightened the final source-control machine-output boundary.",
        "- Closed the remaining Git diagnostic-output ambiguity",
        "- Made scheduler host-state classification fail closed",
        "- Made failed host-probe cleanup best-effort and non-throwing.",
        "- Made source-control status one coherent optimistic snapshot.",
        "- Bounded the complete source-control snapshot to one command budget.",
        "- Consolidated host-projection deadlines into one shared command-budget primitive.",
        "- Made scheduler status one coherent optimistic snapshot.",
        "- Bound scheduler snapshot coherence to launch and log identities.",
        "- Recorded the final identity-aware scheduler deployment handoff.",
        "- Corrected cross-distribution cron-unit discovery",
        "- API-only deployment of the load-state-aware scheduler probe",
        "- Closed shell-grammar gaps in scheduler duplicate detection",
        "- API-only deployment of the shell- and cron-aware duplicate detector",
        "- Tightened the atomic systemd service observation",
        "- Final deployment of the coherent systemd-state invariant",
        "- Hardened scheduled-driver log interpretation at the final run boundary.",
        "- Deployed the hardened driver-log reader and matching browser contract.",
        "- Hardened the inaugural Sunday liquidity-evidence transition",
        "- Deployed the exact liquidity-evidence producer/consumer boundary",
        "- Bound the strict liquidity-evidence schema to explicit producer and browser vocabularies.",
        "- Deployed the parity-locked liquidity contract.",
        "- Closed a remaining liquidity-result honesty gap",
        "- Deployed the backfill-aware liquidity evidence projection.",
        "- Reconciled the undated documentation map, strategy decision ledger, and continuation handoff",
        "- 2026-09-13 · The first independent Sunday liquidity refresh",
        "- Reconciled all 69 failures against the cached 13,214-row Nasdaq directory.",
        "- Because `engine/universe.py` is inside the XS prospective source boundary, explicitly migrated",
        "- Final verification passes all 2,205 warnings-as-errors Python tests",
        "- 2026-09-13 · Closed the universe publisher's mixed-state failure window.",
        "- Explicitly migrated the unchanged zero-observation XS checkpoint from runtime-contract v12 to",
        "- Closed an intermittent release-manifest race exposed by the full suite.",
        "- Final verification passes all **2,210 warnings-as-errors Python tests**",
        "- Deployed the v13 runtime to API PID 2899879; UI remains PID 2444365.",
        "- The identity snapshot taken immediately before this identity-record line had manifest identity",
        "- Clarified the disconnect-safe automation boundary against current official Codex guidance",
        "- Final verification after that documentation-contract change passes all **2,212 collected Python",
        "- Removed the final two production `assert` statements from the support/API layer",
        "- The final **2,215-test warnings-as-errors Python suite** passes",
        "- Removed the remaining replay-runtime assertion from `farm/backtest/replay.py`.",
        "- Replaced all 22 removable assertions in the standalone corporate-actions shakedown",
        "- Final verification passes all **2,221 warnings-as-errors Python tests**",
        "- Closed the failure-path DuckDB handles exposed by the new explicit replay/proof guards.",
        "- Final verification after the connection-ownership correction passes all **2,227",
        "- Applied the same exception-safe ownership rule to the scheduled walk-forward runner.",
        "- Final verification after walk-forward ownership hardening passes all **2,228",
        "- Closed the remaining success-only DuckDB handles in the historical proof drivers.",
        "- Final verification after proof-driver ownership hardening passes all **2,235",
        "- Extended exception-safe DuckDB ownership through the remaining non-frozen command-line",
        "- Final verification after the command-line ownership pass has all **2,241",
        "- Closed the final two owned runtime connection gaps with explicit prospective-contract",
        "- Final verification after the explicit v5/v14 migrations has all **2,243",
        "- Replaced the remaining direct writes of published runtime artifacts with the shared",
        "- Final verification after atomic publication and the explicit v6/v15 migrations has all **2,245",
        "- Closed the companion-artifact recovery gap after committed screen and league runs.",
        "- Final verification after the explicit v7/v16 migrations has all **2,246",
        "- Removed the remaining unattended path that could recompute committed append-only screen rows.",
        "- Final verification after the explicit XS v17 migration has all **2,248",
        "- Removed the screener's last accidental borrowed-connection close.",
        "- Final verification after the explicit XS v18 migration has all **2,249",
        "- Made every temporary DuckDB DataFrame registration exception-safe.",
        "- Final verification after the explicit v8/v19/v5 migrations has all **2,253",
        "- Made the signal breadth reader's temporary universe exception-safe.",
        "- Final verification after breadth temporary-state cleanup has all **2,254",
        "- Made historical-screen temporary tables call-scoped on every exit.",
        "- Final verification after historical-screen temporary-state cleanup has all **2,255",
        "- Centralized every explicit production DuckDB transaction.",
        "- Final verification after interruption-safe transaction cleanup has all **2,259",
        "- Locked the atomic-publication boundary against direct production path writes.",
        "- Final verification after the atomic-publication source guard has all **2,260",
        "- Made the next evidence-authorized strategy actions explicit.",
    )

    assert [legacy.count(marker) for marker in markers] == [1] * len(markers)
    offsets = [legacy.index(marker) for marker in markers]
    assert offsets == sorted(offsets)
    assert buildlog.count(BUILDLOG_TAIL_MARKER) == 1
    assert buildlog.endswith(f"{BUILDLOG_TAIL_MARKER}\n")


def _github_heading_slug(title: str) -> str:
    """Approximate GitHub's Unicode-aware heading IDs for local link checks."""
    title = re.sub(r"[ \t]+#+[ \t]*$", "", title)
    title = re.sub(r"\[([^]]*)\]\([^)]*\)", r"\1", title)
    title = re.sub(r"<[^>]*>", "", title)
    normalized = []
    for character in title.strip().lower():
        category = unicodedata.category(character)
        if character.isspace():
            normalized.append("-")
        elif category[0] in {"L", "N"} or character in {"-", "_"}:
            normalized.append(character)
    return "".join(normalized)


def _without_fenced_code(text: str) -> str:
    """Blank fenced blocks while preserving source offsets and line numbers."""
    visible: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines(keepends=True):
        fence = FENCE_OPEN.match(line)
        if fence:
            marker = fence.group(1)
            suffix = fence.group(2).rstrip("\r\n")
            if fence_character is None and (marker[0] == "~" or "`" not in suffix):
                fence_character = marker[0]
                fence_length = len(marker)
            elif (
                marker[0] == fence_character
                and len(marker) >= fence_length
                and not suffix.strip()
            ):
                fence_character = None
                fence_length = 0
        if fence_character is not None or fence:
            visible.append("".join(character if character in "\r\n" else " " for character in line))
        else:
            visible.append(line)
    return "".join(visible)


def _markdown_heading_fragments(text: str) -> set[str]:
    fragments: set[str] = set()
    occurrences: dict[str, int] = {}
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines():
        fence = FENCE_OPEN.match(line)
        if fence:
            marker = fence.group(1)
            suffix = fence.group(2)
            if fence_character is None and (marker[0] == "~" or "`" not in suffix):
                fence_character = marker[0]
                fence_length = len(marker)
            elif (
                marker[0] == fence_character
                and len(marker) >= fence_length
                and not suffix.strip()
            ):
                fence_character = None
                fence_length = 0
            continue
        if fence_character is not None:
            continue
        heading = ATX_HEADING.match(line)
        if not heading:
            continue
        base = _github_heading_slug(heading.group(1))
        occurrence = occurrences.get(base, 0)
        occurrences[base] = occurrence + 1
        fragments.add(base if occurrence == 0 else f"{base}-{occurrence}")
    return fragments


def _markdown_link_errors(root: Path) -> tuple[int, list[str]]:
    missing: list[str] = []
    checked = 0
    fragment_cache: dict[Path, set[str]] = {}

    for source in _markdown_files(root):
        text = source.read_text(errors="replace")
        visible_text = _without_fenced_code(text)
        for match in MARKDOWN_LINK.finditer(visible_text):
            raw_target = match.group(1).strip()
            if raw_target.startswith("<") and raw_target.endswith(">"):
                raw_target = raw_target[1:-1]
            target, separator, fragment = raw_target.partition("#")
            if URI_SCHEME.match(target):
                continue

            checked += 1
            resolved = source if not target else (source.parent / unquote(target)).resolve()
            problem = not resolved.exists() or not resolved.is_relative_to(root.resolve())
            if not problem and separator and resolved.is_file() and resolved.suffix.lower() == ".md":
                fragments = fragment_cache.setdefault(
                    resolved,
                    _markdown_heading_fragments(resolved.read_text(errors="replace")),
                )
                problem = unquote(fragment) not in fragments
            if problem:
                line = text.count("\n", 0, match.start()) + 1
                relative_source = source.relative_to(root)
                missing.append(f"{relative_source}:{line}: {raw_target}")

    return checked, missing


def test_markdown_discovery_is_limited_to_repository_owned_documentation(tmp_path: Path):
    expected = {
        tmp_path / "README.md",
        tmp_path / "archive" / "history.md",
        tmp_path / "data" / "reports" / "result.md",
        tmp_path / "docs" / "guide.md",
        tmp_path / "ui" / "README.md",
    }
    excluded = {
        tmp_path / "trading_engine-0.1.0" / "README.md",
        tmp_path / "unowned" / "notes.md",
        tmp_path / "docs" / "build" / "copied.md",
        tmp_path / "ui" / ".next" / "generated.md",
        tmp_path / "ui" / "node_modules" / "dependency.md",
    }
    for path in expected | excluded:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n")

    assert set(_markdown_files(tmp_path)) == expected


def test_local_markdown_links_resolve():
    checked, missing = _markdown_link_errors(REPO_ROOT)

    assert checked, "no local Markdown links were discovered"
    assert not missing, "missing local Markdown targets:\n" + "\n".join(missing)


def test_local_markdown_link_check_validates_fragments_and_ignores_fenced_headings(
    tmp_path: Path,
):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text(
        "# Measured cost — 2026\n\n## Repeated\n## Repeated\n\n"
        "```md\n## Hidden\n```not-a-close\n## Still hidden\n````\n"
    )
    (docs / "index.md").write_text(
        "[valid](target.md#measured-cost--2026)\n"
        "[duplicate](target.md#repeated-1)\n"
        "```md\n[backtick example](missing-backtick.md)\n"
        "```not-a-close\n[still fenced](missing-after-false-close.md)\n````\n"
        "~~~md\n[tilde example](missing-tilde.md)\n~~~\n"
        "[missing](target.md#hidden)\n"
    )

    checked, missing = _markdown_link_errors(tmp_path)

    assert checked == 3
    assert missing == ["docs/index.md:11: target.md#hidden"]


def test_contributor_recovery_guide_matches_anchored_publication_contract():
    guide = " ".join((REPO_ROOT / "CONTRIBUTING.md").read_text().split())

    assert "retains one no-follow descriptor" in guide
    assert "atomic no-replace semantics relative to the descriptor" in guide
    assert "without writing into the replacement" in guide
    assert "preserving the verified bundle in the original directory" in guide
    assert "database leaf without following symlinks" in guide
    assert "DuckDB copies and identifies its schema through the retained file descriptor" in guide
    assert "match the requested source pathname before and after publication" in guide
    assert "visible no-follow parent chain" in guide
    assert "detection after publication reports failure" in guide


def test_current_risk_documentation_matches_runtime_contract():
    current_docs = (
        REPO_ROOT / "docs" / "how-it-works.md",
        REPO_ROOT / "docs" / "design" / "trading-execution-design.md",
    )
    for path in current_docs:
        text = path.read_text()
        assert f"{len(RISK_CONTROL_NAMES)}" in text, path
        missing = [name for name in RISK_CONTROL_NAMES if f"`{name}`" not in text]
        assert not missing, f"{path}: missing risk controls: {missing}"


def test_current_market_date_documentation_matches_runtime_contract():
    current_docs = (
        REPO_ROOT / "docs" / "how-it-works.md",
        REPO_ROOT / "docs" / "design" / "trading-engine-design.md",
    )
    coverage = f"{MARKET_DATE_MIN_COVERAGE:.0%}"
    minimum_names = f"{MARKET_DATE_MIN_NAMES:,}"
    for path in current_docs:
        text = path.read_text()
        assert coverage in text, path
        assert minimum_names in text, path
        assert "breadth-qualified" in text, path

    how = current_docs[0].read_text()
    assert "`GET /screen/latest` projection is independently capped" in how
    assert "`GET /screen/{run_date}` remains an explicit archival lookup" in how


def test_current_operator_guide_separates_live_price_evidence_from_dated_incident():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "dated 2026-09-05 incident record" in how
    assert "`price_verification` and `price_quarantines` fields are authoritative" in how
    assert "detail's exact five-field public envelope" in how
    assert "missing confirmation timestamp" in how
    assert "worst-first disagreement records under an exact 20-item limit" in how
    assert "recompute each basis-point gap from the two published prices" in how
    assert "contradictory labels are rejected rather than displayed" in how
    assert "complete disagreement count and an explicit truncation flag" in how
    assert "relative, absolute-dollar, and material thresholds are published" in how
    assert (
        "Malformed, duplicated, future-dated, non-finite, miscomputed, below-threshold, or "
        "out-of-order details" in how
    )
    assert "exact active count and at most 100 ticker-sorted details" in how
    assert "per-ticker buy gate remain complete" in how
    assert "current 2026-09-05 record" not in how


def test_current_operator_guide_documents_bounded_walkforward_diagnostics():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "evidence decision always uses the complete artifact scan" in how
    assert "each expose an exact count, at most 100 sorted values" in how
    assert "separate list- and value-truncation flags" in how
    assert "capped at 256 Unicode code points" in how
    assert "omitted details cannot make the underlying status appear healthier" in how


def test_current_operator_guide_documents_public_meta_summary_boundary():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "complete snapshot private to its server-side evidence reconcilers" in how
    assert (
        "`meta` object in `GET /meta` contains only validated `regime`, `last_run`, `last_screen`, "
        "and `screen_date`" in how
    )
    assert "`meta_file` exposes status but not the host filesystem path" in how
    assert "rather than being copied wholesale into every API response" in how


def test_current_operator_guide_requires_stable_operational_artifact_reads():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "Two bounded reads from that descriptor must return identical bytes" in how
    assert "its metadata must remain stable" in how
    assert "visible final path must still identify that descriptor afterward" in how
    assert "in-place mutation, removal, or replacement therefore fails closed" in how
    assert "canonical postflight receipt is the scoped exception" in how
    assert "retains every parent without following symlinks" in how
    assert "parent/leaf replacement as `receipt-invalid`" in how


def test_current_operator_guide_requires_pinned_driver_log_and_lock_paths():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "visible log path must still identify that descriptor" in how
    assert "Exactly one terminal marker after the latest start" in how
    assert "multiple success/failure terminals for one run" in how
    assert "producer-looking terminal that does not match the exact success or failure grammar" in how
    assert "unrelated `TODO:` diagnostics and manual markers remain ordinary log output" in how
    assert "malformed producer-looking `run_*` start is a hard run boundary" in how
    assert "cannot borrow a terminal from an older run" in how
    assert "descriptor's size, modification time, and change time must remain stable" in how
    assert "Concurrent in-place append/truncation" in how
    assert "`log-changed-during-read` rather than mislabeled as a non-regular file" in how
    assert "Lock inspection likewise opens and pins a regular final path" in how
    assert "kernel table is scanned incrementally with a 1 MiB ceiling" in how
    assert "oversized no-match table" in how
    assert "cannot borrow liveness from an external inode" in how


def test_current_operator_guide_requires_exact_liquidity_evidence_contract():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "published within that exact run's producer-precision start/finish interval" in how
    assert "following second is outside the run" in how
    assert "exact status-specific liquidity envelope" in how
    assert "canonical dates/timestamps, safe non-negative integers" in how
    assert "before/admitted/demoted/after arithmetic" in how
    assert "extra or contradictory fields fail the whole `/meta` contract" in how
    assert "includes `backfill_processed` and `backfill_failed`" in how
    assert "can include work older than the names newly admitted" in how
    assert "Candidate-only, backfill-only, and combined failures" in how
    assert "partial historical backfill as `current`" in how
    assert "Every real weekly refresh drains that pending set even when it admits no names" in how
    assert "the next scheduled refresh retries them without operator intervention" in how
    assert "Backend status and reason vocabularies are explicit allowlists" in how
    assert "cross-language parity test binds them to the browser declarations" in how


def test_current_operator_guide_bounds_unattended_model_review():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "cron does not invoke an LLM" in how
    assert "No Codex scheduled review is installed" in how
    assert "computer to remain powered on and the desktop app to remain running" in how
    assert "isolated Git worktree" in how
    assert "Unattended full-access tasks carry elevated risk" in how
    assert "deliberately narrow sandbox and a report-only output boundary" in how
    assert "must not alter portfolio state" in how


def test_current_engine_design_uses_the_deployed_data_source_and_bootstrap_commands():
    text = (REPO_ROOT / "docs" / "design" / "trading-engine-design.md").read_text()
    assert "Primary data source | **yfinance**" in text
    assert "`collect.py --bootstrap-floor`" in text
    assert "`collect.py --backfill`" in text
    assert "`collect.py --full`" not in text
    assert "source     VARCHAR DEFAULT 'stooq'" not in text
    assert "Primary is **Stooq**" not in text
    assert "≤ 24 workers" not in text
    assert "nightly **walk-forward" not in text
    assert "9:30pm ET catch-up" not in text
    assert "Next step: scaffold" not in text


def test_engine_design_distinguishes_current_exports_from_historical_sibling_plan():
    text = (REPO_ROOT / "docs" / "design" / "trading-engine-design.md").read_text()
    compact = " ".join(text.split())

    assert "watchlist + top-100 passing names" in text
    assert "if that optional watchlist is absent, passing names still export" in compact
    assert "## 9 · Historical sibling-store integration plan" in text
    assert "not a current operating procedure for this repository" in compact
    assert "The proposed skills and `DATA-SOURCES.md` edit were not implemented there" in compact
    assert "that path is not part of this repository" in compact


def test_current_queue_documentation_matches_the_runtime_worker_cap():
    current_docs = (
        REPO_ROOT / "docs" / "how-it-works.md",
        REPO_ROOT / "docs" / "design" / "trading-engine-design.md",
        REPO_ROOT / "docs" / "design" / "trading-execution-design.md",
    )
    for path in current_docs:
        text = path.read_text()
        assert "eight" in text.lower() or "≤ 8" in text, path
        assert "≤24" not in text and "≤ 24" not in text, path

    execution_design = current_docs[-1].read_text()
    assert "engine/         collect.py market_date.py screen.py queue_runner.py" in execution_design
    assert "farm/           queue_runner.py" not in execution_design


def test_current_dashboard_docs_define_active_only_portfolio_views():
    how = (REPO_ROOT / "docs" / "how-it-works.md").read_text()
    compact_how = " ".join(how.split())
    execution = (REPO_ROOT / "docs" / "design" / "trading-execution-design.md").read_text()

    assert "Positions & Orders page is a current-state projection" in how
    assert "both lists join `portfolios` and\ninclude active books only" in how
    assert "at most the first 500 matching active-book holdings" in how
    assert "deterministic portfolio/ticker\norder" in how
    assert "restricted to those returned tickers" in how
    assert "partial table as complete exposure" in how
    assert "newest 500 matching\nactive-book orders" in how
    assert "`matching_count` and `truncated` metadata" in how
    assert "accepts only `pending`, `filled`, `rejected`, or `cancelled`" in how
    assert "unsupported filter with an empty collection" in compact_how
    assert "complete order archive" in how
    assert "playbook at 128 characters and rejection reason at 4,096 characters" in compact_how
    assert "with a per-row `detail_truncated` marker; stored values remain unchanged" in compact_how
    assert "fail visibly instead of becoming an empty table" in how
    assert "bulk and compatibility per-book equity endpoints" in how
    assert "newest 100 discretionary\ntickets" in how
    assert "newest 100 completed discretionary round-trips" in how
    assert "newest 100 active-book fills" in how
    assert "with\nindependent total/truncation metadata for each view" in how
    assert "circuit\nbreaker still evaluates the complete discretionary fill history" in how
    assert "capped at their 128-, 32-, and 4,096-character submission ceilings" in compact_how
    assert "without rewriting the append-only ticket" in compact_how
    assert "at most its newest 100 linked fills" in compact_how
    assert "exact per-ticket count and truncation flag" in compact_how
    assert "does not limit the complete fill stream used by circuit-breaker analysis" in compact_how
    assert "reject malformed successful\nAPI payloads visibly" in how
    assert "Dashboard, League, and Candidate pages apply the same fail-visible boundary" in how
    assert "incrementally reads at most 1 MiB of response bytes" in compact_how
    assert "rejects a larger declared or streamed body before parsing" in compact_how
    assert "validation errors are normalized to readable text" in compact_how
    assert "capped at 4,096 Unicode characters" in compact_how
    assert "at most its first 16 issues" in compact_how
    assert "matches one of the two exact public busy envelopes" in compact_how
    assert "preserves the JSON content type when callers add headers" in compact_how
    assert "clients also validate their successful\nresponse contracts" in how
    assert "text ceilings count Unicode code points consistently" in compact_how
    assert "fixed 100-row League and screen limits" in compact_how
    assert "fixed 500-row equity-series, position, and order limits" in compact_how
    assert "a smaller self-consistent limit cannot masquerade" in compact_how
    assert "verifies newest-first order IDs" in compact_how
    assert "Unicode code points like Python and DuckDB" in compact_how
    assert "not JavaScript UTF-16 code units" in compact_how
    assert "Current League standings are capped at the response's" in how
    assert "return, drawdown, and rank calculations still use complete active-book history" in how
    assert "at most 100\nranked books" in how
    assert "never substitutes an alphabetical subset" in how
    assert "newest 500 points per selected portfolio" in how
    assert "rejects portfolio-count metadata that disagrees" in how
    assert "explicit limits and truncation flags" in how
    assert "Later-dated rows never leak into a current curve" in compact_how
    assert "at most 100 passing names per page" in how
    assert "keep every passer reachable without an\nunbounded dashboard response" in how
    assert "remains visible but is labelled stale and unranked" in how
    assert "table and selected equity curves in two parallel requests" in compact_how
    assert "explicitly labelled unavailable" in how
    assert "candidate tickers use the same 32-character ceiling" in compact_how
    assert "ticker and portfolio identifiers must be nonblank" in compact_how
    assert "portfolio identifiers must contain 1–128 characters" in compact_how
    assert "explicitly empty value is invalid rather than being treated as unfiltered" in compact_how
    assert "bounded route decoding and encoded in-app candidate-link construction" in compact_how
    assert "**Positions & Orders** — all active portfolios" in execution


def test_how_it_works_states_the_complete_managed_schedule_shape():
    how = (REPO_ROOT / "docs" / "how-it-works.md").read_text()
    compact_how = " ".join(how.split())

    assert (
        "five deterministic production cron schedules, and one evidence-only Saturday postflight"
        in compact_how
    )
    assert "five deterministic cron schedules" not in compact_how
    assert "exact five required user-crontab entries above" in compact_how
    assert "auxiliary crontab entry remains outside the five production-driver count" in compact_how


def test_how_it_works_names_both_shared_read_model_utilities():
    how = (REPO_ROOT / "docs" / "how-it-works.md").read_text()

    assert "read_model_utils.py shared row materialization and display-text bounds" in how


def test_how_it_works_documents_the_private_health_path_boundary():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "configured host filesystem path are not exposed in any response" in how
    assert "exact public payload contains only `ok`, `status`, and `db_readable`" in how


def test_how_it_works_documents_private_driver_log_paths():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "five driver projections use an explicit public-field allowlist" in how
    assert (
        "Internal absolute log filenames and any unreviewed parser or recovery fields are "
        "omitted" in how
    )
    assert "browser then validates each driver by status and recovery transition" in how
    assert "accepts only the producer's documented invalid-reason shapes" in how
    assert "requires UTC `Z` timestamps for shell-driver events" in how


def test_how_it_works_documents_exact_postflight_browser_contract():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "browser independently enforces those exact status-specific field sets" in how


def test_how_it_works_documents_exact_meta_envelope():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "API projects the composed response through an explicit top-level public-field allowlist" in how
    assert "cross-language regression keeps that inventory identical to the browser contract" in how
    assert "browser requires the complete documented top-level `/meta` field set" in how
    assert "`freshness_days` value must exactly equal `market_freshness.calendar_days`" in how


def test_how_it_works_documents_host_status_derivation_contracts():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "Scheduler status is recomputed from the same daemon-active" in how
    assert "exact 5+1 schedule" in how
    assert "diagnostic name lists must be sorted, unique subsets" in how
    assert "closed invalid reason sets emitted by the scheduler, postflight, and source-control" in how
    assert "exact following-Saturday 05:15 UTC slot" in how
    assert "compared as exact UTC microsecond instants" in how
    assert "all-zero fraction must use the whole-second form" in how
    assert "weekday, hour, minute, and first-run constants to the Python producer" in how
    assert "production and auxiliary names plus scheduler, postflight, and source-control" in how
    assert "producer helpers reject undocumented reasons" in how
    assert "restricted to the probed `cron`/`crond` units" in how
    assert "skips only a confirmed `not-found`/`inactive` alias" in how
    assert "rejects a contradictory missing-but-active observation" in how
    assert "tokenize each active cron line as POSIX shell input" in how
    assert "first-unescaped-`%` command boundary" in how
    assert "matching `unknown` active and boot states" in how
    assert "undocumented command output is normalized to `unknown`" in how


def test_how_it_works_documents_private_sweep_ranking_path():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert (
        "public charter identifies that evidence with `grid`, `charter_version`, `generated_at`, "
        "and `n_trials`" in how
    )
    assert "internal ranking-artifact filename is used for validation but is not serialized" in how
    assert "browser accepts only the exact status-specific evidence envelope and charter fields" in how
    assert "Raw queue progress and worker-error text are likewise not repeated" in how


def test_current_operator_guide_documents_bounded_queue_failure_details():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "queue.actionable_failure_count` and `queue.historical_failure_count` as complete totals" in how
    assert "newest 100 rows in each class" in how
    assert "independently with a limit and truncation flag" in how
    assert "Public failure rows expose only `id`, bounded `kind`, and `updated_at`" in how
    assert "Failure `kind` is capped at 64 Unicode code points" in how
    assert "unique failure IDs across both classes" in how
    assert "newest-first timestamp/ID ordering" in how
    assert "producer's canonical UTC timestamp spelling" in how
    assert "latest-research-job summary adds only `state`" in how
    assert "Raw parameters, progress, and worker errors remain in DuckDB" in how
    assert "classification uses the complete stored parameters" in how
    assert "header's red queue alert follows the actionable count" in how
    assert "not the returned row count or all-time failed total" in how
    assert "Queue timestamps are emitted with an explicit UTC offset" in how


def test_current_operator_guide_documents_bounded_stale_exposure_details():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "Complete distinct-ticker, position, and pending-order totals remain visible" in how
    assert "independently limited to the first 100 stale records" in how
    assert "keeping a widespread quote outage from making `/meta` unbounded" in how
    assert "unique deterministic row identities and ordering" in how


def test_current_operator_guide_documents_authoritative_ticket_sizing():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "ticket form's 1%-risk hint uses `GET /tickets/context`" in how
    assert "no quantity is suggested" in how
    assert "server's authoritative notional, 1%-risk, experiment-size, and 4R" in how
    assert "shown as a visible warning on the Candidate page" in how


def test_current_operator_guide_documents_json_only_mutations():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "All three paper-state mutation routes require an explicit" in how
    assert "`application/json` media type before opening a write connection" in how
    assert "cross-origin HTML form" in how
    assert "does not make the service safe to expose beyond loopback" in how


def test_current_operator_guide_separates_league_scoreboard_from_research_evidence():
    text = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "operational scoreboard, not a research ranking" in text
    assert "windows differ" in text
    assert "market context, not every strategy's registered control" in text
    assert "evidence_role = operational_only" in text


def test_current_execution_design_does_not_schedule_retired_model_loop():
    text = (REPO_ROOT / "docs" / "design" / "trading-execution-design.md").read_text()
    assert "Sunday cron: `/watchlist-scan`" not in text
    assert "The former\n`/watchlist-scan` + `/trading-review` model loop was retired" in text


def test_operating_guide_documents_every_unattended_engine_driver():
    text = (REPO_ROOT / "docs" / "how-it-works.md").read_text()
    for driver in sorted((REPO_ROOT / "engine").glob("run_*.sh")):
        assert driver.name in text, driver


def test_driver_monitor_schedule_matches_current_operator_guide():
    text = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())
    expected = {
        "run_daily": ("`run_daily.sh` on weekdays at 22:30 UTC", (0, 1, 2, 3, 4), 22, 30),
        "run_weekly_verify": ("`run_weekly_verify.sh` Saturday at 02:00", (5,), 2, 0),
        "run_weekend_sweeps": ("`run_weekend_sweeps.sh` Saturday at 06:00", (5,), 6, 0),
        "run_weekly_liquid": ("`run_weekly_liquid.sh` Sunday at 02:00", (6,), 2, 0),
        "run_weekly_walkforward": (
            "`run_weekly_walkforward.sh` Sunday at 06:00",
            (6,),
            6,
            0,
        ),
    }
    monitored = {
        name: (weekdays, hour, minute)
        for _, name, _, _, weekdays, hour, minute, _, _ in DRIVER_SCHEDULES
    }
    assert monitored == {
        name: (weekdays, hour, minute) for name, (_, weekdays, hour, minute) in expected.items()
    }
    for phrase, _, _, _ in expected.values():
        assert phrase in text

    rendered = expected_cron_entries(REPO_ROOT)
    assert set(rendered) == set(expected)
    for name, line in rendered.items():
        assert f"/engine/{name}.sh" in line
        assert ">>" in line and "2>&1" in line


def test_current_operator_docs_explain_scheduler_continuity_projection():
    how = (REPO_ROOT / "docs" / "how-it-works.md").read_text()
    ui = (REPO_ROOT / "ui" / "README.md").read_text()
    compact_how = " ".join(how.split())

    assert "`scheduler` projection" in how
    assert "exact five required user-crontab entries" in compact_how
    assert "separately validates the exact auxiliary postflight entry" in compact_how
    assert "active and enabled across reboot" in compact_how
    assert "opened through no-follow descriptors" in compact_how
    assert "kernel access checks target the opened object" in compact_how
    assert "same parent and leaf identity" in compact_how
    assert "Existing targets receive the same stable descriptor inspection" in compact_how
    assert "concurrent replacement, removal, or appearance" in compact_how
    assert "Normal append growth is allowed" in compact_how
    assert "normal interpreter symlink" in compact_how
    assert "never installs a crontab entry" in compact_how
    assert "changes permissions or the host timezone, starts a service" in compact_how
    assert (
        "automation <status> (<production matched>/<expected> · postflight "
        "<matched>/<expected>)"
    ) in ui
    assert "read-only and never\nrepair cron or alter paper state" in ui


def test_operating_guide_does_not_promise_interactive_agent_continuation():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "cron does not invoke an LLM" in how
    assert (
        "interactive Codex coding session does not resume edits after its connection closes" in how
    )
    assert "reopen the workspace to continue development" in how
    assert "No Codex scheduled review is installed for this repository" in how
    assert "installed CLI is not authenticated" in how
    assert "does support `codex exec` in scheduled jobs" in how
    assert "deliberately narrow sandbox" in how
    assert "Saturday 05:15 UTC postflight needs no model credentials" in how
    assert "after the nightly's 04:30 completion boundary" in how
    assert "weekly verifier's 05:00 runtime ceiling" in how
    assert "before the 06:00 sweep driver" in how
    assert "never reruns a producer or writes market/research evidence" in how
    assert "HTTP read is capped at 1 MiB" in how
    assert "JSON decoding rejects duplicate keys, non-finite numbers, and excessive nesting" in how
    assert "`checked_at` records completion after the API response is fetched and validated" in how
    assert "schedule admission is still checked before the request begins" in how
    assert "including fundamentals" in how
    assert "Non-publishing is the default" in how
    assert "installed cron uses `--publish`" in how
    assert "requires both `--publish` and `--receipt PATH`" in how
    assert "complete parent chain without following symlinks" in how
    assert "refuses a symlink or other non-regular existing receipt" in how
    assert "absent target uses atomic no-replace" in how
    assert "existing target uses atomic exchange" in how
    assert "exact one admitted before the swap" in how
    assert "does not grant canonical authority through a symlink alias" in how
    assert "Canonical publication also refuses non-Friday dates" in how
    assert "execution before that Friday's Saturday 05:15 UTC slot" in how
    assert (
        ".venv/bin/python -m tools.verify_friday_postflight --publish > "
        "/path/to/trading-engine/logs/friday-postflight.log 2>&1"
    ) in how
    auxiliary = next(iter(expected_auxiliary_cron_entries(Path("/path/to/trading-engine")).values()))
    assert auxiliary in how


def test_root_quick_check_distinguishes_production_and_auxiliary_schedules():
    readme = (REPO_ROOT / "README.md").read_text()

    assert "scheduler: production 5/5 + postflight 1/1" in readme


def test_current_operator_docs_distinguish_local_tracking_from_remote_backup():
    readme = " ".join((REPO_ROOT / "README.md").read_text().split())
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())
    design = " ".join(
        (REPO_ROOT / "docs" / "design" / "trading-engine-design.md").read_text().split()
    )
    ui = " ".join((REPO_ROOT / "ui" / "README.md").read_text().split())

    assert "`source_control` object in `GET /meta` is authoritative" in readme
    assert "`local-only` means Git is not an off-machine backup" in readme
    assert "`source_control` object in `GET /meta`" in how
    assert "authoritative for the current tracking state" in how
    assert "A configured remote URL alone is insufficient" in how
    assert "without changing Git or contacting the network" in how
    assert "network_checked` is always false" in how
    assert "absent pair of branch-remote and branch-merge keys is classified as `no-upstream`" in how
    assert "one-sided pair or malformed merge ref reports `tracking-identity-invalid`" in how
    assert "unexpected diagnostic output from any branch/configuration probe" in how
    assert "Only the expected silent exit from `symbolic-ref` is `branch-unavailable`" in how
    assert "resolves the full and display upstream identities structurally" in how
    assert "cleanly absent commit as `tracking-ref-missing`" in how
    assert "other object-probe failures are `git-unavailable`" in how
    assert "pins both local `HEAD` and the cached upstream to validated commit IDs" in how
    assert "computes ahead/behind from those immutable IDs" in how
    assert "publishes the result only when both observations match" in how
    assert "cached-ref update therefore fails closed as `git-unavailable`" in how
    assert "Local-only observations are likewise repeated before publication" in how
    assert "exactly two ASCII-decimal counts separated by one tab" in how
    assert "Malformed or unsafe counts are `tracking-count-invalid`" in how
    assert "shortened upstream name is display-only" in how
    assert "local automation health separate from off-machine backup health" in how
    assert "browser accepts only the complete documented scheduler and source-control envelopes" in how
    assert "explicit `network_checked: false` boundary" in how
    assert "scheduler and source-control host projections each share one request-local five-second" in how
    assert "source control spends that budget across both observations" in how
    assert "standalone host probe still has the same five-second per-command default" in how
    assert "Every command has a 1 MiB combined stdout/stderr ceiling" in how
    assert "timeout, oversized output, invalid UTF-8" in how
    assert "whole process group" in how
    assert "cannot outlive the bounded probe" in how
    assert "at most one additional second to reap" in how
    assert "cannot turn the five-second command deadline into an unbounded `/meta` request" in how
    assert "cleanup attempts a direct leader kill" in how
    assert "signaling or reap errors remain contained" in how
    assert "only from one canonical stdout line, no stderr" in how
    assert "noisy or contradictory probes are `unknown`" in how
    assert "only the clean absent-crontab diagnostic" in how
    assert "repeats the complete crontab, daemon state/unit, boot enablement, timezone" in how
    assert "Both observations must match" in how
    assert "fails closed as `invalid/projection-error`" in how
    assert "Launch sources and directories are compared by stable inode and metadata" in how
    assert "replacement is detected while ordinary append growth remains valid" in how
    assert "only when a usable upstream is configured" in design
    assert "`local-only` means nightly generated-data commits remain on this machine" in ui


def test_current_docs_describe_miner_resume_and_connection_contract():
    how = (REPO_ROOT / "docs" / "how-it-works.md").read_text()
    design = (REPO_ROOT / "docs" / "design" / "trading-engine-design.md").read_text()
    execution = (REPO_ROOT / "docs" / "design" / "trading-execution-design.md").read_text()
    for table in (
        "`actions_fetch_log`",
        "`earnings_fetch_log`",
        "`fundamentals_fetch_log`",
    ):
        assert table in how and table in design
    normalized_how = " ".join(how.split())
    assert "every 25 names" in normalized_how
    assert "`ok` and `empty`" in normalized_how and "`failed`" in normalized_how
    assert "intraday, signals, action-backfill, earnings, and Friday-fundamentals" in normalized_how
    assert "do not retain a DuckDB connection during HTTP waits" in normalized_how
    assert "only active, non-ETF names" in normalized_how
    assert "explicit operator-supplied ticker list is intentionally unrestricted" in normalized_how
    assert "network collectors lease only for checkpoints" in execution
