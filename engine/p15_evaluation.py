"""Read-only P15 profitability gates and diagnostics."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import NormalDist

import duckdb

from engine import p15_event_sources
from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock, write_text_atomic
from engine.lib.settings import DATA_DIR, REPO_ROOT
from engine.lib.util import table_exists
from sim import nyse

POLICY_ID = "p15-scoring-v1"
BOOK_IDS = ("p15_ai_ranked", "p15_rule_control", "p15_hybrid_veto")
LOOKS = (60, 90, 120)
ALPHA = 0.05 / 3
NW_LAG = 4
MISSING_LABEL_GRACE_SESSIONS = 3
PRIMARY_HH_LAG = 4
PRIMARY_FALLBACK_LAG = 8
PRIMARY_T_CRITICAL = {
    60: 2.431291192871,
    90: 2.315573401153,
    120: 2.263728355255,
}
PRIMARY_STRIDE = 5
PRIMARY_OFFSET = 0
P15EvaluationError = ValueError
REGISTRATION_PATH = REPO_ROOT / "server" / "p15-registration.json"
LOOK_ANCHOR_PATH = DATA_DIR / "reports" / "agent-eval" / "p15-look-anchors.jsonl"


def registration_sha256() -> str:
    registration = json.loads(REGISTRATION_PATH.read_text())
    recorded = registration.pop("registration_sha256", None)
    if recorded != canonical_sha256(registration):
        raise P15EvaluationError("P15 registration identity differs")
    return recorded


def init_look_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_evaluation_looks (
        schema_version INTEGER NOT NULL, policy_id VARCHAR NOT NULL,
        registration_sha256 VARCHAR NOT NULL, look_sessions INTEGER NOT NULL,
        through_market_date DATE NOT NULL, evaluated_at TIMESTAMP NOT NULL,
        source_prefix_sha256 VARCHAR NOT NULL, previous_look_sha256 VARCHAR,
        result_payload VARCHAR NOT NULL, look_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(policy_id,registration_sha256,look_sessions))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS p15_evaluation_look_anchors (
        policy_id VARCHAR NOT NULL, registration_sha256 VARCHAR NOT NULL,
        look_sessions INTEGER NOT NULL, look_sha256 VARCHAR NOT NULL UNIQUE,
        PRIMARY KEY(policy_id,registration_sha256,look_sessions))"""
    )
    con.execute(
        "ALTER TABLE p15_evaluation_look_anchors ADD COLUMN IF NOT EXISTS "
        "external_anchor_sha256 VARCHAR"
    )


def _primary_variance_inflation(n: int, *, fallback: bool) -> float:
    """Analytic finite-sample correction for the registered MA(4) null."""
    overlap_bias = (
        37 / 45 - 457 / (45 * n) + 2272 / (75 * n**2) + 128 / (3 * n**3)
        if fallback else
        1 - 53 / (5 * n) + 24 / n**2 + 32 / n**3
    )
    return n / (n - 1) / overlap_bias


