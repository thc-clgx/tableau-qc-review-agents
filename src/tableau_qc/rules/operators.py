"""Comparison operators available to YAML rules.

Operators are pure functions over already-normalised Python values. They never
see XML and never mutate state, which keeps rule evaluation deterministic.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, Sequence

OperatorFn = Callable[[Any, Any], bool]


class OperatorError(Exception):
    """Raised when an operator is used with an unusable expected value."""


def _as_number(value: Any) -> float:
    if isinstance(value, bool):
        raise OperatorError(f"Expected a number, got boolean {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise OperatorError(f"Expected a number, got {value!r}") from exc
    raise OperatorError(f"Expected a number, got {value!r}")


def _as_sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    if value is None:
        return []
    return [value]


def _normalise(value: Any, *, case_sensitive: bool = True) -> Any:
    if isinstance(value, str) and not case_sensitive:
        return value.casefold()
    return value


def op_equals(observed: Any, expected: Any) -> bool:
    if isinstance(observed, (int, float)) and isinstance(expected, (int, float)):
        return float(observed) == float(expected)
    return observed == expected


def op_not_equals(observed: Any, expected: Any) -> bool:
    return not op_equals(observed, expected)


def op_greater_than(observed: Any, expected: Any) -> bool:
    return _as_number(observed) > _as_number(expected)


def op_greater_than_or_equal(observed: Any, expected: Any) -> bool:
    return _as_number(observed) >= _as_number(expected)


def op_less_than(observed: Any, expected: Any) -> bool:
    return _as_number(observed) < _as_number(expected)


def op_less_than_or_equal(observed: Any, expected: Any) -> bool:
    return _as_number(observed) <= _as_number(expected)


def op_between(observed: Any, expected: Any) -> bool:
    bounds = _as_sequence(expected)
    if len(bounds) != 2:
        raise OperatorError("'between' expects exactly two bounds")
    low, high = _as_number(bounds[0]), _as_number(bounds[1])
    return low <= _as_number(observed) <= high


def op_in(observed: Any, expected: Any) -> bool:
    return observed in _as_sequence(expected)


def op_not_in(observed: Any, expected: Any) -> bool:
    return observed not in _as_sequence(expected)


def op_contains(observed: Any, expected: Any) -> bool:
    if isinstance(observed, str):
        return str(expected) in observed
    return expected in _as_sequence(observed)


def op_not_contains(observed: Any, expected: Any) -> bool:
    return not op_contains(observed, expected)


def op_all_in(observed: Any, expected: Any) -> bool:
    """Every observed value must appear in the allowed set."""
    allowed = {_normalise(v, case_sensitive=False) for v in _as_sequence(expected)}
    values = [_normalise(v, case_sensitive=False) for v in _as_sequence(observed)]
    return all(value in allowed for value in values)


def op_any_in(observed: Any, expected: Any) -> bool:
    allowed = {_normalise(v, case_sensitive=False) for v in _as_sequence(expected)}
    values = [_normalise(v, case_sensitive=False) for v in _as_sequence(observed)]
    return any(value in allowed for value in values)


def op_none_in(observed: Any, expected: Any) -> bool:
    return not op_any_in(observed, expected)


def op_matches(observed: Any, expected: Any) -> bool:
    return re.search(str(expected), str(observed)) is not None


def op_not_matches(observed: Any, expected: Any) -> bool:
    return not op_matches(observed, expected)


def op_is_true(observed: Any, expected: Any = None) -> bool:
    return observed is True


def op_is_false(observed: Any, expected: Any = None) -> bool:
    return observed is False


def op_is_empty(observed: Any, expected: Any = None) -> bool:
    if observed is None:
        return True
    if isinstance(observed, (str, list, tuple, set, dict)):
        return len(observed) == 0
    return False


def op_is_not_empty(observed: Any, expected: Any = None) -> bool:
    return not op_is_empty(observed)


def op_length_less_than_or_equal(observed: Any, expected: Any) -> bool:
    return len(_as_sequence(observed)) <= _as_number(expected)


def op_length_greater_than_or_equal(observed: Any, expected: Any) -> bool:
    return len(_as_sequence(observed)) >= _as_number(expected)


def op_length_equals(observed: Any, expected: Any) -> bool:
    return len(_as_sequence(observed)) == _as_number(expected)


def op_starts_with(observed: Any, expected: Any) -> bool:
    return str(observed).startswith(str(expected))


def op_ends_with(observed: Any, expected: Any) -> bool:
    return str(observed).endswith(str(expected))


def op_equals_ignore_case(observed: Any, expected: Any) -> bool:
    return str(observed).casefold() == str(expected).casefold()


OPERATORS: Dict[str, OperatorFn] = {
    "equals": op_equals,
    "equals_ignore_case": op_equals_ignore_case,
    "not_equals": op_not_equals,
    "greater_than": op_greater_than,
    "greater_than_or_equal": op_greater_than_or_equal,
    "less_than": op_less_than,
    "less_than_or_equal": op_less_than_or_equal,
    "between": op_between,
    "in": op_in,
    "not_in": op_not_in,
    "contains": op_contains,
    "not_contains": op_not_contains,
    "all_in": op_all_in,
    "any_in": op_any_in,
    "none_in": op_none_in,
    "matches": op_matches,
    "not_matches": op_not_matches,
    "is_true": op_is_true,
    "is_false": op_is_false,
    "is_empty": op_is_empty,
    "is_not_empty": op_is_not_empty,
    "length_less_than_or_equal": op_length_less_than_or_equal,
    "length_greater_than_or_equal": op_length_greater_than_or_equal,
    "length_equals": op_length_equals,
    "starts_with": op_starts_with,
    "ends_with": op_ends_with,
}

#: Operators that do not require an ``value:`` entry in YAML.
VALUELESS_OPERATORS = frozenset(
    {"is_true", "is_false", "is_empty", "is_not_empty"}
)


def get_operator(name: str) -> OperatorFn:
    try:
        return OPERATORS[name]
    except KeyError as exc:
        raise OperatorError(
            f"Unknown operator '{name}'. Available: {', '.join(sorted(OPERATORS))}"
        ) from exc


def operator_names() -> Iterable[str]:
    return sorted(OPERATORS)
