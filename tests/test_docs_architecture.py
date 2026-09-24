"""Documentation contracts for source ownership and deployment boundaries."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ui_guide_names_the_current_contract_modules_and_metadata_is_not_milestoned():
    guide = (REPO_ROOT / "ui" / "README.md").read_text()
    layout = (REPO_ROOT / "ui" / "app" / "layout.js").read_text()
    for module in (
        "response-contracts.js",
        "market-contracts.js",
        "league-contracts.js",
        "meta-contracts.js",
        "meta-core-contracts.js",
        "meta-job-contracts.js",
        "meta-automation-contracts.js",
        "meta-evidence-contracts.js",
        "meta-exposure-contracts.js",
        "meta-forward-contracts.js",
        "research-contracts.js",
        "research-coverage-contracts.js",
        "operations-contracts.js",
        "positions-contracts.js",
        "orders-contracts.js",
        "journal-contracts.js",
        "mutation-contracts.js",
        "header-status.js",
    ):
        assert f"`{module}`" in guide
    assert "npm test" in guide
    assert 'description: "Local paper-trading and prospective research dashboard."' in layout
    assert "(M3)" not in layout


def test_current_api_identity_is_not_tied_to_a_retired_milestone():
    server_files = (
        REPO_ROOT / "server" / "__init__.py",
        REPO_ROOT / "server" / "db.py",
        REPO_ROOT / "server" / "main.py",
    )
    for path in server_files:
        assert "M3" not in path.read_text(), path

    main = server_files[-1].read_text()
    assert 'title="trading-engine paper backend"' in main


def test_dated_architecture_debts_are_marked_resolved_without_rewriting_history():
    review = (REPO_ROOT / "docs" / "history" / "architecture-review-2026-09-02.md").read_text()
    addendum = review.split("> **Resolution addendum, 2026-09-11.**", 1)[1].split("\n\n", 1)[0]
    compact = " ".join(line.removeprefix("> ") for line in addendum.splitlines())

    assert "original review, not current claims" in compact
    assert "`engine` is now an installable package" in compact
    assert "runtime DuckDB opens are centralized" in compact
    assert "full warnings-as-errors Python suite and 27 UI contract tests pass" in compact
    assert "remaining release blocker is the reviewed but uncommitted working tree" in compact
    assert "worktree-review-2026-09-11.md" in compact


def test_operating_guide_diagram_preserves_runtime_and_authority_boundaries():
    how = (REPO_ROOT / "docs" / "how-it-works.md").read_text()
    diagram = how.split("```mermaid", 1)[1].split("```", 1)[0]

    for node in (
        "Public market sources",
        "Five production cron schedules",
        "Weekday nightly orchestrator",
        "Weekly verification and liquidity maintenance",
        "Resource-capped job queue",
        "Local DuckDB",
        "Paper league and next-open fills",
        "Generated screens and reports",
        "FastAPI read models and risk gates",
        "Saturday evidence-only postflight",
        "Atomic local receipt",
        "Next.js dashboard",
        "Path-limited generated-data sync",
        "Git remote",
    ):
        assert node in diagram
    assert "configured upstream only" in diagram
    assert (
        "Cron[Five production cron schedules] --> Nightly[Weekday nightly orchestrator]" in diagram
    )
    assert "Cron --> Maintenance[Weekly verification and liquidity maintenance]" in diagram
    assert "Nightly --> Collect" in diagram
    assert "API --> Aux[Saturday evidence-only postflight]" in diagram
    assert "Aux --> API" not in diagram
    assert "none can promote a strategy, connect a broker, or authorize live capital" in how
    assert "postflight receipt remain local and gitignored" in how


def test_current_security_and_design_docs_match_loopback_deployment():
    security = (REPO_ROOT / "SECURITY.md").read_text()
    execution = (REPO_ROOT / "docs" / "design" / "trading-execution-design.md").read_text()
    engine = (REPO_ROOT / "docs" / "design" / "trading-engine-design.md").read_text()

    assert "bind to loopback only" in security
    assert "do not expose ports 8000 or 3000" in security
    assert "SSH tunnel" in security
    assert "API and UI bind loopback only" in execution
    assert "HOST (loopback services; SSH-tunnel access" in execution
    assert "SSH port-forwarding is the supported access path" in execution
    assert "Deterministic Sunday revalidation" in execution
    assert "scheduled revalidation cannot change membership" in execution
    assert "loopback-only" in engine
    assert "UI reachable from the corp intranet" not in execution
    assert "(company intranet" not in execution
    assert "direct intranet access is a convenience" not in execution
    assert "Weekly review + refinement loop" not in execution


def test_live_readiness_requires_evidence_and_operational_gates():
    root = (REPO_ROOT / "README.md").read_text()
    index = (REPO_ROOT / "docs" / "README.md").read_text()
    goal = (REPO_ROOT / "docs" / "history" / "live-readiness-goal.md").read_text()
    audit = (REPO_ROOT / "docs" / "history" / "recoverability-audit-2026-09-11.md").read_text()
    execution = (REPO_ROOT / "docs" / "design" / "trading-execution-design.md").read_text()
    engine = (REPO_ROOT / "docs" / "design" / "trading-engine-design.md").read_text()

    for current_doc in (root, index, execution, engine):
        assert "live-readiness-goal.md" in current_doc
    assert "recoverability-audit-2026-09-11.md" in index
    assert "worktree-review-2026-09-11.md" in index

    for design in (execution, engine):
        compact = " ".join(design.split())
        assert "elapsed time alone" in compact.lower()
        assert "broker-paper" in compact
        assert "reconciliation" in compact
        assert "recovery" in compact
        assert "clears its bar ~6+ months" not in compact

    compact_goal = " ".join(goal.split())
    assert "live-capable but capital-disabled" in compact_goal
    assert "Do not place real orders" in compact_goal
    assert "positive net excess over its frozen proper control" in compact_goal
    assert "one uninterrupted month of broker-paper shadow operation" in compact_goal
    assert "short-lived server-side lease" in compact_goal
    assert "startup and restart state must always be disabled" in compact_goal.lower()
    assert "Algorithm-only" in goal
    assert "Agent-only experimental" in goal
    assert "Hybrid" in goal
    assert "The target is a multi-mode decision system" in compact_goal
    assert "Every portfolio registration must declare exactly one mode" in compact_goal
    assert "Data improvements must remain usable by deterministic strategies" in compact_goal
    assert "keep existing algorithm-only registrations and scheduling unchanged" in compact_goal
    assert "Completed 2026-09-13" in compact_goal
    assert "GET /agent/proposals" in compact_goal
    assert "GET /agent/attribution" in compact_goal
    assert "GET /agent/authority/readiness" in compact_goal
    assert "tools.initialize_agent_paper_book" in compact_goal
    assert "paper-authority-state-machine.md" in compact_goal
    assert "atomically with the broker ledger" in compact_goal
    assert "Automatic paper" in goal
    assert "At least 60 completed market sessions" in compact_goal
    assert "An agent must never be required for an algorithm-only book to run" in compact_goal
    assert "does not authorize live trading" in compact_goal
    assert "Do not weaken a gate to manufacture completion" in compact_goal
    assert "Do not repeat the initial Workstream A audit" in compact_goal
    assert "reviewable commits" in compact_goal
    assert "user-authorized upstream" in compact_goal
    assert "restore drill on an independent personal machine" in compact_goal
    assert "Let scheduled producers add genuinely new observations" in compact_goal
    assert "Do not add broker integration on this host" in compact_goal
    assert "Produce a recoverability audit" not in compact_goal

    compact_audit = " ".join(audit.split())
    assert "Current disposition after the 2026-09-12 updates" in compact_audit
    assert "Workstream A's exit gate remains **not met**" in compact_audit
    assert "not recoverable from `HEAD` or from an off-machine backup" in compact_audit
    assert "former local-database-backup and same-host application gaps are now closed" in compact_audit
    assert "supersede this initial finding for local same-host recovery only" in compact_audit
    assert "Do not copy a live DuckDB file while writers may be active" in compact_audit
    assert "wheel is therefore a useful Python artifact, not a complete deployment" in compact_audit
    assert "No files were staged, committed, or pushed" in compact_audit
    assert "Workstream A's exit gate remains **not met**" in compact_audit
    assert ".venv/bin/python -m tools.release_manifest" in compact_audit
    assert "reads no application rows" in compact_audit
    assert "remains explicitly non-releasable" in compact_audit
    assert ".venv/bin/python -m tools.install_automation --apply" in compact_audit
    assert ".venv/bin/python -m tools.backup_database" in compact_audit
    assert "does not complete that item" in compact_audit
    assert "Closure-sequence item 7 is implemented" in compact_audit
    assert "Items 3, 4, 6, 8, 9, and 10 remain open" in compact_audit
    assert "completes the inventory and intent decisions in items 1 and 2" in compact_audit


def test_worktree_review_separates_inventory_from_release_state():
    review = (REPO_ROOT / "docs" / "history" / "worktree-review-2026-09-11.md").read_text()
    compact = " ".join(review.split())

    assert ".venv/bin/python -m tools.worktree_audit --strict" in compact
    assert "Historical snapshot" in compact
    assert "Counts below are provenance, not current status" in compact
    assert "authoritative current recursive inventory" in compact
    assert "does not turn uncommitted files into a release" in compact
    assert "zero staged paths" in compact
    assert "zero unknown-owner paths" in compact
    assert "22 release-required files remained untracked" in compact
    assert "shared host-command runner is a release-critical scheduler source" in compact
    assert "nightly/report semantic validators and their helpers" in compact
    assert "All 31 UI tests" in compact
    assert "No staging or commit was performed" in compact


def test_current_docs_do_not_present_the_dated_worktree_counts_as_live_state():
    architecture = " ".join(
        (REPO_ROOT / "docs" / "history" / "architecture-review-2026-09-02.md")
        .read_text()
        .replace(">", "")
        .split()
    )
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())

    assert "dated ownership" in architecture
    assert "snapshot and review sequence" in architecture
    assert "run its audit command for current state" in architecture.lower()
    assert "dated worktree review records the same condition" in how
    assert "`tools.release_manifest` is authoritative for current tracking state" in how


def test_dated_review_does_not_present_historical_stale_state_as_current():
    review = (REPO_ROOT / "docs" / "history" / "review-2026-09-06.md").read_text()
    addendum = review.split("> **Historical operational addendum", 1)[1].split("\n\n", 1)[0]
    compact = " ".join(line.removeprefix("> ") for line in addendum.splitlines())

    assert "These are historical observations, not current status" in compact
    assert "live `GET /meta` is authoritative" in compact


def test_backup_runbook_keeps_local_and_off_machine_recovery_distinct():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())
    contributing = " ".join((REPO_ROOT / "CONTRIBUTING.md").read_text().split())

    for text in (how, contributing):
        assert "tools.backup_database create /absolute/backup/path" in text
        assert "tools.backup_database verify /absolute/backup/path" in text
        assert "off-machine" in text
    assert "does not choose a retention policy, schedule itself, encrypt data" in how
    assert "Never treat an unverified local bundle as disaster recovery" in contributing
    for text in (how, contributing):
        assert "Schema v2" in text
        assert "schema-v1 bundles" in text
        assert "seven" in text and "operational artifacts" in text
        assert "Schema v3" in text
        assert "agent-shadow-control.json" in text
        assert "schema-v2" in text
        assert "TRADING_ENGINE_DATA_DIR" in text
        assert "copied database" in text
        assert "semantically" in text or "reconciliation" in text


def test_automation_runbook_requires_in_checkout_regular_launch_files():
    how = " ".join((REPO_ROOT / "docs" / "how-it-works.md").read_text().split())
    contributing = " ".join((REPO_ROOT / "CONTRIBUTING.md").read_text().split())

    assert "cron driver scripts, and the postflight verifier" in how
    assert "cron drivers, and the postflight verifier" in contributing
    assert "non-symlinked checkout paths" in how
    assert "non-symlinked repository paths" in contributing
    assert "`matches`, `enabled`, and `active` state" in how
    assert "user lingering is enabled for logout/reboot continuity" in how
    assert "service-source, enabled/active, user-lingering, and cron drift" in contributing
    assert "system prerequisites are reported as `invalid`" in how
    assert "requires separate operator/admin repair" in contributing
    assert "writable, non-symlinked in-checkout log directory" in how
    assert "unwritable/symlinked log directory" in contributing
    assert "user service-unit directory is invalid" in how
    assert "user unit directory is invalid and never written through" in contributing
    assert "repeats the complete plan immediately before its first mutation" in how
    assert "stale dry-run state cannot" in contributing
    assert "six launch-source hashes and six versioned unit-source hashes" in contributing
    assert "bounded no-follow descriptors" in contributing
    assert "revalidates all twelve sources before mutation" in contributing
    assert "share one retained descriptor" in contributing
    assert "symlink or ordinary-directory substitution" in contributing
    assert "reads and merges the latest crontab immediately before replacement" in contributing
    assert "rechecks lingering and service enabled/active state" in contributing
    assert "fully converged apply issues no mutating systemd command" in contributing
    assert "no compare-and-swap operation" in contributing
    assert "live `/meta.scheduler` launch audit" in contributing
    assert "checks access against the opened object" in contributing
    assert "second traversal to retain the same parent and leaf identity" in contributing
    assert "Existing managed log targets use the same stable descriptor inspection" in contributing
    assert "remains absent across the probe" in contributing
    assert "logs may append normally during inspection" in contributing
    assert "virtual-environment Python remains an intentionally supported" in contributing


def test_ci_preserves_the_support_complexity_gate_and_frozen_source_boundary():
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text()
    compact_contributing = " ".join(contributing.split())

    command = ".venv/bin/ruff check --select C90 server tools"
    assert command in workflow
    assert command in contributing
    validated_values_command = ".venv/bin/ruff check --select PLW2901 server tools"
    assert validated_values_command in workflow
    assert ".venv/bin/ruff check --select PLW2901,RET504 server tools" in contributing
    assert "distinct from their validated public forms" in compact_contributing
    assert ".venv/bin/ruff check --select RET504 server tools" in workflow
    assert "return paths free of dead intermediates" in compact_contributing
    runtime_assert_command = (
        ".venv/bin/ruff check --select S101 engine farm sim server tools"
    )
    assert runtime_assert_command in workflow
    assert runtime_assert_command in contributing
    assert (
        "keeps fail-closed runtime and proof guards active under optimized Python"
        in compact_contributing
    )
    assert ".venv/bin/python -m compileall -q engine sim server tests farm tools" in workflow
    assert "npm audit --omit=dev --audit-level=moderate" in workflow
    assert "npm audit --omit=dev --audit-level=moderate" in contributing
    assert "explicit protected-source transition" in compact_contributing
    assert re.search(r"(?m)^permissions:\n  contents: read$", workflow)
    assert "contents: write" not in workflow


def test_current_packaging_docs_do_not_claim_the_untracked_lockfile_is_committed():
    current_docs = (
        REPO_ROOT / "docs" / "how-it-works.md",
        REPO_ROOT / "docs" / "design" / "trading-engine-design.md",
    )

    for path in current_docs:
        compact = " ".join(path.read_text().split())
        assert "uv.lock" in compact
        assert "still untracked" in compact
        assert "not yet reproducible" in compact or "not recoverable from `HEAD`" in compact


def test_dependency_updates_cover_python_and_ui_without_automatic_merges():
    path = REPO_ROOT / ".github" / "dependabot.yml"
    config = yaml.safe_load(path.read_text())

    assert config["version"] == 2
    updates = {(item["package-ecosystem"], item["directory"]): item for item in config["updates"]}
    assert set(updates) == {
        ("uv", "/"),
        ("github-actions", "/"),
        ("npm", "/ui"),
    }
    for item in updates.values():
        assert item["schedule"]["interval"] == "weekly"
        assert item["schedule"]["timezone"] == "Etc/UTC"
        assert item["open-pull-requests-limit"] > 0
        assert "target-branch" not in item
        assert "allow" not in item
    assert "automerge" not in path.read_text().lower()


def test_current_docs_name_meta_fields_without_inventing_routes():
    current_docs = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "README.md",
        REPO_ROOT / "docs" / "how-it-works.md",
        REPO_ROOT / "docs" / "design" / "trading-engine-design.md",
        REPO_ROOT / "docs" / "design" / "trading-execution-design.md",
    )
    for path in current_docs:
        assert re.search(r"GET /meta\.[A-Za-z0-9_-]+", path.read_text()) is None, path


def test_operating_guide_maps_split_server_projection_modules():
    how = (REPO_ROOT / "docs" / "how-it-works.md").read_text()

    for module in (
        "driver_log.py",
        "driver_monitor.py",
        "host_command.py",
        "miner_monitor.py",
        "nightly_monitor.py",
        "nightly_reports.py",
        "meta_snapshot.py",
        "market_health.py",
        "liquidity_monitor.py",
        "exposure_monitor.py",
        "meta_projection.py",
        "queue_monitor.py",
        "sweep_monitor.py",
        "scheduler_host.py",
        "scheduler_monitor.py",
        "friday_postflight.py",
        "status_validation.py",
        "walkforward_recovery.py",
        "walkforward_artifacts.py",
        "walkforward_artifact_identity.py",
        "walkforward_artifact_geometry.py",
        "walkforward_artifact_folds.py",
        "walkforward_cohort.py",
        "walkforward_evidence.py",
        "sector_forward_status.py",
        "xs_forward_status.py",
        "e1_forward_status.py",
        "forward_contracts.py",
        "research_readiness.py",
        "stock_readiness.py",
        "fundamentals_readiness.py",
        "intraday_readiness.py",
        "readiness_common.py",
        "market_read_models.py",
        "league_read_models.py",
        "league_equity_read_models.py",
        "paper_read_models.py",
        "position_read_models.py",
        "order_read_models.py",
        "journal_read_models.py",
        "file_utils.py",
        "json_utils.py",
        "read_model_utils.py",
        "risk.py",
        "risk_ticket_gates.py",
        "risk_book.py",
        "risk_history.py",
        "risk_market.py",
        "sizing.py",
        "ticket_contract.py",
    ):
        assert module in how


def test_walkforward_artifact_facade_owns_the_public_validation_boundary():
    facade = (REPO_ROOT / "server" / "walkforward_artifacts.py").read_text()
    cohort = (REPO_ROOT / "server" / "walkforward_cohort.py").read_text()

    for module in (
        "walkforward_artifact_identity",
        "walkforward_artifact_geometry",
        "walkforward_artifact_folds",
    ):
        assert f"server.{module}" in facade
        assert module not in cohort
    assert "def validate_result(payload: dict, registration: dict)" in facade
    assert "def signature(payload: dict)" in facade
    assert "walkforward_artifacts.validate_result(payload, registration)" in cohort
    assert "walkforward_artifacts.signature(payload)" in cohort


def test_league_read_model_facade_owns_the_public_equity_boundary():
    facade = (REPO_ROOT / "server" / "league_read_models.py").read_text()
    routes = (REPO_ROOT / "server" / "main.py").read_text()

    assert "from . import league_equity_read_models" in facade
    assert "league_equity_read_models.project_equity(" in facade
    assert "league_equity_read_models.project_equities(" in facade
    assert "league_equity_read_models" not in routes
    assert "league_read_models.equity(con, portfolio_id)" in routes
    assert "league_read_models.equities(con)" in routes


def test_risk_facade_owns_policy_ordering_and_ticket_admission():
    facade = (REPO_ROOT / "server" / "risk.py").read_text()
    ticket_gates = (REPO_ROOT / "server" / "risk_ticket_gates.py").read_text()
    tickets = (REPO_ROOT / "server" / "tickets.py").read_text()

    assert "from . import risk_book, risk_history, risk_market, risk_ticket_gates" in facade
    assert "risk_ticket_gates.evaluate(" in facade
    for policy in ("EXPERIMENT_MAX", "MAX_OPEN_R", "ENTRY_ANCHOR_MAX", "KNOWN_PLAYBOOKS"):
        assert f"{policy} =" in facade or f"{policy}:" in facade
        assert f"{policy} =" not in ticket_gates and f"{policy}:" not in ticket_gates
    assert "def evaluate_gates(" in facade
    assert "def is_allowed(" in facade
    assert "risk.evaluate_gates(con, ticket" in tickets
    assert "risk.is_allowed(gates, ticket)" in tickets
    assert "risk_ticket_gates" not in tickets


def test_ticket_facade_owns_transaction_and_persistence_boundary():
    facade = (REPO_ROOT / "server" / "tickets.py").read_text()
    store = (REPO_ROOT / "server" / "ticket_store.py").read_text()
    routes = (REPO_ROOT / "server" / "main.py").read_text()

    assert "ticket_contract, ticket_store" in facade
    assert "engine_db.transaction(con)" in facade
    assert "BEGIN TRANSACTION" not in store
    for operation in (
        "insert_portfolio",
        "available_to_sell",
        "insert_pending_order",
        "insert_ticket",
        "ticket_order_id",
        "order_status",
        "cancel_pending_order",
        "insert_review_marker",
    ):
        assert f"ticket_store.{operation}(" in facade
    assert "def _audit(" in facade
    assert "audit_log" not in store
    assert "ticket_store" not in routes
    assert "tickets.create(con" in routes
    assert "tickets.cancel(con" in routes
    assert "tickets.mark_review_done(con)" in routes


def test_ui_guide_maps_page_orchestration_and_section_owners():
    ui_guide = (REPO_ROOT / "ui" / "README.md").read_text()
    compact_ui_guide = " ".join(ui_guide.split())
    operating_guide = (REPO_ROOT / "docs" / "how-it-works.md").read_text()

    assert "`app/page.js` owns dashboard request fan-out" in ui_guide
    for component in (
        "DashboardLeagueSummary.js",
        "DashboardProspectiveEvidence.js",
        "DashboardResearchReadiness.js",
        "DashboardScreen.js",
    ):
        assert component in ui_guide
    assert "app/page.js           dashboard request fan-out" in operating_guide
    assert "app/components/Dashboard*.js" in operating_guide
    assert "app/components/Header*.js" in operating_guide
    assert "app/lib/*-contracts.js" in operating_guide
    for component in (
        "Header.js",
        "HeaderStatus.js",
        "HeaderOperationalStatus.js",
        "HeaderResearchStatus.js",
    ):
        assert f"`{component}`" in ui_guide
    for component in (
        "TicketForm.js",
        "TicketTradeFields.js",
        "TicketJournalFields.js",
        "TicketOutcome.js",
    ):
        assert f"`{component}`" in ui_guide
    assert "app/components/Ticket*.js" in operating_guide
    assert "`app/positions/page.js` owns position/order request fan-out" in ui_guide
    for component in ("PositionsOpenPositions.js", "PositionsOrders.js"):
        assert f"`{component}`" in ui_guide
    assert "app/positions/page.js" in operating_guide
    assert "app/components/Positions*.js" in operating_guide
    assert "`app/journal/page.js` owns journal response admission" in ui_guide
    for component in (
        "JournalCircuitBreaker.js",
        "JournalTickets.js",
        "JournalRoundTrips.js",
        "JournalLeagueEvents.js",
    ):
        assert f"`{component}`" in ui_guide
    assert "app/journal/page.js" in operating_guide
    assert "app/components/Journal*.js" in operating_guide
    assert "`app/league/page.js` owns league/equity request fan-out" in ui_guide
    for component in ("LeagueOverview.js", "LeagueStandings.js"):
        assert f"`{component}`" in ui_guide
    assert "app/league/page.js" in operating_guide
    assert "app/components/League*.js" in operating_guide
    assert "`app/candidates/[ticker]/page.js` owns candidate/context request fan-out" in ui_guide
    for component in (
        "CandidateSummary.js",
        "CandidateTemplateChecks.js",
        "CandidateTicketPanel.js",
    ):
        assert f"`{component}`" in ui_guide
    assert "app/candidates/[ticker]/page.js" in operating_guide
    assert "app/components/Candidate*.js" in operating_guide
    assert "must not call the API" in compact_ui_guide

    assert not (REPO_ROOT / "server" / "read_models.py").exists()
    assert not (REPO_ROOT / "server" / "forward_status.py").exists()
    assert not (REPO_ROOT / "server" / "operations.py").exists()
    assert not (REPO_ROOT / "server" / "walkforward_status.py").exists()
    main = (REPO_ROOT / "server" / "main.py").read_text()
    for owner in (
        "market_read_models",
        "league_read_models",
        "paper_read_models",
        "position_read_models",
        "order_read_models",
        "journal_read_models",
    ):
        assert owner in main


def test_current_operator_instructions_do_not_embed_a_developer_home_path():
    current_instructions = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "docs" / "README.md",
        REPO_ROOT / "docs" / "how-it-works.md",
        REPO_ROOT / "docs" / "settlement-runbook.md",
        REPO_ROOT / "ui" / "README.md",
        *sorted((REPO_ROOT / "engine").glob("run_*.sh")),
    )
    absolute_home = re.compile(r"/(?:data\d+/)?home/[A-Za-z0-9._-]+/")
    for path in current_instructions:
        assert absolute_home.search(path.read_text()) is None, path