def _mean(values: list[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


def average_ranks(values: list[float]) -> list[float]:
    """Return one-based average ranks, including average ranks for ties."""
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2
        for index in order[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    x, y = average_ranks(left), average_ranks(right)
    mx, my = _mean(x), _mean(y)
    dx, dy = [v - mx for v in x], [v - my for v in y]
    denominator = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    return None if denominator == 0 else sum(a * b for a, b in zip(dx, dy, strict=True)) / denominator


def newey_west(values: list[float], lag: int = NW_LAG) -> dict:
    xs = [float(value) for value in values if math.isfinite(float(value))]
    if len(xs) < 3:
        return {"n": len(xs), "mean": _mean(xs), "se": None, "t": None, "lag": lag}
    mean = sum(xs) / len(xs)
    centered = [value - mean for value in xs]
    bounded_lag = max(0, min(lag, len(xs) - 1))
    lrv = sum(value * value for value in centered) / len(xs)
    for offset in range(1, bounded_lag + 1):
        covariance = sum(
            centered[index] * centered[index - offset]
            for index in range(offset, len(xs))
        ) / len(xs)
        lrv += 2 * (1 - offset / (bounded_lag + 1)) * covariance
    se = math.sqrt(max(lrv, 0.0) / len(xs))
    return {"n": len(xs), "mean": mean, "se": se,
            "t": None if se == 0 else mean / se, "lag": bounded_lag}


def _interval(values: list[float], *, alpha: float = ALPHA, lag: int = NW_LAG) -> dict:
    result = newey_west(values, lag)
    critical = NormalDist().inv_cdf(1 - alpha)
    result.update(alpha=alpha, lower=None, upper=None)
    if result["mean"] is not None and result["se"] is not None:
        result["lower"] = result["mean"] - critical * result["se"]
        result["upper"] = result["mean"] + critical * result["se"]
    return result


def _primary_standard_error(values: list[float]) -> dict:
    """Hansen-Hodrick lag-4 SE, with the registered nonpositive fallback."""
    xs = [float(value) for value in values if math.isfinite(float(value))]
    mean = _mean(xs)
    base = {
        "n": len(xs), "mean": mean, "se": None, "t": None,
        "raw_long_run_variance": None, "long_run_variance": None,
        "variance_inflation": None,
        "variance_estimator": "hansen_hodrick",
        "kernel": "uniform", "lag": min(PRIMARY_HH_LAG, max(0, len(xs) - 1)),
        "fallback_used": False,
    }
    if len(xs) < 3:
        return base
    centered = [value - mean for value in xs]
    n = len(xs)

    def covariance(offset: int) -> float:
        return sum(
            centered[index] * centered[index - offset]
            for index in range(offset, n)
        ) / n

    lag = min(PRIMARY_HH_LAG, n - 1)
    lrv = covariance(0) + 2 * sum(covariance(offset) for offset in range(1, lag + 1))
    if lrv <= 0:
        lag = min(PRIMARY_FALLBACK_LAG, n - 1)
        lrv = covariance(0) + 2 * sum(
            (1 - offset / (lag + 1)) * covariance(offset)
            for offset in range(1, lag + 1)
        )
        base.update(
            variance_estimator="newey_west", kernel="bartlett", lag=lag,
            fallback_used=True,
        )
    base["raw_long_run_variance"] = lrv
    inflation = _primary_variance_inflation(n, fallback=base["fallback_used"])
    base["variance_inflation"] = inflation
    lrv *= inflation
    base["long_run_variance"] = lrv
    if lrv > 0:
        base["se"] = math.sqrt(lrv / n)
        base["t"] = mean / base["se"]
    return base


def _hansen_hodrick_interval(values: list[float], *, alpha: float = ALPHA) -> dict:
    result = _primary_standard_error(values)
    critical = NormalDist().inv_cdf(1 - alpha)
    result.update(
        alpha=alpha, critical_value=critical,
        lower=None, upper=None,
    )
    if result["mean"] is not None and result["se"] is not None:
        result["lower"] = result["mean"] - critical * result["se"]
        result["upper"] = result["mean"] + critical * result["se"]
    return result


def _primary_interval(values: list[float], *, alpha: float = ALPHA) -> dict:
    """Registered offset-0, every-fifth-session Student-t interval."""
    full = [float(value) for value in values if math.isfinite(float(value))]
    critical = PRIMARY_T_CRITICAL.get(len(full))
    if critical is None:
        raise P15EvaluationError("P15 primary interval is outside a registered look")
    selected = full[PRIMARY_OFFSET::PRIMARY_STRIDE]
    mean = _mean(selected)
    variance = (
        sum((value - mean) ** 2 for value in selected) / (len(selected) - 1)
        if len(selected) > 1 else None
    )
    se = None if variance is None or variance <= 0 else math.sqrt(variance / len(selected))
    result = {
        "n": len(selected), "origin_count": len(full), "mean": mean, "se": se,
        "t": None if se is None else mean / se,
        "df": len(selected) - 1, "alpha": alpha, "critical_value": critical,
        "lower": None, "upper": None, "variance_estimator": "sample_variance",
        "sampling": "nonoverlapping_offset0", "stride": PRIMARY_STRIDE,
        "offset": PRIMARY_OFFSET,
    }
    if mean is not None and se is not None:
        result["lower"] = mean - critical * se
        result["upper"] = mean + critical * se
    return result


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _primary_rows(con: duckdb.DuckDBPyConnection, generated_at: datetime) -> list[dict]:
    if not all(table_exists(con, name) for name in (
        "agent_evaluation_traces", "agent_evaluation_decisions", "agent_evaluation_labels_v2"
    )):
        return []
    rows = con.execute(
        "SELECT t.market_date,t.observed_at,d.id,d.decision,d.decision_payload,"
        "l.horizon_sessions,l.label_basis,l.net_excess_return,l.missing_bar_status,l.labeled_at "
        "FROM agent_evaluation_traces t JOIN agent_evaluation_decisions d ON d.trace_id=t.id "
        "LEFT JOIN agent_evaluation_labels_v2 l ON l.decision_id=d.id "
        "AND l.horizon_sessions IN (5,10) AND l.label_basis IN "
        "('next_session_open','missing_entry_last_available_close') "
        "AND l.labeled_at<=? WHERE t.policy_id=? ORDER BY t.market_date,d.id,l.horizon_sessions",
        [generated_at.replace(tzinfo=None), POLICY_ID],
    ).fetchall()
    result: dict[int, dict] = {}
    for market_date, observed_at, decision_id, decision, raw, horizon, basis, net, missing, labeled in rows:
        item = result.setdefault(int(decision_id), {
            "market_date": market_date, "observed_at": observed_at, "decision": decision,
            "payload": json.loads(raw), "labels": {},
        })
        if horizon is not None:
            if int(horizon) in item["labels"]:
                raise P15EvaluationError("P15 decision has duplicate terminal labels")
            item["labels"][int(horizon)] = {
                "basis": basis, "net_excess_return": float(net),
                "missing_bar_status": missing, "labeled_at": labeled,
            }
    return list(result.values())


def _mature(con, market_date: date, horizon: int, generated_at: datetime) -> bool:
    if not table_exists(con, "prices"):
        return False
    return con.execute(
        f"SELECT COUNT(DISTINCT date)>=? FROM prices WHERE ticker='SPY' AND date>? "
        f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL}",
        [horizon, market_date, generated_at.replace(tzinfo=None)],
    ).fetchone()[0]


def _scores(row: dict, horizon: int) -> tuple[float, float] | None:
    payload = row["payload"]
    model = _finite_number(payload.get("expected_excess_bp_5" if horizon == 5
                                       else "expected_excess_bp_10"))
    baseline = _finite_number(payload.get("baseline_score"))
    if (payload.get("stratum") not in {"mover", "trend"}
            or payload.get("scoring_status") != "available"
            or row["decision"] == "unavailable" or model is None or baseline is None):
        return None
    return model, baseline


def _session_ics(rows: list[dict], horizon: int) -> dict:
    usable = []
    for row in rows:
        payload, label, scores = row["payload"], row["labels"].get(horizon), _scores(row, horizon)
        if scores is not None and label is not None:
            model, baseline = scores
            usable.append((model, baseline, label["net_excess_return"], payload, label, row))
    reason = None
    if len(usable) < 20:
        reason = "fewer_than_20_pairs"
    elif len({row[0] for row in usable}) == 1:
        reason = "constant_model_score"
    elif len({row[1] for row in usable}) == 1:
        reason = "constant_baseline_score"
    constant_outcome = len(usable) >= 20 and len({row[2] for row in usable}) == 1
    model_ic = (None if reason else 0.0 if constant_outcome else
                spearman([row[0] for row in usable], [row[2] for row in usable]))
    base_ic = (None if reason else 0.0 if constant_outcome else
               spearman([row[1] for row in usable], [row[2] for row in usable]))
    return {"status": "insufficient" if reason else "scored",
            "reason": "constant_outcome_neutral" if constant_outcome else reason,
            "pair_count": len(usable), "model_ic": model_ic, "baseline_ic": base_ic,
            "delta_ic": None if reason else model_ic - base_ic,
            "evaluated_at": None if not usable else max(
                row[4]["labeled_at"] for row in usable
            ).replace(tzinfo=timezone.utc).isoformat(), "rows": usable}


def _logistic(training: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if len(training) < 20 or len({item[1] for item in training}) < 2:
        return None
    xs, ys = [item[0] for item in training], [item[1] for item in training]
    center, scale = sum(xs) / len(xs), max(max(xs) - min(xs), 1.0)
    x = [(value - center) / scale for value in xs]
    intercept = math.log(max(1e-6, min(1 - 1e-6, sum(ys) / len(ys))) /
                         max(1e-6, 1 - sum(ys) / len(ys)))
    slope = 0.0
    for _ in range(30):
        probabilities = [1 / (1 + math.exp(-max(-30, min(30, intercept + slope * value))))
                         for value in x]
        weights = [max(probability * (1 - probability), 1e-9)
                   for probability in probabilities]
        h00, h01 = sum(weights), sum(w * value for w, value in zip(weights, x, strict=True))
        h11 = sum(w * value * value for w, value in zip(weights, x, strict=True))
        g0 = sum(y - p for y, p in zip(ys, probabilities, strict=True))
        g1 = sum((y - p) * value for y, p, value in zip(ys, probabilities, x, strict=True))
        determinant = h00 * h11 - h01 * h01
        if determinant <= 1e-12:
            return None
        delta0 = (g0 * h11 - g1 * h01) / determinant
        delta1 = (g1 * h00 - g0 * h01) / determinant
        intercept, slope = intercept + delta0, slope + delta1
        if max(abs(delta0), abs(delta1)) < 1e-9:
            return intercept, slope, center, scale
    return None


def _diagnostics(rows: list[tuple]) -> dict:
    outcomes = [float(row[2] > 0) for row in rows]
    probabilities = [float(row[3]["p_outperform_5"]) for row in rows]
    calibration = []
    for low in (0.0, 0.2, 0.4, 0.6, 0.8):
        members = [(p, y) for p, y in zip(probabilities, outcomes, strict=True)
                   if low <= p <= low + 0.2 and (p < low + 0.2 or low == 0.8)]
        calibration.append({"lower": low, "upper": low + 0.2, "count": len(members),
                            "mean_probability": _mean([item[0] for item in members]),
                            "observed_rate": _mean([item[1] for item in members])})
    dated = sorted(rows, key=lambda row: (row[5]["market_date"], row[0], row[1]))
    climatology_errors, logistic_errors = [], []
    session_dates = sorted({row[5]["market_date"] for row in dated})
    date_index = {value: index for index, value in enumerate(session_dates)}
    for row in dated:
        current_date, observed = row[5]["market_date"], row[5]["observed_at"]
        known = [prior for prior in dated if prior[5]["market_date"] < current_date
                 and prior[4]["labeled_at"] <= observed]
        if known:
            prediction = _mean([float(prior[2] > 0) for prior in known])
            climatology_errors.append((prediction - float(row[2] > 0)) ** 2)
        index = date_index[current_date]
        if index >= 6:
            training_dates = set(session_dates[:index - 5])
            training = [(prior[1], float(prior[2] > 0)) for prior in known
                        if prior[5]["market_date"] in training_dates]
            fit = _logistic(training)
            if fit is not None:
                intercept, slope, center, scale = fit
                value = intercept + slope * ((row[1] - center) / scale)
                prediction = 1 / (1 + math.exp(-max(-30, min(30, value))))
                logistic_errors.append((prediction - float(row[2] > 0)) ** 2)
    spreads = []
    for session_date in session_dates:
        members = [row for row in dated if row[5]["market_date"] == session_date]
        size = len(members) // 5
        if size:
            ordered = sorted(members, key=lambda row: (-row[0], -row[1]))
            spreads.append(_mean([row[2] for row in ordered[:size]])
                           - _mean([row[2] for row in ordered[-size:]]))
    by_stratum = {}
    for stratum in ("mover", "trend"):
        members = [row for row in rows if row[3].get("stratum") == stratum]
        by_stratum[stratum] = {"count": len(members), "model_ic": spearman(
            [row[0] for row in members], [row[2] for row in members]
        )}
    return {
        "model_brier": _mean([(p - y) ** 2 for p, y in zip(
            probabilities, outcomes, strict=True)]),
        "climatology_brier": _mean(climatology_errors),
        "baseline_logistic_brier": _mean(logistic_errors),
        "calibration": calibration, "ic_by_stratum": by_stratum,
        "mean_top_bottom_quintile_spread": _mean(spreads),
    }


def _look(scored: list[dict], size: int) -> dict:
    prefix = scored[:size]
    interval = _primary_interval([row["delta_ic"] for row in prefix])
    diagnostic = _hansen_hodrick_interval([row["delta_ic"] for row in prefix])
    mean_model = _mean([row["model_ic"] for row in prefix])
    status = "continue"
    if interval["lower"] is not None and interval["lower"] > 0 and mean_model > 0:
        status = "pass"
    elif interval["upper"] is not None and interval["upper"] < 0:
        status = "kill"
    elif size == 120:
        status = "kill"
    return {"look": size, "status": status, "mean_model_ic": mean_model,
            "mean_baseline_ic": _mean([row["baseline_ic"] for row in prefix]),
            "delta": interval, "hansen_hodrick_diagnostic": diagnostic}


def evaluate_looks(scored: list[dict]) -> tuple[str, list[dict], int | None]:
    """Apply only the three pre-registered immutable-prefix looks."""
    looks, terminal = [], None
    for size in LOOKS:
        if len(scored) < size or terminal is not None:
            break
        item = _look(scored, size)
        item["through_market_date"] = scored[size - 1]["market_date"]
        item["evaluated_at"] = max(row["evaluated_at"] for row in scored[:size])
        looks.append(item)
        if item["status"] in {"pass", "kill"}:
            terminal = item["status"]
    next_look = None if terminal else next((size for size in LOOKS if size > len(scored)), None)
    return terminal or "collecting", looks, next_look


def _look_source_prefix(scored: list[dict], size: int) -> str:
    return canonical_sha256([{
        "market_date": row["market_date"], "evaluated_at": row["evaluated_at"],
        "pair_count": row["pair_count"], "model_ic": row["model_ic"],
        "baseline_ic": row["baseline_ic"], "delta_ic": row["delta_ic"],
    } for row in scored[:size]])


def _external_look_anchors(path: Path) -> list[dict]:
    if not path.exists():
        return []
    anchors, previous = [], None
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise P15EvaluationError("P15 external look anchor is unavailable") from exc
    for line in lines:
        try:
            item = json.loads(line)
        except (TypeError, ValueError) as exc:
            raise P15EvaluationError("P15 external look anchor differs") from exc
        body = {key: item.get(key) for key in (
            "schema_version", "policy_id", "registration_sha256",
            "look_sessions", "look_sha256", "previous_anchor_sha256",
        )}
        if (
            set(item) != {*body, "anchor_sha256"}
            or body["schema_version"] != 1
            or body["previous_anchor_sha256"] != previous
            or canonical_sha256(body) != item["anchor_sha256"]
        ):
            raise P15EvaluationError("P15 external look anchor differs")
        anchors.append(item)
        previous = item["anchor_sha256"]
    return anchors


def publish_pending_look_anchors(
    con: duckdb.DuckDBPyConnection, registration_sha256: str,
    *, anchor_path: Path = LOOK_ANCHOR_PATH,
) -> int:
    """Publish committed DB anchors, recovering either side of a prior crash."""
    with advisory_file_lock(anchor_path.with_suffix(anchor_path.suffix + ".lock")):
        external = _external_look_anchors(anchor_path)
        rows = con.execute(
            "SELECT look_sessions,look_sha256,external_anchor_sha256 "
            "FROM p15_evaluation_look_anchors WHERE policy_id=? "
            "AND registration_sha256=? ORDER BY look_sessions",
            [POLICY_ID, registration_sha256],
        ).fetchall()
        matching = [
            item for item in external
            if item["policy_id"] == POLICY_ID
            and item["registration_sha256"] == registration_sha256
        ]
        if len(matching) > len(rows):
            raise P15EvaluationError("P15 look evidence differs")
        for index, item in enumerate(matching):
            size, look_sha, published_sha = rows[index]
            if (
                item["look_sessions"] != size
                or item["look_sha256"] != look_sha
                or published_sha not in (None, item["anchor_sha256"])
            ):
                raise P15EvaluationError("P15 look evidence differs")
            if published_sha is None:
                con.execute(
                    "UPDATE p15_evaluation_look_anchors "
                    "SET external_anchor_sha256=? WHERE policy_id=? "
                    "AND registration_sha256=? AND look_sessions=? "
                    "AND external_anchor_sha256 IS NULL",
                    [item["anchor_sha256"], POLICY_ID, registration_sha256, size],
                )
        published = len(matching)
        for size, look_sha, published_sha in rows[published:]:
            if published_sha is not None:
                raise P15EvaluationError("P15 look evidence differs")
            body = {
                "schema_version": 1, "policy_id": POLICY_ID,
                "registration_sha256": registration_sha256,
                "look_sessions": size, "look_sha256": look_sha,
                "previous_anchor_sha256": (
                    None if not external else external[-1]["anchor_sha256"]
                ),
            }
            item = {**body, "anchor_sha256": canonical_sha256(body)}
            text = "" if not anchor_path.exists() else anchor_path.read_text()
            if text and not text.endswith("\n"):
                raise P15EvaluationError("P15 external look anchor differs")
            write_text_atomic(
                anchor_path, text + json.dumps(item, sort_keys=True) + "\n",
            )
            external.append(item)
            con.execute(
                "UPDATE p15_evaluation_look_anchors SET external_anchor_sha256=? "
                "WHERE policy_id=? AND registration_sha256=? AND look_sessions=? "
                "AND external_anchor_sha256 IS NULL",
                [item["anchor_sha256"], POLICY_ID, registration_sha256, size],
            )
            published += 1
        return published


def load_retained_looks(
    con: duckdb.DuckDBPyConnection, scored: list[dict], registration_sha256: str,
    *, require_reached: bool = True, anchor_path: Path = LOOK_ANCHOR_PATH,
) -> list[dict]:
    if not table_exists(con, "p15_evaluation_looks"):
        if require_reached and len(scored) >= LOOKS[0]:
            raise P15EvaluationError("P15 reached look is not persisted")
        return []
    rows = con.execute(
        "SELECT schema_version,policy_id,registration_sha256,look_sessions,"
        "through_market_date,evaluated_at,source_prefix_sha256,previous_look_sha256,"
        "result_payload,look_sha256 FROM p15_evaluation_looks "
        "WHERE policy_id=? AND registration_sha256=? ORDER BY look_sessions",
        [POLICY_ID, registration_sha256],
    ).fetchall()
    anchors = con.execute(
        "SELECT look_sessions,look_sha256,external_anchor_sha256 "
        "FROM p15_evaluation_look_anchors "
        "WHERE policy_id=? AND registration_sha256=? ORDER BY look_sessions",
        [POLICY_ID, registration_sha256],
    ).fetchall()
    if [(row[0], row[1]) for row in anchors] != [(row[3], row[9]) for row in rows]:
        raise P15EvaluationError("P15 look evidence differs")
    external = [
        item for item in _external_look_anchors(anchor_path)
        if item["policy_id"] == POLICY_ID
        and item["registration_sha256"] == registration_sha256
    ]
    if (
        any(row[2] is None for row in anchors)
        or [
            (item["look_sessions"], item["look_sha256"], item["anchor_sha256"])
            for item in external
        ] != anchors
    ):
        raise P15EvaluationError("P15 look evidence differs")
    retained, previous = [], None
    for index, row in enumerate(rows):
        (schema_version, policy_id, registered, size, through, evaluated,
         prefix_sha, prior_sha, raw_result, look_sha) = row
        if index >= len(LOOKS) or size != LOOKS[index] or len(scored) < size:
            raise P15EvaluationError("P15 look evidence differs")
        result = json.loads(raw_result)
        expected_prefix = _look_source_prefix(scored, size)
        body = {
            "schema_version": schema_version, "policy_id": policy_id,
            "registration_sha256": registered, "look_sessions": size,
            "through_market_date": through.isoformat(),
            "evaluated_at": evaluated.replace(tzinfo=timezone.utc).isoformat(),
            "source_prefix_sha256": prefix_sha,
            "previous_look_sha256": prior_sha, "result": result,
        }
        if (
            schema_version != 1 or policy_id != POLICY_ID
            or registered != registration_sha256 or prefix_sha != expected_prefix
            or prior_sha != previous or canonical_sha256(body) != look_sha
            or result.get("look") != size
            or result.get("through_market_date") != through.isoformat()
        ):
            raise P15EvaluationError("P15 look evidence differs")
        retained.append(result)
        previous = look_sha
        if result.get("status") in {"pass", "kill"} and index != len(rows) - 1:
            raise P15EvaluationError("P15 look evidence differs")
    if require_reached:
        terminal = retained and retained[-1]["status"] in {"pass", "kill"}
        next_size = None if terminal else LOOKS[len(retained)] if len(retained) < len(LOOKS) else None
        if next_size is not None and len(scored) >= next_size:
            raise P15EvaluationError("P15 reached look is not persisted")
    return retained


def persist_reached_looks(
    con: duckdb.DuckDBPyConnection, scored: list[dict], registration_sha256: str,
    *, evaluated_at: datetime, anchor_path: Path = LOOK_ANCHOR_PATH,
) -> list[dict]:
    init_look_schema(con)
    retained = load_retained_looks(
        con, scored, registration_sha256, require_reached=False,
        anchor_path=anchor_path,
    )
    previous_rows = con.execute(
        "SELECT look_sha256 FROM p15_evaluation_looks WHERE policy_id=? "
        "AND registration_sha256=? ORDER BY look_sessions",
        [POLICY_ID, registration_sha256],
    ).fetchall()
    previous = None if not previous_rows else previous_rows[-1][0]
    terminal = bool(retained and retained[-1]["status"] in {"pass", "kill"})
    for size in LOOKS[len(retained):]:
        if terminal or len(scored) < size:
            break
        result = _look(scored, size)
        result["through_market_date"] = scored[size - 1]["market_date"]
        result["evaluated_at"] = max(row["evaluated_at"] for row in scored[:size])
        prefix_sha = _look_source_prefix(scored, size)
        evaluated = evaluated_at.astimezone(timezone.utc)
        body = {
            "schema_version": 1, "policy_id": POLICY_ID,
            "registration_sha256": registration_sha256, "look_sessions": size,
            "through_market_date": result["through_market_date"],
            "evaluated_at": evaluated.isoformat(),
            "source_prefix_sha256": prefix_sha,
            "previous_look_sha256": previous, "result": result,
        }
        look_sha = canonical_sha256(body)
        con.execute(
            "INSERT INTO p15_evaluation_looks VALUES (?,?,?,?,?,?,?,?,?,?)",
            [1, POLICY_ID, registration_sha256, size,
             date.fromisoformat(result["through_market_date"]),
             evaluated.replace(tzinfo=None), prefix_sha, previous,
             json.dumps(result, sort_keys=True, separators=(",", ":")), look_sha],
        )
        con.execute(
            "INSERT INTO p15_evaluation_look_anchors "
            "(policy_id,registration_sha256,look_sessions,look_sha256) "
            "VALUES (?,?,?,?)",
            [POLICY_ID, registration_sha256, size, look_sha],
        )
        retained.append(result)
        previous = look_sha
        terminal = result["status"] in {"pass", "kill"}
    return retained


def primary(
    con: duckdb.DuckDBPyConnection, generated_at: datetime, *,
    persist_looks: bool = False, registration_sha: str | None = None,
) -> dict:
    rows = _primary_rows(con, generated_at)
    if not rows:
        next_date = generated_at.date()
        for _ in range(65):
            next_date = nyse.next_session(next_date)
        return {"status": "not_initialized", "candidate_count": 0,
                "scored_session_count": 0, "insufficient_session_count": 0,
                "immature_session_count": 0, "missing_mature_label_count": 0,
                "looks": [], "book_look_dates": [], "next_look": 60,
                "earliest_next_look_date": next_date.isoformat()}
    sessions: dict[date, list[dict]] = {}
    for row in rows:
        sessions.setdefault(row["market_date"], []).append(row)
    scored, insufficient, immature, missing, immature_dates = [], 0, 0, 0, []
    diagnostic_rows = []
    for market_date, members in sorted(sessions.items()):
        eligible = [row for row in members if _scores(row, 5) is not None]
        mature = _mature(con, market_date, 5, generated_at)
        missing_rows = [row for row in eligible if 5 not in row["labels"]]
        past_grace = _mature(
            con, market_date, 5 + MISSING_LABEL_GRACE_SESSIONS, generated_at,
        )
        if not mature or (missing_rows and not past_grace):
            possible = [scores for row in eligible if (scores := _scores(row, 5)) is not None]
            if (len(possible) < 20 or len({item[0] for item in possible}) == 1
                    or len({item[1] for item in possible}) == 1):
                insufficient += 1
            else:
                immature += 1
                immature_dates.append(market_date)
            continue
        missing += len(missing_rows)
        result = _session_ics(members, 5)
        diagnostic_rows.extend(result.pop("rows"))
        result["market_date"] = market_date.isoformat()
        if result["status"] == "scored":
            scored.append(result)
        else:
            insufficient += 1
    registered = registration_sha or registration_sha256()
    if persist_looks and not missing and not immature:
        looks = persist_reached_looks(
            con, scored, registered, evaluated_at=generated_at,
        )
    else:
        looks = load_retained_looks(con, scored, registered)
    terminal = next(
        (item["status"] for item in looks if item["status"] in {"pass", "kill"}),
        None,
    )
    status = "invalid" if missing else terminal or "collecting"
    retained_sizes = {item["look"] for item in looks}
    next_look = None if terminal else next(
        (size for size in LOOKS if size not in retained_sizes), None,
    )
    book_look_dates = [{
        "look": item["look"], "through_market_date": item["through_market_date"],
        "evaluated_at": item["evaluated_at"],
    } for item in looks]
    next_date = None
    if next_look is not None:
        maturities = []
        for market_date in immature_dates:
            maturity = market_date
            for _ in range(5 + MISSING_LABEL_GRACE_SESSIONS):
                maturity = nyse.next_session(maturity)
            maturities.append(max(maturity, generated_at.date()))
        decision_day = generated_at.date()
        remaining = max(0, next_look - len(scored))
        while len(maturities) < remaining:
            decision_day = nyse.next_session(decision_day)
            maturity = decision_day
            for _ in range(5):
                maturity = nyse.next_session(maturity)
            maturities.append(maturity)
        next_date = (
            sorted(maturities)[max(1, remaining) - 1]
            if maturities else generated_at.date()
        )
    h10 = [_session_ics(members, 10) for _day, members in sorted(sessions.items())]
    h10 = [item for item in h10 if item["status"] == "scored"]
    diagnostics = _diagnostics(diagnostic_rows)
    diagnostics["h10"] = {
        "scored_session_count": len(h10),
        "mean_model_ic": _mean([item["model_ic"] for item in h10]),
        "mean_baseline_ic": _mean([item["baseline_ic"] for item in h10]),
    }
    return {"status": status, "candidate_count": len(rows),
            "scored_session_count": len(scored),
            "insufficient_session_count": insufficient,
            "immature_session_count": immature, "missing_mature_label_count": missing,
            "looks": looks, "book_look_dates": book_look_dates, "next_look": next_look,
            "earliest_next_look_date": None if next_date is None else next_date.isoformat(),
            "diagnostics": diagnostics}


def _series_metrics(values: list[tuple[date, float]]) -> dict:
    equity = [item[1] for item in values]
    peak, drawdown = None, None
    for value in equity:
        peak = value if peak is None else max(peak, value)
        drawdown = value / peak - 1 if drawdown is None else min(drawdown, value / peak - 1)
    returns = {(values[index - 1][0], values[index][0]):
               values[index][1] / values[index - 1][1] - 1
               for index in range(1, len(values)) if values[index - 1][1] > 0
               and nyse.next_session(values[index - 1][0]) == values[index][0]}
    return {"start_date": None if not values else values[0][0].isoformat(),
            "end_date": None if not values else values[-1][0].isoformat(),
            "calendar_days": 0 if len(values) < 2 else (values[-1][0] - values[0][0]).days,
            "maximum_drawdown": drawdown, "returns": returns}


def books(con: duckdb.DuckDBPyConnection, primary_result: dict | None = None) -> dict:
    required = ("p15_book_contracts", "p15_book_windows", "p15_book_fills",
                "p15_order_intents", "portfolios")
    if not all(table_exists(con, table) for table in required):
        return {"status": "not_initialized", "books": [], "comparisons": []}
    contracts = con.execute(
        "SELECT c.portfolio_id,p.active,p.initial_cash FROM p15_book_contracts c "
        "JOIN portfolios p ON p.id=c.portfolio_id ORDER BY c.portfolio_id"
    ).fetchall()
    if {row[0] for row in contracts} != set(BOOK_IDS):
        raise P15EvaluationError("P15 book cohort differs")
    primary_result = primary_result or {"status": "collecting", "book_look_dates": []}
    primary_status = primary_result["status"]
    book_looks = primary_result.get("book_look_dates", [])
    latest_look = book_looks[-1] if book_looks else None
    look_date = None if latest_look is None else datetime.fromisoformat(
        latest_look["evaluated_at"]
    ).date()
    output, series = [], {}
    for portfolio_id, active, initial_cash in contracts:
        values = [(row[0], float(row[1])) for row in con.execute(
            "SELECT market_date,equity FROM p15_book_windows WHERE portfolio_id=? "
            "ORDER BY market_date", [portfolio_id],
        ).fetchall()]
        evaluated_values = values if look_date is None else [row for row in values
                                                             if row[0] <= look_date]
        metrics = _series_metrics(evaluated_values)
        returns = metrics.pop("returns")
        closed = int(con.execute(
            "SELECT COUNT(*) FROM p15_order_intents i JOIN p15_book_fills f ON f.intent_id=i.id "
            "WHERE i.portfolio_id=? AND i.side='sell' AND i.ticker<>'SPY' AND i.status='filled' "
            "AND (? IS NULL OR f.fill_date<=?)", [portfolio_id, look_date, look_date],
        ).fetchone()[0])
        turnover = float(con.execute(
            "SELECT COALESCE(SUM(ABS(qty*fill_px)),0) FROM p15_book_fills "
            "WHERE portfolio_id=? AND (? IS NULL OR fill_date<=?)",
            [portfolio_id, look_date, look_date],
        ).fetchone()[0])
        series[portfolio_id] = returns if look_date is not None else {}
        output.append({"portfolio_id": portfolio_id, "active": bool(active), **metrics,
                       "closed_trade_count": closed, "turnover_notional": turnover,
                       "turnover_over_initial_cash": None if not initial_cash else
                       turnover / float(initial_cash),
                       "comparison_eligible": metrics["calendar_days"] >= 90 and closed >= 30})
    by_id = {item["portfolio_id"]: item for item in output}
    comparisons = []
    for challenger in (BOOK_IDS[0], BOOK_IDS[2]):
        keys = sorted(set(series[challenger]) & set(series[BOOK_IDS[1]]))
        deltas = [series[challenger][key] - series[BOOK_IDS[1]][key] for key in keys]
        interval = _interval(deltas)
        eligible = by_id[challenger]["comparison_eligible"] and by_id[BOOK_IDS[1]][
            "comparison_eligible"
        ]
        positive = bool(eligible and interval["lower"] is not None and interval["lower"] > 0)
        final_look = latest_look is not None and latest_look["look"] == LOOKS[-1]
        status = ("killed" if primary_status == "kill" and eligible else
                  "inconclusive" if final_look and not positive else
                  "ready" if eligible else "collecting")
        comparisons.append({"challenger": challenger, "control": BOOK_IDS[1],
                            "look": None if latest_look is None else latest_look["look"],
                            "evaluated_through": None if look_date is None else look_date.isoformat(),
                            "paired_return_count": len(deltas), "eligible": eligible,
                            "status": status, "delta": interval,
                            "positive_lower_bound": positive})
    drawdown_ok = bool(output) and all(item["maximum_drawdown"] is not None
                                      and item["maximum_drawdown"] >= -0.2 for item in output)
    for comparison in comparisons:
        comparison["promotion_status"] = (
            "pass" if primary_status == "pass" and drawdown_ok
            and comparison["positive_lower_bound"] else comparison["status"]
        )
    status = "inactive" if not any(row[1] for row in contracts) else "collecting"
    if status != "inactive" and primary_status == "kill":
        status = "killed"
    elif any(item["promotion_status"] == "pass" for item in comparisons):
        status = "pass"
    elif status != "inactive" and latest_look is not None \
            and latest_look["look"] == LOOKS[-1] and primary_status == "pass":
        status = "inconclusive"
    return {"status": status, "books": output, "comparisons": comparisons}


def preopen(con: duckdb.DuckDBPyConnection, generated_at: datetime) -> dict:
    required = ("p15_preopen_runs", "p15_preopen_decisions", "p15_limit_attempts",
                "p15_limit_labels")
    if not all(table_exists(con, table) for table in required):
        return {"status": "not_initialized", "run_count": 0, "books": []}
    cutoff = generated_at.replace(tzinfo=None)
    run_count = int(con.execute(
        "SELECT COUNT(*) FROM p15_preopen_runs WHERE completed_at<=?", [cutoff]
    ).fetchone()[0])
    output = []
    for book in (BOOK_IDS[0], BOOK_IDS[2]):
        rows = con.execute(
            "SELECT a.outcome,l.net_excess_return FROM p15_preopen_decisions d "
            "JOIN p15_preopen_runs r ON r.id=d.run_id "
            "LEFT JOIN (SELECT intent_id,outcome FROM p15_limit_attempts "
            "WHERE outcome LIKE 'cancelled_%' AND attempt_date<=? QUALIFY ROW_NUMBER() OVER "
            "(PARTITION BY intent_id ORDER BY attempt_date DESC)=1) a ON a.intent_id=d.intent_id "
            "LEFT JOIN p15_limit_labels l ON l.intent_id=d.intent_id AND l.labeled_at<=? "
            "WHERE r.status='completed' AND d.portfolio_id=? AND d.decision='cancel' "
            "AND r.completed_at<=? AND d.applied_at<=? ORDER BY d.id",
            [generated_at.date(), cutoff, book, cutoff, cutoff],
        ).fetchall()
        effective = [row for row in rows if row[0] == "cancelled_would_fill"]
        saved = [-10_000 * float(row[1]) for row in effective if row[1] is not None]
        output.append({"portfolio_id": book, "cancel_count": len(rows),
                       "effective_cancel_count": len(effective),
                       "ineffective_limit_miss_count": sum(
                           row[0] == "cancelled_limit_not_reached" for row in rows),
                       "pending_or_other_attempt_count": sum(row[0] is None for row in rows),
                       "pending_label_count": sum(
                           row[0] == "cancelled_would_fill" and row[1] is None for row in rows),
                       "mature_effective_cancel_count": len(saved),
                       "cancel_hit_rate": _mean([float(value > 0) for value in saved]),
                       "mean_saved_bp": _mean(saved)})
    return {"status": "collecting" if run_count else "waiting",
            "run_count": run_count, "books": output}


def _event_basis(rows: list[tuple]) -> dict:
    usable = []
    for decision_id, raw, net, missing in rows:
        payload = json.loads(raw)
        score = _finite_number(payload.get("expected_excess_bp_5"))
        if score is not None:
            usable.append((score, float(net), missing, int(decision_id)))
    if len(usable) < 5:
        status, reason = "unavailable", "fewer_than_5_labels"
    elif len({row[0] for row in usable}) == 1:
        status, reason = "unavailable", "constant_model_score"
    elif len({row[1] for row in usable}) == 1:
        status, reason = "unavailable", "constant_outcome"
    else:
        status, reason = "available", None
    ordered = sorted(usable, key=lambda row: (-row[0], row[3]))
    size = len(ordered) // 5
    return {"status": status, "reason": reason, "label_count": len(usable),
            "ic": None if reason else spearman([row[0] for row in usable],
                                                [row[1] for row in usable]),
            "top_bottom_quintile_spread": None if not size else
            _mean([row[1] for row in ordered[:size]]) - _mean(
                [row[1] for row in ordered[-size:]]),
            "missing_status_counts": {value: sum(row[2] == value for row in usable)
                                      for value in sorted({row[2] for row in usable})}}


def events(con: duckdb.DuckDBPyConnection, generated_at: datetime) -> dict:
    required = ("p15_event_windows", "p15_event_decisions", "p15_event_labels",
                "p15_event_triggers")
    if not all(table_exists(con, table) for table in required):
        return {"status": "not_initialized", "window_count": 0, "decision_count": 0,
                "by_basis": {}}
    cutoff = generated_at.replace(tzinfo=None)
    decisions = con.execute(
        "SELECT d.id,d.latency_ms,d.scoring_status,d.decision_at FROM p15_event_decisions d "
        "JOIN p15_event_windows w USING(window_id) WHERE d.decision_at<=? "
        "AND w.status<>'running' ORDER BY d.id", [cutoff],
    ).fetchall()
    latencies = [(float(row[1]), row[2]) for row in decisions]
    by_basis = {}
    for basis in ("next_bar", "next_session_open"):
        rows = con.execute(
            "SELECT d.id,d.decision_payload,l.net_excess_return,l.missing_bar_status "
            "FROM p15_event_decisions d JOIN p15_event_labels l ON l.decision_id=d.id "
            "JOIN p15_event_windows w USING(window_id) "
            "WHERE d.scoring_status='available' AND d.decision_at<=? AND l.labeled_at<=? "
            "AND w.status<>'running' AND l.horizon_sessions=5 AND l.label_basis=? ORDER BY d.id",
            [cutoff, cutoff, basis],
        ).fetchall()
        metric = _event_basis(rows)
        labeled_ids = {row[0] for row in rows}
        missing = 0
        for decision_id, _latency, status, decision_at in decisions:
            if status != "available" or decision_id in labeled_ids:
                continue
            if basis == "next_bar":
                day = decision_at.replace(tzinfo=timezone.utc).astimezone(
                    p15_event_sources.ET
                ).date()
                mature = bool(con.execute(
                    f"SELECT COUNT(DISTINCT date)>=5 FROM prices WHERE ticker='SPY' "
                    f"AND date>=? AND fetched_at IS NOT NULL AND fetched_at<=? AND {REAL_BAR_SQL}",
                    [day, cutoff],
                ).fetchone()[0]) if table_exists(con, "prices") else False
            else:
                mature = _mature(con, decision_at.date(), 5, generated_at)
            missing += mature
        metric["missing_mature_label_count"] = missing
        if missing:
            metric.update(status="invalid", reason="missing_mature_labels")
        by_basis[basis] = metric
    return {"status": "invalid" if any(item["status"] == "invalid"
                                        for item in by_basis.values()) else "collecting",
            "window_count": int(con.execute(
                "SELECT COUNT(*) FROM p15_event_windows WHERE observed_at<=?", [cutoff]
            ).fetchone()[0]),
            "decision_count": len(latencies),
            "unavailable_count": sum(row[1] == "unavailable" for row in latencies),
            "skipped_rate_limit_count": int(con.execute(
                "SELECT COUNT(*) FROM p15_event_triggers "
                "WHERE status='skipped_rate_limit' AND triggered_at<=?", [cutoff]
            ).fetchone()[0]), "p95_latency_ms_all": _percentile(
                [row[0] for row in latencies], 0.95),
            "p95_latency_ms_available": _percentile(
                [row[0] for row in latencies if row[1] == "available"], 0.95),
            "latency_target_ms": 600_000, "by_basis": by_basis}


def p8_rule(con: duckdb.DuckDBPyConnection, generated_at: datetime) -> dict:
    sessions, cohort_start = 0, None
    if table_exists(con, "agent_evaluation_traces"):
        cohort_start, sessions = con.execute(
            "SELECT MIN(market_date),COUNT(DISTINCT market_date) FROM agent_evaluation_traces "
            "WHERE policy_id='nightly_opportunity_tool_v1' AND terminal_status='completed' "
            "AND market_date<=?", [generated_at.date()]
        ).fetchone()
    returns = []
    if all(table_exists(con, table) for table in (
        "daily_opportunity_exit_rules", "daily_opportunity_exit_events", "sim_fills"
    )):
        returns = [float(row[1]) / float(row[0]) - 1 for row in con.execute(
            "SELECT entry.fill_px,exit.fill_px FROM daily_opportunity_exit_rules r "
            "JOIN sim_fills entry ON entry.order_id=r.entry_order_id "
            "JOIN daily_opportunity_exit_events e ON e.rule_sha256=r.rule_sha256 "
            "JOIN sim_fills exit ON exit.order_id=e.exit_order_id "
            "WHERE entry.portfolio_id='daily_opportunity_agent_v1' "
            "AND exit.portfolio_id='daily_opportunity_agent_v1' AND exit.fill_date<=? "
            "ORDER BY exit.fill_date,r.ticker", [generated_at.date()]
        ).fetchall() if row[0] and row[1]]
    elapsed = 0 if cohort_start is None else max(0, (generated_at.date() - cohort_start).days)
    ready = elapsed >= 90 and sessions >= 60
    interval = _interval(returns, alpha=0.05, lag=0)
    return {"status": "review_ready" if ready else "collecting",
            "cohort_start": None if cohort_start is None else cohort_start.isoformat(),
            "elapsed_calendar_days": elapsed,
            "completed_session_count": sessions, "minimum_calendar_days": 90,
            "minimum_completed_sessions": 60, "completed_round_trip_count": len(returns),
            "trade_expectancy_status": "reportable" if ready and len(returns) >= 20
            else "withheld", "mean_net_round_trip_return": _mean(returns),
            "lower_confidence_bound": interval["lower"], "lower_bound_is_gate": False,
            "promotion_authority": "none"}


def observer_pairing(con: duckdb.DuckDBPyConnection, generated_at: datetime) -> dict:
    if not all(table_exists(con, table) for table in (
        "agent_evaluation_traces", "agent_evaluation_decisions", "agent_evaluation_labels_v2"
    )):
        return {"hourly_market_watch_v5": 0, "four_hour_opportunity_review_v5": 0}
    result = {}
    for policy in ("hourly_market_watch_v5", "four_hour_opportunity_review_v5"):
        result[policy] = int(con.execute(
            "SELECT COUNT(*) FROM agent_evaluation_decisions d "
            "JOIN agent_evaluation_traces t ON t.id=d.trace_id "
            "JOIN agent_evaluation_labels_v2 l ON l.decision_id=d.id "
            "JOIN agent_evaluation_decisions nd ON nd.ticker=d.ticker "
            "JOIN agent_evaluation_traces nt ON nt.id=nd.trace_id AND nt.market_date=t.market_date "
            "JOIN agent_evaluation_labels_v2 nl ON nl.decision_id=nd.id "
            "AND nl.horizon_sessions=l.horizon_sessions AND nl.label_basis=l.label_basis "
            "AND nl.price_prefix_sha256=l.price_prefix_sha256 "
            "WHERE t.policy_id=? AND nt.policy_id='nightly_opportunity_tool_v1' "
            "AND l.label_basis='common_entry' AND l.horizon_sessions=5 "
            "AND t.observed_at<=? AND nt.observed_at<=? AND l.labeled_at<=? AND nl.labeled_at<=?",
            [policy, *[generated_at.replace(tzinfo=None)] * 4],
        ).fetchone()[0])
    return result


def project(con: duckdb.DuckDBPyConnection, *, generated_at: datetime) -> dict:
    primary_result = primary(con, generated_at)
    book_result = books(con, primary_result)
    preopen_result, event_result = preopen(con, generated_at), events(con, generated_at)
    status = primary_result["status"]
    if status == "not_initialized" and book_result["status"] == "inactive":
        status = "inactive"
    promotion_ready = any(item["promotion_status"] == "pass"
                          for item in book_result["comparisons"])
    if status == "pass" and not promotion_ready:
        status = "inconclusive" if book_result["status"] == "inconclusive" else "collecting"
    if event_result.get("status") == "invalid":
        status = "invalid"
    return {
        "p15": {"schema_version": 1, "generated_at": generated_at.astimezone(
                    timezone.utc
                ).isoformat(), "status": status, "primary": primary_result,
                "books": book_result, "preopen": preopen_result, "events": event_result,
                "observer_pairing": observer_pairing(con, generated_at),
                "promotion_ready": promotion_ready,
                "promotion_authority": "owner_review_required"},
        "p8_evaluation": p8_rule(con, generated_at),
    }
