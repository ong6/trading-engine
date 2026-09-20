"""Pure P7 attribution contract and read-only semantic verifier."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import duckdb

from engine.lib.provenance import canonical_sha256
from sim import p7_attribution as sim_attribution

from .json_utils import loads_object

SCHEMA_VERSION = 1
TRIAL_TABLE = "p7_trial_attribution"
ARM_TABLE = "p7_arm_attribution"
WINDOW_TABLE = "p7_window_attribution"
ORDER_TABLE = "p7_order_attribution"
ARM_IDS = ("algorithm_only", "ai_only", "algorithm_plus_ai")
MODEL_ROLES = dict(zip(ARM_IDS, ("none", "target_choice", "veto_only"), strict=True))
TERMINAL_OUTCOMES = {
    "algorithm_only": {"deterministic_target", "deterministic_cash"},
    "ai_only": {"target", "explicit_cash", "hold_no_trade", "model_failure_hold"},
    "algorithm_plus_ai": {"allow", "veto", "fallback_allow"},
}
BOOK_STRATEGY = "agent_only_policy"
MAX_WINDOWS, MAX_ORDERS = 1_000, 10_000
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


def _columns(spec):
    return tuple(
        (field.rstrip("?"), kind, field.endswith("?"))
        for field, kind in (item.split(":") for item in spec.split())
    )


TABLE_SCHEMAS = {
    TRIAL_TABLE: _columns(
        "trial_id:VARCHAR cohort_id:VARCHAR manifest_sha256:VARCHAR "
        "fx_observation_sha256:VARCHAR window_namespace:VARCHAR activation_market_date:DATE "
        "usd_opening_balance:DECIMAL(18,6) contract_payload:VARCHAR contract_sha256:VARCHAR recorded_at:TIMESTAMP"
    ),
    ARM_TABLE: _columns(
        "portfolio_id:VARCHAR trial_id:VARCHAR cohort_id:VARCHAR arm_id:VARCHAR "
        "policy_id:VARCHAR policy_sha256:VARCHAR model_role:VARCHAR contract_payload:VARCHAR "
        "contract_sha256:VARCHAR recorded_at:TIMESTAMP"
    ),
    WINDOW_TABLE: _columns(
        "trial_id:VARCHAR cohort_id:VARCHAR window_id:VARCHAR arm_id:VARCHAR "
        "portfolio_id:VARCHAR decision_date:DATE data_snapshot_sha256:VARCHAR decision_config_sha256:VARCHAR "
        "model_attempt_id?:BIGINT model_identity_sha256?:VARCHAR terminal_outcome:VARCHAR "
        "decision_evidence_sha256:VARCHAR attribution_payload:VARCHAR attribution_sha256:VARCHAR recorded_at:TIMESTAMP"
    ),
    ORDER_TABLE: _columns(
        "order_id:BIGINT trial_id:VARCHAR cohort_id:VARCHAR window_id:VARCHAR "
        "arm_id:VARCHAR portfolio_id:VARCHAR window_attribution_sha256:VARCHAR order_sequence:INTEGER "
        "order_sha256:VARCHAR attribution_payload:VARCHAR attribution_sha256:VARCHAR recorded_at:TIMESTAMP"
    ),
}
# fmt: off
TABLE_KEYS = {
    TRIAL_TABLE: {("PRIMARY KEY", ("trial_id",)), ("UNIQUE", ("cohort_id",))},
    ARM_TABLE: {("PRIMARY KEY", ("portfolio_id",)), ("UNIQUE", ("trial_id", "cohort_id", "arm_id"))},
    WINDOW_TABLE: {("PRIMARY KEY", ("trial_id", "cohort_id", "window_id", "arm_id")), ("UNIQUE", ("model_attempt_id",))},
    ORDER_TABLE: {("PRIMARY KEY", ("order_id",)), ("UNIQUE", ("trial_id", "cohort_id", "window_id", "arm_id", "order_sequence"))},
}
# fmt: on
class TrialAttributionError(ValueError):
    pass
def _valid(value, field, pattern):
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise TrialAttributionError(f"P7 attribution {field} is invalid")
    return value


def _day(value, field):
    try:
        parsed = value if type(value) is date else date.fromisoformat(value)
    except (TypeError, ValueError):
        parsed = None
    if type(parsed) is not date:
        raise TrialAttributionError(f"P7 attribution {field} is invalid")
    return parsed


def _utc(value, field):
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError:
        parsed = None
    if type(parsed) is not datetime:
        raise TrialAttributionError(f"P7 attribution {field} is invalid")
    parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise TrialAttributionError(f"P7 attribution {field} is invalid")
    return parsed.astimezone(timezone.utc)


def _money(value, field):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        amount = Decimal("NaN")
    if (
        isinstance(value, bool)
        or not amount.is_finite()
        or amount <= 0
        or amount.as_tuple().exponent < -6
    ):
        raise TrialAttributionError(f"P7 attribution {field} is invalid")
    return amount


def _nonnegative(value, field):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        amount = Decimal("NaN")
    if isinstance(value, bool) or not amount.is_finite() or amount < 0:
        raise TrialAttributionError(f"P7 attribution {field} is invalid")
    return amount


def _payload(raw, expected, identity, label):
    try:
        actual = loads_object(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise TrialAttributionError(f"P7 attribution {label} payload is invalid") from exc
    if actual != expected or identity != canonical_sha256(expected):
        raise TrialAttributionError(f"P7 attribution {label} identity does not match")


def _manifest_boundary(manifest, fx_contract):
    try:
        trial_id = _valid(manifest["trial_id"], "trial identity", _ID)
        if (
            manifest["trial_version"] != 1
            or manifest["execution_authority"] != "none"
            or manifest["live_trading"] != "disabled"
        ):
            raise TrialAttributionError("P7 attribution manifest is not non-authorizing")
        manifest_sha = _valid(manifest["manifest_sha256"], "manifest identity", _SHA)
        if manifest_sha != canonical_sha256(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        ):
            raise TrialAttributionError("P7 attribution manifest identity does not match")
        cohort_id = _valid(manifest["cohort"]["cohort_id"], "cohort identity", _ID)
        activation = _day(manifest["cohort"]["activation_market_date"], "activation date")
        capital, decision, arms = (
            manifest["capital"],
            manifest["decision_contract"],
            manifest["arms"],
        )
        if (
            capital["owner_envelope_currency"],
            Decimal(str(capital["owner_envelope_value"])),
            capital["accounting_currency"],
            capital["counterfactual_book_count"],
        ) != ("SGD", Decimal(10000), "USD", 3):
            raise TrialAttributionError("P7 attribution capital contract is invalid")
        fx_sha = _valid(capital["fx_observation_sha256"], "FX identity", _SHA)
        observed = _utc(capital["fx_observed_at"], "FX observation time")
        if observed.date() > activation:
            raise TrialAttributionError("P7 attribution FX observation postdates activation")
        balance = _money(capital["usd_opening_balance"], "USD opening balance")
        derived = _money(
            fx_contract.derive_usd_opening_balance(
                observation_sha256=fx_sha,
                observed_at=observed,
                owner_currency="SGD",
                owner_value=Decimal(10000),
            ),
            "derived USD opening balance",
        )
        if balance != derived:
            raise TrialAttributionError("P7 attribution FX-derived balance does not match")
        if (decision["cadence"], decision["execution_profile_id"], decision["fill_timing"]) != (
            "monthly",
            "baseline_v1",
            "next_session_open",
        ):
            raise TrialAttributionError("P7 attribution decision contract is invalid")
        execution_sha = _valid(decision["execution_profile_sha256"], "execution identity", _SHA)
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise TrialAttributionError("P7 attribution manifest is incomplete") from exc
    return (
        trial_id,
        manifest_sha,
        cohort_id,
        activation,
        fx_sha,
        observed,
        derived,
        decision,
        arms,
        execution_sha,
    )


def expected_contracts(manifest: dict, fx_contract: object) -> dict:
    # fmt: off
    trial_id, manifest_sha, cohort_id, activation, fx_sha, observed, derived, decision, arms, execution_sha = _manifest_boundary(manifest, fx_contract)
    # fmt: on
    if not isinstance(arms, list) or tuple(item.get("arm_id") for item in arms) != ARM_IDS:
        raise TrialAttributionError("P7 attribution requires the exact three arms")
    namespace = f"{trial_id}:{cohort_id}:monthly:v1"
    decision_sha = canonical_sha256(decision)
    trial = dict(
        schema_version=1,
        contract_kind="p7_trial_attribution",
        trial_id=trial_id,
        trial_version=1,
        cohort_id=cohort_id,
        manifest_sha256=manifest_sha,
        activation_market_date=activation.isoformat(),
        window_namespace=namespace,
        cadence="monthly",
        fx={
            "observation_sha256": fx_sha,
            "observed_at": observed.isoformat().replace("+00:00", "Z"),
            "owner_currency": "SGD",
            "owner_value": "10000",
            "accounting_currency": "USD",
            "usd_opening_balance": f"{derived:.6f}",
        },
        decision_config_sha256=decision_sha,
        execution_profile_id="baseline_v1",
        execution_profile_sha256=execution_sha,
        fill_timing="next_session_open",
        execution_authority="none",
        evidence_pooling="prohibited",
    )
    books = []
    for arm in arms:
        arm_id, binding = arm["arm_id"], arm.get("implementation_binding")
        if not isinstance(binding, dict) or arm.get("model_role") != MODEL_ROLES[arm_id]:
            raise TrialAttributionError("P7 attribution arm binding or role is invalid")
        policy_sha = _valid(arm["policy_sha256"], "policy identity", _SHA)
        if policy_sha != canonical_sha256(
            {key: value for key, value in arm.items() if key != "policy_sha256"}
        ):
            raise TrialAttributionError("P7 attribution policy identity does not match")
        config = {
            "schema_version": 1,
            "contract_kind": "p7_isolated_counterfactual_book",
            "strategy_runtime": BOOK_STRATEGY,
            "strategy_behavior": "no_op_external_order_only",
            "trial_id": trial_id,
            "cohort_id": cohort_id,
            "window_namespace": namespace,
            "arm_id": arm_id,
            "policy_id": _valid(arm["policy_id"], "policy identity", _ID),
            "policy_sha256": policy_sha,
            "policy_registration_sha256": _valid(
                binding.get("policy_registration_sha256"), "policy registration identity", _SHA
            ),
            "runtime_source_sha256": _valid(
                binding.get("runtime_source_sha256"), "runtime identity", _SHA
            ),
            "model_role": MODEL_ROLES[arm_id],
            "allowed_assets": ["BIL", "CASH", "EFA", "SPY"],
            "activation_market_date": activation.isoformat(),
            "fx_observation_sha256": fx_sha,
            "accounting_currency": "USD",
            "usd_opening_balance": f"{derived:.6f}",
            "decision_config_sha256": decision_sha,
            "execution_profile_id": "baseline_v1",
            "execution_profile_sha256": execution_sha,
            "fill_timing": "next_session_open",
            "order_attribution": "required",
            "execution_authority": "none",
        }
        # fmt: off
        books.append({"portfolio_id": _valid(binding.get("portfolio_id"), "portfolio identity", _ID),
            "arm_id": arm_id, "policy_id": config["policy_id"], "policy_sha256": config["policy_sha256"],
            "model_role": config["model_role"], "book_strategy": BOOK_STRATEGY,
            "book_config": config, "book_config_sha256": canonical_sha256(config)})
        # fmt: on
    if len({item["portfolio_id"] for item in books}) != 3:
        raise TrialAttributionError("P7 attribution books are not isolated")
    # fmt: off
    return {"trial": trial, "trial_sha256": canonical_sha256(trial), "arms": books,
        "activation_market_date": activation, "usd_opening_balance": derived,
        "window_namespace": namespace, "decision_config_sha256": decision_sha}
    # fmt: on


def _schema(con):
    for table, expected in TABLE_SCHEMAS.items():
        rows = con.execute(
            "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position",
            [table],
        ).fetchall()
        if tuple((a, b, c == "YES") for a, b, c in rows) != expected:
            raise TrialAttributionError(f"P7 attribution schema {table} is unavailable or invalid")
        rows = con.execute(
            "SELECT tc.constraint_type,tc.constraint_name,kcu.column_name,kcu.ordinal_position "
            "FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu "
            "USING (constraint_catalog,constraint_schema,constraint_name) WHERE tc.table_schema=current_schema() "
            "AND tc.table_name=? AND tc.constraint_type IN ('PRIMARY KEY','UNIQUE') ORDER BY 1,2,4",
            [table],
        ).fetchall()
        groups = {}
        for kind, name, column, _ in rows:
            groups.setdefault((kind, name), []).append(column)
        if {(kind, tuple(cols)) for (kind, _), cols in groups.items()} != TABLE_KEYS[table]:
            raise TrialAttributionError(f"P7 attribution keys {table} are invalid")


def _books(con, contracts):
    trial, activation = contracts["trial"], contracts["activation_market_date"]
    rows = con.execute(f"SELECT * FROM {TRIAL_TABLE}").fetchall()
    if len(rows) != 1:
        raise TrialAttributionError("P7 attribution requires one trial contract")
    row = rows[0]
    trial_recorded = _utc(row[9], "trial time")
    if (
        row[:6]
        != (
            trial["trial_id"],
            trial["cohort_id"],
            trial["manifest_sha256"],
            trial["fx"]["observation_sha256"],
            trial["window_namespace"],
            activation,
        )
        or _money(row[6], "persisted balance") != contracts["usd_opening_balance"]
        or not _utc(trial["fx"]["observed_at"], "FX time") <= trial_recorded
        or trial_recorded.date() > activation
    ):
        raise TrialAttributionError("P7 attribution trial contract does not match")
    _payload(row[7], trial, row[8], "trial")
    expected = {arm["arm_id"]: arm for arm in contracts["arms"]}
    rows = con.execute(f"SELECT * FROM {ARM_TABLE}").fetchall()
    if len(rows) != 3 or {row[3] for row in rows} != set(ARM_IDS):
        raise TrialAttributionError("P7 attribution requires exactly three arm contracts")
    books, states = {}, set()
    for row in rows:
        arm = expected[row[3]]
        if row[:7] != (
            arm["portfolio_id"],
            trial["trial_id"],
            trial["cohort_id"],
            arm["arm_id"],
            arm["policy_id"],
            arm["policy_sha256"],
            arm["model_role"],
        ):
            raise TrialAttributionError("P7 attribution arm contract does not match")
        _payload(row[7], arm, row[8], "arm")
        portfolio = con.execute(
            "SELECT id,name,strategy,config,created,active,cash,initial_cash,execution_profile "
            "FROM portfolios WHERE id=?",
            [arm["portfolio_id"]],
        ).fetchall()
        if len(portfolio) != 1:
            raise TrialAttributionError("P7 attribution book is missing or duplicated")
        book = portfolio[0]
        try:
            config = loads_object(book[3])
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise TrialAttributionError("P7 attribution book config is invalid") from exc
        if (
            not isinstance(book[1], str)
            or not book[1].strip()
            or book[2] != BOOK_STRATEGY
            or config != arm["book_config"]
            or book[4] != activation
            or not isinstance(book[5], bool)
            or _money(book[7], "book balance") != contracts["usd_opening_balance"]
            or book[8] != "baseline_v1"
            or _nonnegative(book[6], "book cash") < 0
            or not trial_recorded <= _utc(row[9], "arm time")
            or _utc(row[9], "arm time").date() > activation
        ):
            raise TrialAttributionError("P7 attribution book balance, date, or config differs")
        books[book[0]] = arm
        states.add(book[5])
    if len(states) != 1:
        raise TrialAttributionError("P7 attribution book activation states are mixed")
    return books, states.pop()


def _windows(con, contracts, books, as_of):
    rows = con.execute(f"SELECT * FROM {WINDOW_TABLE} ORDER BY window_id,arm_id").fetchall()
    if len(rows) > MAX_WINDOWS * 3:
        raise TrialAttributionError("P7 attribution window count exceeds bound")
    windows, attempts = {}, set()
    for row in rows:
        window_id, arm, decision_date = (
            _valid(row[2], "window identity", _ID),
            books.get(row[4]),
            _day(row[5], "decision date"),
        )
        if (
            arm is None
            or row[3] != arm["arm_id"]
            or row[:2] != (contracts["trial"]["trial_id"], contracts["trial"]["cohort_id"])
            or window_id != f"{contracts['window_namespace']}:{decision_date.isoformat()}"
            or not contracts["activation_market_date"] <= decision_date <= as_of
            or row[7] != contracts["decision_config_sha256"]
            or row[10] not in TERMINAL_OUTCOMES[row[3]]
            or _utc(row[14], "window time").date() != decision_date
        ):
            raise TrialAttributionError("P7 attribution window contract does not match")
        _valid(row[6], "snapshot identity", _SHA)
        if arm["model_role"] == "none":
            if row[8] is not None or row[9] is not None:
                raise TrialAttributionError(
                    "P7 deterministic control has fabricated model evidence"
                )
        elif (
            not isinstance(row[8], int)
            or isinstance(row[8], bool)
            or row[8] <= 0
            or row[8] in attempts
        ):
            raise TrialAttributionError("P7 model evidence is missing or duplicated")
        else:
            attempts.add(row[8])
            _valid(row[9], "model identity", _SHA)
        _valid(row[11], "decision evidence identity", _SHA)
        payload = {
            "schema_version": 1,
            "trial_id": row[0],
            "cohort_id": row[1],
            "window_id": window_id,
            "arm_id": row[3],
            "portfolio_id": row[4],
            "decision_date": decision_date.isoformat(),
            "data_snapshot_sha256": row[6],
            "decision_config_sha256": row[7],
            "model_attempt_id": row[8],
            "model_identity_sha256": row[9],
            "terminal_outcome": row[10],
            "decision_evidence_sha256": row[11],
        }
        _payload(row[12], payload, row[13], "window")
        windows.setdefault(window_id, []).append(row)
    for _window_id, items in windows.items():
        if len(items) != 3 or {row[3] for row in items} != set(ARM_IDS):
            raise TrialAttributionError("P7 attribution window is not shared by all three arms")
        if len({row[5:8] for row in items}) != 1:
            raise TrialAttributionError("P7 attribution window uses unequal dates or configs")
    return {key: (items[0][5], {row[3]: row for row in items}) for key, items in windows.items()}


def _orders(con, contracts, books, windows):
    ids, marks = list(books), ",".join("?" for _ in books)
    orders = con.execute(
        f"SELECT id,portfolio_id,ticker,side,qty,signal_date,status FROM sim_orders "
        f"WHERE portfolio_id IN ({marks}) ORDER BY id",
        ids,
    ).fetchall()
    if len(orders) > MAX_ORDERS:
        raise TrialAttributionError("P7 attribution order count exceeds bound")
    by_id, seen = {row[0]: row for row in orders}, set()
    owned = con.execute(
        f"SELECT * FROM {ORDER_TABLE} WHERE trial_id=? OR cohort_id=? OR portfolio_id IN ({marks}) "
        f"OR order_id IN (SELECT id FROM sim_orders WHERE portfolio_id IN ({marks})) ORDER BY order_id",
        [contracts["trial"]["trial_id"], contracts["trial"]["cohort_id"], *ids, *ids],
    ).fetchall()
    for row in owned:
        order, arm, window = by_id.get(row[0]), books.get(row[5]), windows.get(row[3])
        if (
            order is None
            or arm is None
            or window is None
            or row[0] in seen
            or row[4] != arm["arm_id"]
            or row[1:3] != (contracts["trial"]["trial_id"], contracts["trial"]["cohort_id"])
            or row[4] not in window[1]
            or order[1] != row[5]
            or order[5] != window[0]
        ):
            raise TrialAttributionError("P7 attribution order ownership is inconsistent")
        recorded = _utc(row[11], "order time")
        if recorded.date() != order[5]:
            raise TrialAttributionError("P7 attribution order time is inconsistent")
        window_sha = window[1][row[4]][13]
        order_identity = canonical_sha256(
            {
                "order_id": order[0],
                "portfolio_id": order[1],
                "ticker": order[2],
                "side": order[3],
                "quantity": float(order[4]),
                "signal_date": order[5].isoformat(),
            }
        )
        if (
            row[6] != window_sha
            or not isinstance(row[7], int)
            or row[7] <= 0
            or row[8] != order_identity
        ):
            raise TrialAttributionError("P7 attribution order decision binding is inconsistent")
        payload = {
            "schema_version": 1,
            "order_id": row[0],
            "trial_id": row[1],
            "cohort_id": row[2],
            "window_id": row[3],
            "arm_id": row[4],
            "portfolio_id": row[5],
            "window_attribution_sha256": row[6],
            "order_sequence": row[7],
            "order_sha256": row[8],
            "recorded_at": recorded.isoformat().replace("+00:00", "Z"),
        }
        _payload(row[9], payload, row[10], "order")
        seen.add(row[0])
    if seen != set(by_id):
        raise TrialAttributionError("P7 attribution contains unattributed simulator orders")
    return by_id


def verify(
    con: duckdb.DuckDBPyConnection, manifest: dict, fx_contract: object, *, as_of_date: date
) -> dict:
    if type(as_of_date) is not date:
        raise TypeError("as_of_date must be a date")
    contracts = expected_contracts(manifest, fx_contract)
    _schema(con)
    books, active = _books(con, contracts)
    if not active and any(
        con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (WINDOW_TABLE, ORDER_TABLE)
    ):
        raise TrialAttributionError("P7 inactive books contain runtime evidence")
    windows = _windows(con, contracts, books, as_of_date)
    try:
        evidence = sim_attribution.verify(
            con,
            books,
            balance=float(contracts["usd_opening_balance"]),
            activation=contracts["activation_market_date"],
            as_of=as_of_date,
            active=active,
            max_orders=MAX_ORDERS,
        )
    except sim_attribution.SimulatorAttributionError as exc:
        raise TrialAttributionError(str(exc)) from exc
    by_id = _orders(con, contracts, books, windows)
    body = {
        "schema_version": 1,
        "status": "pass",
        "trial_id": contracts["trial"]["trial_id"],
        "cohort_id": contracts["trial"]["cohort_id"],
        "window_namespace": contracts["window_namespace"],
        "arm_ids": list(ARM_IDS),
        "book_count": len(books),
        "window_count": len(windows),
        "order_count": len(by_id),
        "fill_count": evidence["fills"],
        "cost_count": evidence["costs"],
        "execution_attempt_count": evidence["attempts"],
        "equity_observation_count": evidence["equity"],
        "dividend_count": evidence["dividends"],
        "settlement_count": evidence["settlements"],
        "usd_opening_balance": f"{contracts['usd_opening_balance']:.6f}",
        "fx_observation_sha256": contracts["trial"]["fx"]["observation_sha256"],
        "execution_authority": "none",
    }
    return {**body, "verification_sha256": canonical_sha256(body)}
