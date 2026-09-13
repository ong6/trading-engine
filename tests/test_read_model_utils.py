"""Tests for shared public read-model primitives."""

from datetime import date, datetime

import pytest

from server import read_model_utils


def test_public_date_accepts_exact_date_and_rejects_datetime():
    value = date(2026, 9, 4)

    assert read_model_utils.require_public_date(value, "event date") is value
    with pytest.raises(ValueError, match="public event date is invalid"):
        read_model_utils.require_public_date(datetime(2026, 9, 4), "event date")


@pytest.mark.parametrize("value", [None, "", "   ", 1])
def test_public_nonempty_string_rejects_non_strings_and_blank_text(value):
    with pytest.raises(ValueError, match="public label is invalid"):
        read_model_utils.require_public_nonempty_string(value, "label")


def test_public_nonempty_string_preserves_display_text():
    assert read_model_utils.require_public_nonempty_string("  label  ", "label") == "  label  "


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", " book", "book ", "book\nother", "book\tother", "book\x00other"],
)
def test_public_portfolio_id_rejects_noncanonical_text(value):
    with pytest.raises(ValueError, match="portfolio identifier is invalid"):
        read_model_utils.require_public_portfolio_id(value)


def test_public_portfolio_id_accepts_unicode_at_exact_character_budget():
    value = "💥" * read_model_utils.PUBLIC_PORTFOLIO_ID_MAX_CHARS

    assert read_model_utils.require_public_portfolio_id(value) == value


def test_public_portfolio_id_rejects_value_above_character_budget():
    value = "x" * (read_model_utils.PUBLIC_PORTFOLIO_ID_MAX_CHARS + 1)

    with pytest.raises(ValueError, match="portfolio identifier is invalid"):
        read_model_utils.require_public_portfolio_id(value)


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", " AAA", "AAA ", "AA\nA", "AA\tA", "AA\x00A"],
)
def test_public_ticker_rejects_noncanonical_text(value):
    with pytest.raises(ValueError, match="ticker is invalid"):
        read_model_utils.require_public_ticker(value)


def test_public_ticker_accepts_unicode_at_exact_character_budget():
    value = "💥" * read_model_utils.PUBLIC_TICKER_MAX_CHARS

    assert read_model_utils.require_public_ticker(value) == value


def test_public_ticker_rejects_value_above_character_budget():
    value = "x" * (read_model_utils.PUBLIC_TICKER_MAX_CHARS + 1)

    with pytest.raises(ValueError, match="ticker is invalid"):
        read_model_utils.require_public_ticker(value)


def test_public_positive_integer_accepts_exact_json_safe_maximum():
    maximum = read_model_utils.PUBLIC_SAFE_INTEGER_MAX

    assert read_model_utils.require_public_positive_integer(maximum) == maximum


@pytest.mark.parametrize(
    "value",
    [
        read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1,
        0,
        -1,
        True,
        False,
        1.0,
        None,
    ],
)
def test_public_positive_integer_rejects_non_interoperable_values(value):
    with pytest.raises(ValueError, match="public identifier is invalid"):
        read_model_utils.require_public_positive_integer(value)


@pytest.mark.parametrize("value", [0, read_model_utils.PUBLIC_SAFE_INTEGER_MAX])
def test_public_nonnegative_integer_accepts_exact_safe_boundaries(value):
    assert read_model_utils.require_public_nonnegative_integer(value) == value


@pytest.mark.parametrize(
    "value",
    [
        read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1,
        -1,
        True,
        False,
        0.0,
        None,
    ],
)
def test_public_nonnegative_integer_rejects_non_interoperable_values(value):
    with pytest.raises(ValueError, match="public count is invalid"):
        read_model_utils.require_public_nonnegative_integer(value)


@pytest.mark.parametrize("value", [-1.5, 0, 2, 3.5])
def test_public_finite_number_accepts_finite_numbers(value):
    assert read_model_utils.require_public_finite_number(value, "metric") == value


@pytest.mark.parametrize("value", [True, False, None, "1", float("nan"), float("inf"), 10**309])
def test_public_finite_number_rejects_non_numeric_or_nonfinite_values(value):
    with pytest.raises(ValueError, match="public metric is invalid"):
        read_model_utils.require_public_finite_number(value, "metric")


@pytest.mark.parametrize("value", [1, 2.5])
def test_public_positive_number_accepts_positive_finite_numbers(value):
    assert read_model_utils.require_public_positive_number(value, "price") == value


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("-inf")])
def test_public_positive_number_rejects_nonpositive_or_nonfinite_values(value):
    with pytest.raises(ValueError, match="public price is invalid"):
        read_model_utils.require_public_positive_number(value, "price")


@pytest.mark.parametrize("value", [0, 2.5])
def test_public_nonnegative_number_accepts_finite_boundaries(value):
    assert read_model_utils.require_public_nonnegative_number(value, "volume") == value


@pytest.mark.parametrize("value", [-1, True, float("nan"), float("inf")])
def test_public_nonnegative_number_rejects_negative_or_nonfinite_values(value):
    with pytest.raises(ValueError, match="public volume is invalid"):
        read_model_utils.require_public_nonnegative_number(value, "volume")
