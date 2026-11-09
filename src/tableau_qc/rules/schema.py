"""Rule schema: declarative definition of a QC rule plus validation.

A rule file looks like::

    version: "1.0.0"
    metadata:
      name: Layout rules
      standard: Analytics Tableau Style Guide v2.0
    rules:
      - id: CTL-LAYOUT-001
        title: Dashboard width must be 1600 px
        scope: dashboard
        severity: HIGH
        assertions:
          - field: size.width
            operator: equals
            value: 1600
        on_missing: MANUAL_REVIEW
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..domain.findings import Severity, Status
from .operators import OPERATORS, VALUELESS_OPERATORS
from .selectors import SELECTORS

RULE_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._\-]{2,63}$")

#: Statuses a rule may fall back to when a value cannot be observed.
ALLOWED_MISSING_STATUSES = {Status.MANUAL_REVIEW, Status.NOT_APPLICABLE, Status.FAIL}

#: Statuses a rule may report when its assertions do not hold. Every Agent
#: Review question must resolve to a binary answer, so FAIL is the only option.
ALLOWED_VIOLATION_STATUSES = {Status.FAIL}

REQUIRED_RULE_KEYS = ("id", "title", "scope", "assertions")
ALLOWED_RULE_KEYS = {
    "id",
    "title",
    "description",
    "category",
    "scope",
    "severity",
    "assertions",
    "applies_when",
    "on_missing",
    "on_violation",
    "treat_empty_as_missing",
    "checklist_ref",
    "standard_ref",
    "recommendation",
    "message_pass",
    "message_fail",
    "message_manual",
    "message_not_applicable",
    "evidence_fields",
    "tags",
    "enabled",
}
ALLOWED_CONDITION_KEYS = {"field", "operator", "value", "description"}


class RuleSchemaError(ValueError):
    """Raised when a YAML rule definition is invalid."""


@dataclass(frozen=True)
class Condition:
    """A single ``field operator value`` assertion."""

    field_path: str
    operator: str
    value: Any = None
    description: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field_path,
            "operator": self.operator,
            "value": self.value,
            "description": self.description,
        }


@dataclass(frozen=True)
class RuleDefinition:
    """An immutable, validated rule."""

    id: str
    title: str
    scope: str
    assertions: List[Condition]
    description: str = ""
    category: str = "General"
    severity: Severity = Severity.MEDIUM
    applies_when: List[Condition] = field(default_factory=list)
    on_missing: Status = Status.MANUAL_REVIEW
    on_violation: Status = Status.FAIL
    treat_empty_as_missing: bool = False
    checklist_ref: Optional[str] = None
    standard_ref: Optional[str] = None
    recommendation: str = ""
    message_pass: str = ""
    message_fail: str = ""
    message_manual: str = ""
    message_not_applicable: str = ""
    evidence_fields: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    source_file: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "scope": self.scope,
            "severity": self.severity.value,
            "assertions": [a.as_dict() for a in self.assertions],
            "applies_when": [a.as_dict() for a in self.applies_when],
            "on_missing": self.on_missing.value,
            "on_violation": self.on_violation.value,
            "checklist_ref": self.checklist_ref,
            "standard_ref": self.standard_ref,
            "tags": self.tags,
            "enabled": self.enabled,
            "source_file": self.source_file,
        }


def _parse_condition(data: Any, *, rule_id: str, section: str) -> Condition:
    if not isinstance(data, dict):
        raise RuleSchemaError(f"[{rule_id}] each {section} entry must be a mapping, got {type(data).__name__}")
    unknown = set(data) - ALLOWED_CONDITION_KEYS
    if unknown:
        raise RuleSchemaError(f"[{rule_id}] unknown {section} keys: {', '.join(sorted(unknown))}")
    field_path = data.get("field")
    operator = data.get("operator")
    if not field_path or not isinstance(field_path, str):
        raise RuleSchemaError(f"[{rule_id}] {section} entry requires a non-empty 'field'")
    if not operator or not isinstance(operator, str):
        raise RuleSchemaError(f"[{rule_id}] {section} entry requires a non-empty 'operator'")
    if operator not in OPERATORS:
        raise RuleSchemaError(
            f"[{rule_id}] unknown operator '{operator}'. Available: {', '.join(sorted(OPERATORS))}"
        )
    if operator not in VALUELESS_OPERATORS and "value" not in data:
        raise RuleSchemaError(f"[{rule_id}] operator '{operator}' requires a 'value'")
    return Condition(
        field_path=field_path,
        operator=operator,
        value=data.get("value"),
        description=data.get("description"),
    )


def _parse_enum(value: Any, enum_cls, default, rule_id: str, key: str):
    if value is None:
        return default
    try:
        return enum_cls(str(value).upper())
    except ValueError as exc:
        allowed = ", ".join(e.value for e in enum_cls)
        raise RuleSchemaError(f"[{rule_id}] invalid {key} '{value}'. Allowed: {allowed}") from exc


def parse_rule(data: Any, *, source_file: Optional[str] = None) -> RuleDefinition:
    """Validate and convert one YAML mapping into a :class:`RuleDefinition`."""
    if not isinstance(data, dict):
        raise RuleSchemaError(f"Rule entries must be mappings, got {type(data).__name__}")

    rule_id = data.get("id")
    if not rule_id or not isinstance(rule_id, str):
        raise RuleSchemaError("Every rule requires a string 'id'")
    if not RULE_ID_PATTERN.match(rule_id):
        raise RuleSchemaError(
            f"Rule id '{rule_id}' must be upper-case and match {RULE_ID_PATTERN.pattern}"
        )

    unknown = set(data) - ALLOWED_RULE_KEYS
    if unknown:
        raise RuleSchemaError(f"[{rule_id}] unknown rule keys: {', '.join(sorted(unknown))}")

    for key in REQUIRED_RULE_KEYS:
        if key not in data:
            raise RuleSchemaError(f"[{rule_id}] missing required key '{key}'")

    scope = data["scope"]
    if scope not in SELECTORS:
        raise RuleSchemaError(
            f"[{rule_id}] unknown scope '{scope}'. Available: {', '.join(sorted(SELECTORS))}"
        )

    assertions_raw = data["assertions"]
    if not isinstance(assertions_raw, list) or not assertions_raw:
        raise RuleSchemaError(f"[{rule_id}] 'assertions' must be a non-empty list")
    assertions = [_parse_condition(a, rule_id=rule_id, section="assertion") for a in assertions_raw]

    applies_when_raw = data.get("applies_when") or []
    if not isinstance(applies_when_raw, list):
        raise RuleSchemaError(f"[{rule_id}] 'applies_when' must be a list")
    applies_when = [
        _parse_condition(a, rule_id=rule_id, section="applies_when") for a in applies_when_raw
    ]

    on_missing = _parse_enum(data.get("on_missing"), Status, Status.MANUAL_REVIEW, rule_id, "on_missing")
    if on_missing not in ALLOWED_MISSING_STATUSES:
        allowed = ", ".join(s.value for s in ALLOWED_MISSING_STATUSES)
        raise RuleSchemaError(f"[{rule_id}] 'on_missing' must be one of: {allowed}")

    on_violation = _parse_enum(
        data.get("on_violation"), Status, Status.FAIL, rule_id, "on_violation"
    )
    if on_violation not in ALLOWED_VIOLATION_STATUSES:
        allowed = ", ".join(s.value for s in ALLOWED_VIOLATION_STATUSES)
        raise RuleSchemaError(f"[{rule_id}] 'on_violation' must be one of: {allowed}")

    title = data["title"]
    if not isinstance(title, str) or not title.strip():
        raise RuleSchemaError(f"[{rule_id}] 'title' must be a non-empty string")

    tags = data.get("tags") or []
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise RuleSchemaError(f"[{rule_id}] 'tags' must be a list of strings")

    evidence_fields = data.get("evidence_fields") or []
    if not isinstance(evidence_fields, list) or any(not isinstance(t, str) for t in evidence_fields):
        raise RuleSchemaError(f"[{rule_id}] 'evidence_fields' must be a list of strings")

    return RuleDefinition(
        id=rule_id,
        title=title.strip(),
        scope=scope,
        assertions=assertions,
        description=data.get("description", "") or "",
        category=data.get("category", "General") or "General",
        severity=_parse_enum(data.get("severity"), Severity, Severity.MEDIUM, rule_id, "severity"),
        applies_when=applies_when,
        on_missing=on_missing,
        on_violation=on_violation,
        treat_empty_as_missing=bool(data.get("treat_empty_as_missing", False)),
        checklist_ref=data.get("checklist_ref"),
        standard_ref=data.get("standard_ref"),
        recommendation=data.get("recommendation", "") or "",
        message_pass=data.get("message_pass", "") or "",
        message_fail=data.get("message_fail", "") or "",
        message_manual=data.get("message_manual", "") or "",
        message_not_applicable=data.get("message_not_applicable", "") or "",
        evidence_fields=list(evidence_fields),
        tags=list(tags),
        enabled=bool(data.get("enabled", True)),
        source_file=source_file,
    )
