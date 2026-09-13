"""Validate terminal walk-forward fold results and their statistics."""

from __future__ import annotations

import math
import re
from datetime import date

from engine.lib.provenance import canonical_sha256
from farm.walkforward.runner import summarize as summarize_folds
from server.status_validation import iso_date
from server.walkforward_artifact_identity import positive_number


def _positive_int(value: object, message: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(message)
    return value


def _nonnegative_int(value: object, message: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(message)
    return value


def _finite_number(value: object, message: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(message)
    return float(value)


def _nonnegative_number(value: object, message: str) -> float:
    number = _finite_number(value, message)
    if number < 0:
        raise ValueError(message)
    return number


def _bounded_number(value: object, message: str, *, minimum: float, maximum: float) -> float:
    number = _finite_number(value, message)
    if not minimum <= number <= maximum:
        raise ValueError(message)
    return number


def _validate_stat_block(
    value: object,
    *,
    expected_start: date,
    expected_end: date,
    expected_base: float | None = None,
) -> tuple[int, float, float]:
    if not isinstance(value, dict):
        raise ValueError("invalid fold statistics")
    start = iso_date(value.get("start_date"), "invalid statistic start date")
    end = iso_date(value.get("end_date"), "invalid statistic end date")
    if start != expected_start or end != expected_end or start >= end:
        raise ValueError("statistic dates do not match fold sessions")
    n_sessions = _positive_int(value.get("n_sessions"), "invalid statistic session count")
    equity_start = positive_number(value.get("equity_start"), "invalid starting equity")
    equity_end = _nonnegative_number(value.get("equity_end"), "invalid ending equity")
    return_base = positive_number(value.get("return_base"), "invalid return base")
    years = positive_number(value.get("years"), "invalid statistic years")
    if expected_base is not None and not math.isclose(return_base, expected_base):
        raise ValueError("train return base does not match initial cash")
    if expected_base is not None and not math.isclose(equity_start, expected_base):
        raise ValueError("train starting equity does not match initial cash")
    if not math.isclose(years, (end - start).days / 365.25):
        raise ValueError("statistic years do not match dates")
    _validate_performance_metrics(value, equity_end, return_base)
    return n_sessions, equity_start, equity_end


def _validate_monthly_equity(
    value: object,
    first_session: date,
    last_session: date,
    equity_end: float,
) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("invalid monthly equity")
    months = []
    equities = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("invalid monthly equity point")
        month = point[0]
        if not isinstance(month, str) or re.fullmatch(r"\d{4}-\d{2}", month) is None:
            raise ValueError("invalid monthly equity month")
        try:
            month_date = date.fromisoformat(f"{month}-01")
        except ValueError:
            raise ValueError("invalid monthly equity month") from None
        months.append(month_date)
        equities.append(_nonnegative_number(point[1], "invalid monthly equity value"))
    if months != sorted(set(months)):
        raise ValueError("monthly equity months are not unique and ordered")
    if months[0].strftime("%Y-%m") != first_session.strftime("%Y-%m"):
        raise ValueError("monthly equity does not start at the split session")
    if months[-1].strftime("%Y-%m") != last_session.strftime("%Y-%m"):
        raise ValueError("monthly equity does not reach the final session")
    if not math.isclose(equities[-1], equity_end):
        raise ValueError("monthly equity does not match ending equity")


def _validate_performance_metrics(value: dict, equity_end: float, return_base: float) -> None:
    total_return = _finite_number(value.get("total_return"), "invalid total return")
    years = positive_number(value.get("years"), "invalid statistic years")
    cagr = _finite_number(value.get("cagr"), "invalid CAGR")
    _nonnegative_number(value.get("vol_ann"), "invalid annualized volatility")
    _bounded_number(value.get("max_dd"), "invalid maximum drawdown", minimum=-1.0, maximum=0.0)
    _bounded_number(value.get("worst_month"), "invalid worst month", minimum=-1.0, maximum=math.inf)
    _bounded_number(value.get("bil_coverage"), "invalid BIL coverage", minimum=0.0, maximum=1.0)
    _finite_number(value.get("sharpe"), "invalid Sharpe")
    sharpe_ex_bil = value.get("sharpe_ex_bil")
    if sharpe_ex_bil is not None:
        _finite_number(sharpe_ex_bil, "invalid excess Sharpe")
    if total_return < -1.0 or not math.isclose(total_return, equity_end / return_base - 1.0):
        raise ValueError("total return does not match equity endpoints")
    try:
        expected_cagr = (equity_end / return_base) ** (1.0 / years) - 1.0
    except OverflowError:
        raise ValueError("invalid CAGR inputs") from None
    if not math.isfinite(expected_cagr) or not math.isclose(cagr, expected_cagr):
        raise ValueError("CAGR does not match equity endpoints")


def _successful_fold_sessions(fold: dict) -> tuple[date, date, date]:
    train_start = iso_date(fold.get("train_start"), "invalid fold train start")
    split_date = iso_date(fold.get("split_date"), "invalid fold split date")
    validate_end = iso_date(fold.get("validate_end"), "invalid fold validate end")
    first_session = iso_date(fold.get("first_session"), "invalid first session")
    split_session = iso_date(fold.get("split_session"), "invalid split session")
    last_session = iso_date(fold.get("last_session"), "invalid last session")
    if (
        not train_start
        <= first_session
        <= split_session
        <= split_date
        < last_session
        <= validate_end
    ):
        raise ValueError("fold sessions do not match fold boundaries")
    return first_session, split_session, last_session


def _successful_fold_statistics(
    fold: dict,
    initial_cash: float,
    first_session: date,
    split_session: date,
    last_session: date,
) -> tuple[int, int, float]:
    train_n, _train_start_equity, train_end_equity = _validate_stat_block(
        fold.get("train"),
        expected_start=first_session,
        expected_end=split_session,
        expected_base=initial_cash,
    )
    validate_n, validate_start_equity, validate_end_equity = _validate_stat_block(
        fold.get("validate"),
        expected_start=split_session,
        expected_end=last_session,
    )
    if not math.isclose(train_end_equity, validate_start_equity):
        raise ValueError("train and validate equity do not join")
    if not math.isclose(
        float(fold["validate"]["return_base"]), float(fold["validate"]["equity_start"])
    ):
        raise ValueError("validate return base does not match starting equity")
    return train_n, validate_n, validate_end_equity


def _validate_successful_fold(fold: dict, initial_cash: float) -> None:
    first_session, split_session, last_session = _successful_fold_sessions(fold)
    train_n, validate_n, validate_end_equity = _successful_fold_statistics(
        fold, initial_cash, first_session, split_session, last_session
    )
    sessions = _positive_int(fold.get("sessions"), "invalid fold session count")
    if sessions != train_n + validate_n - 1:
        raise ValueError("fold session count does not match statistics")
    n_fills = _positive_int(fold.get("n_fills"), "invalid fold fill count")
    n_validate_fills = _nonnegative_int(fold.get("n_validate_fills"), "invalid validate fill count")
    if n_validate_fills > n_fills:
        raise ValueError("validate fill count exceeds total fills")
    _validate_monthly_equity(
        fold.get("validate_monthly_equity"), split_session, last_session, validate_end_equity
    )


def validate_terminal_folds(
    folds: list,
    clamped_indices: set[int],
    initial_cash: float,
) -> None:
    statuses = [fold.get("status") if isinstance(fold, dict) else None for fold in folds]
    if any(status not in {"ok", "inert", "skipped"} for status in statuses):
        raise ValueError("invalid fold status")
    if any(
        fold.get("train_start_clamped_to_data_floor") != (fold["index"] in clamped_indices)
        for fold in folds
    ):
        raise ValueError("fold data-floor clamp disclosure does not match geometry")
    terminal_without_result = [fold for fold in folds if fold["status"] in {"inert", "skipped"}]
    if any(
        not isinstance(fold.get("reason"), str) or not fold["reason"].strip()
        for fold in terminal_without_result
    ):
        raise ValueError("terminal fold lacks reason")
    for fold in folds:
        if fold["status"] == "ok":
            _validate_successful_fold(fold, initial_cash)


def validate_summary(folds: list, summary: dict) -> None:
    if canonical_sha256(summary) != canonical_sha256(summarize_folds(folds)):
        raise ValueError("walk-forward summary does not match folds")
