"""Unit tests for rule operators."""

from __future__ import annotations

import pytest

from tableau_qc.rules.operators import OPERATORS, OperatorError, get_operator


@pytest.mark.parametrize(
    "name,observed,expected,result",
    [
        ("equals", 1600, 1600, True),
        ("equals", 1600.0, 1600, True),
        ("equals", 1200, 1600, False),
        ("equals_ignore_case", "arial", "Arial", True),
        ("not_equals", "Arial", "Calibri", True),
        ("greater_than", 11, 10, True),
        ("greater_than_or_equal", 10, 10, True),
        ("greater_than_or_equal", 9.5, 10, False),
        ("less_than", 5, 6, True),
        ("less_than_or_equal", 6, 6, True),
        ("less_than_or_equal", 7, 6, False),
        ("between", 12, [10, 15], True),
        ("between", 20, [10, 15], False),
        ("in", "Arial", ["Arial", "Arial Black"], True),
        ("not_in", "Calibri", ["Arial"], True),
        ("contains", "Arial Black", "Black", True),
        ("not_contains", ["a", "b"], "c", True),
        ("all_in", ["Arial", "Arial Black"], ["arial", "arial black"], True),
        ("all_in", ["Arial", "Calibri"], ["Arial"], False),
        ("all_in", [], ["Arial"], True),
        ("any_in", ["Calibri", "Arial"], ["Arial"], True),
        ("none_in", ["Calibri"], ["Arial"], True),
        ("matches", "Dashboard A", r"^Dashboard", True),
        ("not_matches", "Dashboard A", r"^Sheet", True),
        ("is_true", True, None, True),
        ("is_true", False, None, False),
        ("is_false", False, None, True),
        ("is_empty", [], None, True),
        ("is_not_empty", ["x"], None, True),
        ("length_less_than_or_equal", [1, 2, 3], 6, True),
        ("length_greater_than_or_equal", [1, 2], 2, True),
        ("length_equals", [1, 2], 2, True),
        ("starts_with", "Dashboard A", "Dash", True),
        ("ends_with", "Dashboard A", "A", True),
    ],
)
def test_operator_behaviour(name, observed, expected, result):
    assert get_operator(name)(observed, expected) is result


def test_unknown_operator_raises():
    with pytest.raises(OperatorError):
        get_operator("almost_equals")


def test_numeric_operator_rejects_non_numeric():
    with pytest.raises(OperatorError):
        get_operator("greater_than")("ten", 5)


def test_between_requires_two_bounds():
    with pytest.raises(OperatorError):
        get_operator("between")(5, [1])


def test_boolean_is_not_treated_as_number():
    with pytest.raises(OperatorError):
        get_operator("greater_than")(True, 0)


def test_operator_registry_is_complete():
    assert "equals" in OPERATORS
    assert all(callable(fn) for fn in OPERATORS.values())
