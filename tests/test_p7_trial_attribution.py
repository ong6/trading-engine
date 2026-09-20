"""P7 attribution is exact, three-arm, read-only, and fail-closed."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from engine.lib.provenance import canonical_sha256
from server import p7_trial_attribution, p7_trial_status

ACTIVATION = date(2026, 10, 1)
RECORDED = datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc)
BALANCE = Decimal("7777.123456")
BOOKS = {
    "algorithm_only": "p7-control",
    "ai_only": "p7-ai",
    "algorithm_plus_ai": "p7-hybrid",
}


class FixedFx:
    def __init__(self, balance: Decimal = BALANCE):
        self.balance = balance
        self.calls = []

    def derive_usd_opening_balance(self, **kwargs) -> Decimal:
        self.calls.append(kwargs)
        return self.balance


def _manifest() -> dict:
    manifest = copy.deepcopy(p7_trial_status.registration())
    manifest["capital"].update(
        {
            "fx_observation_sha256": "a" * 64,
            "fx_observed_at": "2026-09-30T19:00:00Z",
            "usd_opening_balance": float(BALANCE),
        }
    )
    manifest["cohort"].update(
        {
            "activation_market_date": ACTIVATION.isoformat(),
            "cohort_id": "p7-2026-10-cohort",
        }
    )
    for index, arm in enumerate(manifest["arms"], start=1):
        arm["implementation_binding"] = {
            "policy_registration_sha256": str(index) * 64,
            "portfolio_id": BOOKS[arm["arm_id"]],
            "runtime_source_sha256": str(index + 3) * 64,
        }
        arm["policy_sha256"] = canonical_sha256(
            {key: value for key, value in arm.items() if key != "policy_sha256"}
        )
    manifest["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    return manifest


def _create_schema(con) -> None:
    definitions = {
        p7_trial_attribution.TRIAL_TABLE: """
            trial_id VARCHAR PRIMARY KEY, cohort_id VARCHAR NOT NULL UNIQUE,
            manifest_sha256 VARCHAR NOT NULL, fx_observation_sha256 VARCHAR NOT NULL,
            window_namespace VARCHAR NOT NULL, activation_market_date DATE NOT NULL,
            usd_opening_balance DECIMAL(18,6) NOT NULL, contract_payload VARCHAR NOT NULL,
            contract_sha256 VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL
        """,
        p7_trial_attribution.ARM_TABLE: """
            portfolio_id VARCHAR PRIMARY KEY, trial_id VARCHAR NOT NULL,
            cohort_id VARCHAR NOT NULL, arm_id VARCHAR NOT NULL, policy_id VARCHAR NOT NULL,
            policy_sha256 VARCHAR NOT NULL, model_role VARCHAR NOT NULL,
            contract_payload VARCHAR NOT NULL, contract_sha256 VARCHAR NOT NULL,
            recorded_at TIMESTAMP NOT NULL, UNIQUE (trial_id, cohort_id, arm_id)
        """,
        p7_trial_attribution.WINDOW_TABLE: """
            trial_id VARCHAR NOT NULL, cohort_id VARCHAR NOT NULL, window_id VARCHAR NOT NULL,
            arm_id VARCHAR NOT NULL, portfolio_id VARCHAR NOT NULL, decision_date DATE NOT NULL,
            data_snapshot_sha256 VARCHAR NOT NULL, decision_config_sha256 VARCHAR NOT NULL,
            model_attempt_id BIGINT UNIQUE, model_identity_sha256 VARCHAR,
            terminal_outcome VARCHAR NOT NULL, decision_evidence_sha256 VARCHAR NOT NULL,
            attribution_payload VARCHAR NOT NULL, attribution_sha256 VARCHAR NOT NULL,
            recorded_at TIMESTAMP NOT NULL, PRIMARY KEY (trial_id, cohort_id, window_id, arm_id)
        """,
        p7_trial_attribution.ORDER_TABLE: """
            order_id BIGINT PRIMARY KEY, trial_id VARCHAR NOT NULL, cohort_id VARCHAR NOT NULL,
            window_id VARCHAR NOT NULL, arm_id VARCHAR NOT NULL, portfolio_id VARCHAR NOT NULL,
            window_attribution_sha256 VARCHAR NOT NULL, order_sequence INTEGER NOT NULL,
            order_sha256 VARCHAR NOT NULL,
            attribution_payload VARCHAR NOT NULL, attribution_sha256 VARCHAR NOT NULL,
            recorded_at TIMESTAMP NOT NULL,
            UNIQUE (trial_id, cohort_id, window_id, arm_id, order_sequence)
        """,
    }
    for table, definition in definitions.items():
        con.execute(f"CREATE TABLE {table} ({definition})")


def _seed_contracts(con, manifest: dict, fx: FixedFx) -> dict:
    contracts = p7_trial_attribution.expected_contracts(manifest, fx)
    trial = contracts["trial"]
    con.execute(
        f"INSERT INTO {p7_trial_attribution.TRIAL_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            trial["trial_id"],
            trial["cohort_id"],
            trial["manifest_sha256"],
            trial["fx"]["observation_sha256"],
            trial["window_namespace"],
            ACTIVATION,
            BALANCE,
            json.dumps(trial, sort_keys=True),
            contracts["trial_sha256"],
            RECORDED,
        ],
    )
    for arm in contracts["arms"]:
        con.execute(
            "INSERT INTO portfolios "
            "(id, name, strategy, config, created, active, cash, initial_cash, execution_profile) "
            "VALUES (?, ?, ?, ?, ?, FALSE, ?, ?, 'baseline_v1')",
            [
                arm["portfolio_id"],
                f"P7 {arm['arm_id']}",
                arm["book_strategy"],
                json.dumps(arm["book_config"], sort_keys=True),
                ACTIVATION,
                BALANCE,
                BALANCE,
            ],
        )
        con.execute(
            f"INSERT INTO {p7_trial_attribution.ARM_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                arm["portfolio_id"],
                trial["trial_id"],
                trial["cohort_id"],
                arm["arm_id"],
                arm["policy_id"],
                arm["policy_sha256"],
                arm["model_role"],
                json.dumps(arm, sort_keys=True),
                canonical_sha256(arm),
                RECORDED,
            ],
        )
    return contracts


def _activate(con) -> None:
    con.execute(
        "UPDATE portfolios SET active = TRUE WHERE id IN ('p7-control', 'p7-ai', 'p7-hybrid')"
    )
    for portfolio_id in BOOKS.values():
        con.execute(
            "INSERT INTO sim_equity VALUES (?, ?, ?, ?, 0)",
            [portfolio_id, ACTIVATION, BALANCE, BALANCE],
        )


def _seed_window(con, contracts: dict, *, decision_date: date = ACTIVATION) -> str:
    _activate(con)
    trial = contracts["trial"]
    window_id = f"{contracts['window_namespace']}:{decision_date.isoformat()}"
    for index, arm in enumerate(contracts["arms"]):
        attempt = None if arm["arm_id"] == "algorithm_only" else 100 + index
        model_sha = None if attempt is None else chr(ord("b") + index) * 64
        outcome = {
            "algorithm_only": "deterministic_target",
            "ai_only": "target",
            "algorithm_plus_ai": "allow",
        }[arm["arm_id"]]
        evidence_sha = format(10 + index, "x") * 64
        payload = {
            "schema_version": 1,
            "trial_id": trial["trial_id"],
            "cohort_id": trial["cohort_id"],
            "window_id": window_id,
            "arm_id": arm["arm_id"],
            "portfolio_id": arm["portfolio_id"],
            "decision_date": decision_date.isoformat(),
            "data_snapshot_sha256": "9" * 64,
            "decision_config_sha256": contracts["decision_config_sha256"],
            "model_attempt_id": attempt,
            "model_identity_sha256": model_sha,
            "terminal_outcome": outcome,
            "decision_evidence_sha256": evidence_sha,
        }
        con.execute(
            f"INSERT INTO {p7_trial_attribution.WINDOW_TABLE} VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                trial["trial_id"],
                trial["cohort_id"],
                window_id,
                arm["arm_id"],
                arm["portfolio_id"],
                decision_date,
                "9" * 64,
                contracts["decision_config_sha256"],
                attempt,
                model_sha,
                outcome,
                evidence_sha,
                json.dumps(payload, sort_keys=True),
                canonical_sha256(payload),
                datetime.combine(decision_date, datetime.min.time()),
            ],
        )
    return window_id


def _seed_order_attribution(con, contracts, window_id, arm):
    window_sha = con.execute(
        f"SELECT attribution_sha256 FROM {p7_trial_attribution.WINDOW_TABLE} "
        "WHERE window_id=? AND arm_id='algorithm_only'",
        [window_id],
    ).fetchone()[0]
    order_sha = canonical_sha256(
        {
            "order_id": 1,
            "portfolio_id": arm["portfolio_id"],
            "ticker": "SPY",
            "side": "buy",
            "quantity": 10.0,
            "signal_date": ACTIVATION.isoformat(),
        }
    )
    payload = {
        "schema_version": 1,
        "order_id": 1,
        "trial_id": contracts["trial"]["trial_id"],
        "cohort_id": contracts["trial"]["cohort_id"],
        "window_id": window_id,
        "arm_id": arm["arm_id"],
        "portfolio_id": arm["portfolio_id"],
        "window_attribution_sha256": window_sha,
        "order_sequence": 1,
        "order_sha256": order_sha,
        "recorded_at": "2026-10-01T00:00:00Z",
    }
    con.execute(
        f"INSERT INTO {p7_trial_attribution.ORDER_TABLE} VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            1,
            payload["trial_id"],
            payload["cohort_id"],
            window_id,
            payload["arm_id"],
            payload["portfolio_id"],
            window_sha,
            1,
            order_sha,
            json.dumps(payload, sort_keys=True),
            canonical_sha256(payload),
            datetime(2026, 10, 1),
        ],
    )


def _seed_order(con, contracts: dict, window_id: str) -> None:
    arm = contracts["arms"][0]
    con.execute(
        "INSERT INTO sim_orders VALUES (1, ?, 'SPY', 'buy', 10, ?, 'filled', NULL)",
        [arm["portfolio_id"], ACTIVATION],
    )
    con.execute(
        "INSERT INTO sim_fills VALUES (1, ?, 'SPY', 'buy', 10, DATE '2026-10-02', "
        "100, 100.1, 10, 10)",
        [arm["portfolio_id"]],
    )
    con.execute("INSERT INTO sim_fill_costs VALUES (1, 'baseline_v1', 0.001, 10, 0, 0, 10)")
    con.execute(
        "INSERT INTO sim_execution_attempts VALUES "
        "(1, DATE '2026-10-02', 'baseline_v1', 1000, 1000000, 0.001, 'filled', NULL)"
    )
    _seed_order_attribution(con, contracts, window_id, arm)


@pytest.fixture
def p7(con):
    manifest = _manifest()
    fx = FixedFx()
    _create_schema(con)
    contracts = _seed_contracts(con, manifest, fx)
    return con, manifest, fx, contracts


def test_contract_uses_independent_fx_and_exact_three_isolated_books(p7):
    con, manifest, fx, contracts = p7
    before = {
        table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
        for table in (*p7_trial_attribution.TABLE_SCHEMAS, "portfolios")
    }

    result = p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 1))

    assert result["status"] == "pass"
    assert result["arm_ids"] == list(p7_trial_attribution.ARM_IDS)
    assert result["book_count"] == 3
    assert result["dividend_count"] == result["settlement_count"] == 0
    assert result["usd_opening_balance"] == "7777.123456"
    assert fx.calls[-1]["owner_value"] == Decimal("10000")
    assert {arm["book_config"]["window_namespace"] for arm in contracts["arms"]} == {
        contracts["window_namespace"]
    }
    assert {arm["book_strategy"] for arm in contracts["arms"]} == {"agent_only_policy"}
    assert {arm["book_config"]["strategy_behavior"] for arm in contracts["arms"]} == {
        "no_op_external_order_only"
    }
    after = {
        table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall() for table in before
    }
    assert after == before


def test_rejects_unequal_fx_balance_dates_and_configs(p7):
    con, manifest, fx, contracts = p7
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="FX-derived"):
        p7_trial_attribution.verify(con, manifest, FixedFx(Decimal("1")), as_of_date=ACTIVATION)

    con.execute("UPDATE portfolios SET initial_cash = initial_cash + 1 WHERE id = 'p7-ai'")
    with pytest.raises(
        p7_trial_attribution.TrialAttributionError, match="balance, date, or config"
    ):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)
    con.execute("UPDATE portfolios SET initial_cash = ? WHERE id = 'p7-ai'", [BALANCE])
    con.execute("UPDATE portfolios SET created = DATE '2026-10-02' WHERE id = 'p7-ai'")
    with pytest.raises(
        p7_trial_attribution.TrialAttributionError, match="balance, date, or config"
    ):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)
    con.execute("UPDATE portfolios SET created = ? WHERE id = 'p7-ai'", [ACTIVATION])
    con.execute("UPDATE portfolios SET config = '{}' WHERE id = 'p7-ai'")
    with pytest.raises(
        p7_trial_attribution.TrialAttributionError, match="balance, date, or config"
    ):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)

    con.execute(
        "UPDATE portfolios SET config = ?, cash = cash - 1 WHERE id = 'p7-ai'",
        [json.dumps(contracts["arms"][1]["book_config"], sort_keys=True)],
    )
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="balances are unequal"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)


def test_shared_window_has_control_without_fabricated_model_attempt(p7):
    con, manifest, fx, contracts = p7
    window_id = _seed_window(con, contracts)
    result = p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)
    assert result["window_count"] == 1

    con.execute(
        f"UPDATE {p7_trial_attribution.WINDOW_TABLE} SET model_attempt_id = 999, "
        "model_identity_sha256 = ? WHERE window_id = ? AND arm_id = 'algorithm_only'",
        ["f" * 64, window_id],
    )
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="fabricated model"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)


@pytest.mark.parametrize(
    "column,value",
    [
        ("terminal_outcome", "unbounded_trade"),
        ("decision_evidence_sha256", "not-a-hash"),
    ],
)
def test_rejects_invalid_terminal_decision_evidence(p7, column, value):
    con, manifest, fx, contracts = p7
    window_id = _seed_window(con, contracts)
    con.execute(
        f"UPDATE {p7_trial_attribution.WINDOW_TABLE} SET {column}=? "
        "WHERE window_id=? AND arm_id='ai_only'",
        [value, window_id],
    )
    with pytest.raises(p7_trial_attribution.TrialAttributionError):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)


def test_rejects_partial_or_nonshared_windows(p7):
    con, manifest, fx, contracts = p7
    window_id = _seed_window(con, contracts)
    con.execute(
        f"DELETE FROM {p7_trial_attribution.WINDOW_TABLE} "
        "WHERE window_id = ? AND arm_id = 'ai_only'",
        [window_id],
    )
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="shared by all three"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)


def test_lifecycle_requires_uniform_state_and_no_inactive_runtime_rows(p7):
    con, manifest, fx, contracts = p7
    con.execute("UPDATE portfolios SET active = TRUE WHERE id = 'p7-ai'")
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="states are mixed"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)

    con.execute("UPDATE portfolios SET active = FALSE WHERE id = 'p7-ai'")
    con.execute(
        "INSERT INTO sim_equity VALUES ('p7-control', ?, ?, ?, 0)",
        [ACTIVATION, BALANCE, BALANCE],
    )
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="inactive books"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)

    con.execute("DELETE FROM sim_equity")
    con.execute("UPDATE portfolios SET active = TRUE")
    with pytest.raises(
        p7_trial_attribution.TrialAttributionError, match="require complete aligned"
    ):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)


def test_rejects_unattributed_and_cross_book_orders_fills_and_costs(p7):
    con, manifest, fx, contracts = p7
    window_id = _seed_window(con, contracts)
    _seed_order(con, contracts, window_id)
    result = p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 2))
    assert (result["order_count"], result["fill_count"], result["cost_count"]) == (1, 1, 1)

    con.execute(f"DELETE FROM {p7_trial_attribution.ORDER_TABLE}")
    with pytest.raises(
        p7_trial_attribution.TrialAttributionError, match="unattributed simulator orders"
    ):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 2))

    arm = contracts["arms"][0]
    _seed_order_attribution(con, contracts, window_id, arm)
    con.execute("UPDATE sim_fills SET portfolio_id = 'p7-ai' WHERE order_id = 1")
    with pytest.raises(
        p7_trial_attribution.TrialAttributionError, match="fill is unattributed or cross-book"
    ):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 2))


@pytest.mark.parametrize("mutation", ["window_binding", "order_intent"])
def test_rejects_order_decision_binding_or_intent_tampering(p7, mutation):
    con, manifest, fx, contracts = p7
    window_id = _seed_window(con, contracts)
    _seed_order(con, contracts, window_id)
    if mutation == "window_binding":
        con.execute(
            f"UPDATE {p7_trial_attribution.ORDER_TABLE} "
            "SET window_attribution_sha256=repeat('f', 64)"
        )
    else:
        con.execute("UPDATE sim_orders SET qty=11 WHERE id=1")
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="decision binding"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 2))


def test_rejects_missing_cost_and_future_equity_preseed(p7):
    con, manifest, fx, contracts = p7
    window_id = _seed_window(con, contracts)
    _seed_order(con, contracts, window_id)
    con.execute("DELETE FROM sim_fill_costs WHERE order_id = 1")
    with pytest.raises(
        p7_trial_attribution.TrialAttributionError, match="fills and cost evidence differ"
    ):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 2))

    con.execute("DELETE FROM sim_fills; DELETE FROM sim_orders")
    con.execute(f"DELETE FROM {p7_trial_attribution.ORDER_TABLE}")
    for portfolio_id in BOOKS.values():
        con.execute(
            "INSERT INTO sim_equity VALUES (?, DATE '2026-10-03', ?, ?, 0)",
            [portfolio_id, BALANCE, BALANCE],
        )
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="future equity preseed"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 2))


def test_rejects_incomplete_attempt_wrong_cost_formula_and_excess_exposure(p7):
    con, manifest, fx, contracts = p7
    window_id = _seed_window(con, contracts)
    _seed_order(con, contracts, window_id)
    con.execute("DELETE FROM sim_execution_attempts")
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="attempts are incomplete"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 2))

    con.execute(
        "INSERT INTO sim_execution_attempts VALUES "
        "(1, DATE '2026-10-02', 'baseline_v1', 1000, 1000000, 0.001, 'filled', NULL)"
    )
    con.execute("UPDATE sim_fill_costs SET impact_bps = 2, total_bps = 12")
    con.execute("UPDATE sim_fills SET cost_bps = 12")
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="cost ownership"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 2))

    con.execute("UPDATE sim_fill_costs SET total_bps = 10")
    con.execute("UPDATE sim_fills SET cost_bps = 10")
    con.execute("INSERT INTO sim_positions VALUES ('p7-control', 'SPY', 100, 100)")
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match="gross exposure"):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=date(2026, 10, 2))


@pytest.mark.parametrize("ledger", ["dividend", "settlement"])
def test_rejects_unsupported_economic_rows_with_counts(p7, ledger):
    con, manifest, fx, _contracts = p7
    if ledger == "dividend":
        con.execute(
            "INSERT INTO sim_dividends VALUES ('p7-control', 'SPY', DATE '2026-10-01', 1, 1, 1)"
        )
        expected = "dividends=1, settlements=0"
    else:
        con.execute(
            "CREATE TABLE sim_settlements (portfolio_id VARCHAR, ticker VARCHAR, effective DATE)"
        )
        con.execute("INSERT INTO sim_settlements VALUES ('p7-ai', 'EFA', DATE '2026-10-01')")
        expected = "dividends=0, settlements=1"
    with pytest.raises(p7_trial_attribution.TrialAttributionError, match=expected):
        p7_trial_attribution.verify(con, manifest, fx, as_of_date=ACTIVATION)


def test_schema_contract_is_pure_and_has_no_initializer():
    assert not hasattr(p7_trial_attribution, "init_schema")
    assert not hasattr(p7_trial_attribution, "initialize")
    assert set(p7_trial_attribution.TABLE_SCHEMAS) == {
        "p7_trial_attribution",
        "p7_arm_attribution",
        "p7_window_attribution",
        "p7_order_attribution",
    }
