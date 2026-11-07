"""Load-time semantic validation of the rule repository.

The schema in :mod:`tableau_qc.rules.schema` checks a rule's *structure*. This
module checks its *meaning* against the normalised model and the checklist, so
that a typo fails when the rules are loaded rather than silently degrading to
MANUAL_REVIEW on a real workbook.

Three classes of defect are caught:

* a ``field`` path that does not exist on the rule's scope;
* an ``operator`` used with a value it cannot accept;
* a ``checklist_ref`` that does not match a checklist cell.
"""

from __future__ import annotations

import re
import typing
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Type

from ..domain import models as domain_models
from .operators import VALUELESS_OPERATORS
from .schema import Condition, RuleDefinition

#: Rule scope -> the normalised class a rule of that scope is evaluated against.
SCOPE_MODELS: Dict[str, Type] = {
    "workbook": domain_models.Workbook,
    "dashboard": domain_models.Dashboard,
    "dashboard_zone": domain_models.DashboardZone,
    "dashboard_view_zone": domain_models.DashboardZone,
    "dashboard_filter_zone": domain_models.DashboardZone,
    "multi_select_filter_zone": domain_models.DashboardZone,
    "dashboard_image": domain_models.ImageObject,
    "mark_palette": domain_models.MarkPalette,
    "worksheet": domain_models.Worksheet,
    "used_worksheet": domain_models.Worksheet,
    "datasource": domain_models.DataSource,
    "calculated_field": domain_models.CalculatedField,
    "action": domain_models.DashboardAction,
    "worksheet_filter": domain_models.WorksheetFilter,
}

#: Operators that require their value to be a list.
LIST_VALUE_OPERATORS = frozenset(
    {"in", "not_in", "all_in", "any_in", "none_in", "between"}
)

#: Operators that require a numeric value.
NUMERIC_VALUE_OPERATORS = frozenset(
    {
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "length_less_than_or_equal",
        "length_greater_than_or_equal",
        "length_equals",
    }
)

#: Operators whose value is compiled as a regular expression.
REGEX_VALUE_OPERATORS = frozenset({"matches", "not_matches"})


class RuleValidationError(ValueError):
    """Raised when a rule is structurally valid but semantically wrong."""


def _unwrap(annotation: Any) -> Any:
    """Strip ``Optional[...]`` / ``List[...]`` down to the inner class."""
    origin = typing.get_origin(annotation)
    if origin is None:
        return annotation
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if not args:
        return annotation
    if origin in (list, set, tuple, frozenset):
        return args[0]
    if len(args) == 1:
        return _unwrap(args[0])
    return args[0]


def _resolved_hints(cls: Type) -> Dict[str, Any]:
    try:
        return typing.get_type_hints(cls, vars(domain_models))
    except Exception:  # pragma: no cover - defensive
        return {}


def _attribute_type(cls: Type, name: str) -> Optional[Any]:
    """Declared type of ``name`` on ``cls``, or ``None`` if not introspectable."""
    if is_dataclass(cls):
        hints = _resolved_hints(cls)
        if name in hints:
            return _unwrap(hints[name])
    attribute = getattr(cls, name, None)
    if isinstance(attribute, property) and attribute.fget is not None:
        hints = typing.get_type_hints(attribute.fget, vars(domain_models))
        if "return" in hints:
            return _unwrap(hints["return"])
    return None


def _has_attribute(cls: Type, name: str) -> bool:
    if hasattr(cls, name):
        return True
    if is_dataclass(cls):
        return any(f.name == name for f in dataclass_fields(cls))
    return False


def validate_field_path(scope: str, path: str) -> Optional[str]:
    """Validate a dotted field path against the model for ``scope``.

    Returns an error message, or ``None`` when the path is valid or cannot be
    introspected (an unannotated property stops the walk without failing).
    """
    cls = SCOPE_MODELS.get(scope)
    if cls is None:
        return None

    current: Optional[Type] = cls
    walked: List[str] = []
    for part in path.split("."):
        if current is None:
            return None  # type is not introspectable; accept the remainder
        if not _has_attribute(current, part):
            where = ".".join(walked) or current.__name__
            return f"'{path}' is not valid: '{part}' does not exist on {where}"
        walked.append(part)
        next_type = _attribute_type(current, part)
        current = next_type if isinstance(next_type, type) else None
    return None


def validate_condition_value(condition: Condition) -> Optional[str]:
    """Check the value is usable by the operator it is paired with."""
    operator = condition.operator
    value = condition.value

    if operator in VALUELESS_OPERATORS:
        if value is not None:
            return f"operator '{operator}' takes no 'value' (got {value!r})"
        return None

    if operator == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return "operator 'between' requires a list of exactly two bounds"
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
            return "operator 'between' requires two numeric bounds"
        return None

    if operator in LIST_VALUE_OPERATORS and not isinstance(value, (list, tuple)):
        return f"operator '{operator}' requires a list value (got {type(value).__name__})"

    if operator in NUMERIC_VALUE_OPERATORS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"operator '{operator}' requires a numeric value (got {value!r})"

    if operator in REGEX_VALUE_OPERATORS:
        if not isinstance(value, str):
            return f"operator '{operator}' requires a string pattern"
        try:
            re.compile(value)
        except re.error as exc:
            return f"operator '{operator}' has an invalid regular expression: {exc}"

    return None


def validate_rule(rule: RuleDefinition) -> List[str]:
    """Return every semantic problem found in one rule."""
    problems: List[str] = []
    seen_fields: Set[str] = set()

    for condition in list(rule.applies_when) + list(rule.assertions):
        error = validate_field_path(rule.scope, condition.field_path)
        if error:
            problems.append(error)
        error = validate_condition_value(condition)
        if error:
            problems.append(f"'{condition.field_path}': {error}")

    for condition in rule.assertions:
        if condition.field_path in seen_fields:
            problems.append(
                f"duplicate assertion on field '{condition.field_path}'; "
                "combine them into one condition"
            )
        seen_fields.add(condition.field_path)

    for field_path in rule.evidence_fields:
        error = validate_field_path(rule.scope, field_path)
        if error:
            problems.append(f"evidence_fields: {error}")

    return problems


def validate_repository(rules: Iterable[RuleDefinition]) -> List[str]:
    """Validate every rule, returning messages prefixed with the rule id."""
    problems: List[str] = []
    for rule in rules:
        problems.extend(f"[{rule.id}] {p}" for p in validate_rule(rule))
    return problems


def validate_checklist_references(
    rules: Iterable[RuleDefinition], checklist_cells: Sequence[str]
) -> List[str]:
    """Check every ``checklist_ref`` points at a real checklist question.

    ``checklist_cells`` holds ``"<sheet>!<cell>"`` strings built from the
    checklist definition.
    """
    known = set(checklist_cells)
    problems: List[str] = []
    for rule in rules:
        if rule.checklist_ref and rule.checklist_ref not in known:
            problems.append(
                f"[{rule.id}] checklist_ref '{rule.checklist_ref}' does not match "
                "any checklist question"
            )
    return problems


def unmapped_rule_ids(
    rules: Iterable[RuleDefinition], mapped_rule_ids: Iterable[str]
) -> List[str]:
    """Enabled rules that no checklist question consumes."""
    mapped = set(mapped_rule_ids)
    return sorted(r.id for r in rules if r.enabled and r.id not in mapped)
