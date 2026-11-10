"""Deterministic, data-driven QC rule engine.

The engine knows nothing about Tableau standards: it resolves field paths on
normalised objects, applies the operator named by the rule, and records
evidence for every decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..domain.findings import Evidence, Finding, Status
from ..domain.models import Workbook
from .loader import RuleRepository
from .operators import OperatorError, get_operator
from .schema import Condition, RuleDefinition
from .selectors import SELECTORS, Resolution, Target, resolve_field


@dataclass(frozen=True)
class ConditionOutcome:
    """Result of evaluating a single condition against a target."""

    condition: Condition
    status: Status
    evidence: Evidence


class RuleEngine:
    """Executes a :class:`RuleRepository` against a normalised workbook."""

    def __init__(
        self,
        repository: RuleRepository,
        *,
        selectors: Optional[Dict[str, Callable[[Workbook], List[Target]]]] = None,
    ) -> None:
        self.repository = repository
        self.selectors = selectors if selectors is not None else SELECTORS

    # -- public API --------------------------------------------------------
    def execute(self, workbook: Workbook) -> List[Finding]:
        """Evaluate every enabled rule and return findings in rule order."""
        findings: List[Finding] = []
        for rule in self.repository.enabled_rules:
            findings.extend(self.execute_rule(rule, workbook))
        return findings

    def execute_rule(self, rule: RuleDefinition, workbook: Workbook) -> List[Finding]:
        selector = self.selectors.get(rule.scope)
        if selector is None:
            return [
                self._finding(
                    rule,
                    Status.MANUAL_REVIEW,
                    target_type=rule.scope,
                    target_id="*",
                    target_name=None,
                    evidence=[
                        Evidence(
                            field_path="scope",
                            operator="exists",
                            expected=rule.scope,
                            observed=None,
                            observed_available=False,
                            note="No selector is registered for this scope",
                        )
                    ],
                    message=f"Scope '{rule.scope}' is not supported by this engine build",
                )
            ]

        targets = selector(workbook)
        if not targets:
            return [
                self._finding(
                    rule,
                    Status.NOT_APPLICABLE,
                    target_type=rule.scope,
                    target_id="*",
                    target_name=None,
                    evidence=[
                        Evidence(
                            field_path=rule.scope,
                            operator="exists",
                            expected="at least one object",
                            observed=0,
                            note="The workbook contains no objects in this scope",
                        )
                    ],
                    message=rule.message_not_applicable
                    or f"No {rule.scope} objects present in the workbook",
                )
            ]

        return [self._evaluate_target(rule, target) for target in targets]

    # -- evaluation --------------------------------------------------------
    def _evaluate_target(self, rule: RuleDefinition, target: Target) -> Finding:
        precondition_outcomes = [
            self._evaluate_condition(rule, target, condition) for condition in rule.applies_when
        ]
        if any(o.status is Status.MANUAL_REVIEW for o in precondition_outcomes):
            return self._finding(
                rule,
                Status.MANUAL_REVIEW,
                target_type=target.object_type,
                target_id=target.object_id,
                target_name=target.name,
                evidence=[o.evidence for o in precondition_outcomes],
                message=rule.message_manual
                or f"Rule applicability could not be determined for '{target.name}'",
            )
        if any(o.status is Status.FAIL for o in precondition_outcomes):
            return self._finding(
                rule,
                Status.NOT_APPLICABLE,
                target_type=target.object_type,
                target_id=target.object_id,
                target_name=target.name,
                evidence=[o.evidence for o in precondition_outcomes],
                message=rule.message_not_applicable
                or f"Rule does not apply to '{target.name}'",
            )

        outcomes = [
            self._evaluate_condition(rule, target, condition) for condition in rule.assertions
        ]
        evidence = [o.evidence for o in outcomes]
        evidence.extend(self._extra_evidence(rule, target))

        if any(o.status is Status.FAIL for o in outcomes):
            status = rule.on_violation
            message = rule.message_fail or self._default_message(rule, target, outcomes, failed=True)
        elif any(o.status is Status.MANUAL_REVIEW for o in outcomes):
            status = rule.on_missing
            message = rule.message_manual or (
                f"{rule.title}: required value is not declared in the workbook XML for "
                f"'{target.name}'; manual verification required"
            )
        else:
            status = Status.PASS
            message = rule.message_pass or self._default_message(rule, target, outcomes, failed=False)

        return self._finding(
            rule,
            status,
            target_type=target.object_type,
            target_id=target.object_id,
            target_name=target.name,
            evidence=evidence,
            message=self._format(message, rule, target, outcomes),
        )

    def _evaluate_condition(
        self, rule: RuleDefinition, target: Target, condition: Condition
    ) -> ConditionOutcome:
        resolution: Resolution = resolve_field(target.obj, condition.field_path)
        observed = resolution.value
        missing = not resolution.present
        if not missing and rule.treat_empty_as_missing and _is_empty(observed):
            missing = True

        if missing:
            return ConditionOutcome(
                condition=condition,
                status=Status.MANUAL_REVIEW,
                evidence=Evidence(
                    field_path=condition.field_path,
                    operator=condition.operator,
                    expected=condition.value,
                    observed=None,
                    observed_available=False,
                    source=resolution.source,
                    note=resolution.error or "Value is not declared in the workbook XML",
                ),
            )

        try:
            operator = get_operator(condition.operator)
            passed = bool(operator(observed, condition.value))
            note = condition.description
        except OperatorError as exc:
            return ConditionOutcome(
                condition=condition,
                status=Status.MANUAL_REVIEW,
                evidence=Evidence(
                    field_path=condition.field_path,
                    operator=condition.operator,
                    expected=condition.value,
                    observed=_serialisable(observed),
                    source=resolution.source,
                    note=f"Operator could not be applied: {exc}",
                ),
            )

        return ConditionOutcome(
            condition=condition,
            status=Status.PASS if passed else Status.FAIL,
            evidence=Evidence(
                field_path=condition.field_path,
                operator=condition.operator,
                expected=condition.value,
                observed=_serialisable(observed),
                source=resolution.source,
                note=note,
            ),
        )

    def _extra_evidence(self, rule: RuleDefinition, target: Target) -> List[Evidence]:
        """Context values requested by ``evidence_fields`` (never assertions)."""
        extra: List[Evidence] = []
        for field_path in rule.evidence_fields:
            resolution = resolve_field(target.obj, field_path)
            extra.append(
                Evidence(
                    field_path=field_path,
                    operator=None,
                    expected=None,
                    observed=_serialisable(resolution.value) if resolution.present else None,
                    observed_available=resolution.present,
                    source=resolution.source,
                    note="context",
                )
            )
        return extra

    # -- helpers -----------------------------------------------------------
    def _finding(
        self,
        rule: RuleDefinition,
        status: Status,
        *,
        target_type: str,
        target_id: str,
        target_name: Optional[str],
        evidence: Sequence[Evidence],
        message: str,
    ) -> Finding:
        return Finding(
            rule_id=rule.id,
            title=rule.title,
            status=status,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            target_location=_location_of(target_id),
            category=rule.category,
            severity=rule.severity,
            message=message,
            evidence=list(evidence),
            recommendation=rule.recommendation if status is not Status.PASS else None,
            checklist_ref=rule.checklist_ref,
            standard_ref=rule.standard_ref,
            automated=True,
            tags=list(rule.tags),
        )

    @staticmethod
    def _default_message(
        rule: RuleDefinition, target: Target, outcomes: Sequence[ConditionOutcome], *, failed: bool
    ) -> str:
        relevant = [o for o in outcomes if (o.status is Status.FAIL) == failed]
        details = "; ".join(o.evidence.summary() for o in relevant) or rule.title
        verb = "does not meet" if failed else "meets"
        return f"'{target.name}' {verb} the standard: {details}"

    @staticmethod
    def _format(
        message: str, rule: RuleDefinition, target: Target, outcomes: Sequence[ConditionOutcome]
    ) -> str:
        first = outcomes[0] if outcomes else None
        context = {
            "rule_id": rule.id,
            "title": rule.title,
            "target_name": target.name,
            "target_id": target.object_id,
            "observed": first.evidence.observed if first else None,
            "expected": first.evidence.expected if first else None,
            "field": first.evidence.field_path if first else None,
        }
        try:
            return message.format(**context)
        except (KeyError, IndexError, ValueError):
            return message


def _location_of(target_id: str) -> Optional[str]:
    """Dashboard that owns a target, taken from its composite id.

    Zone and image ids are formatted ``<dashboard>:zone-<n>``, so the dashboard
    name is the part before the final separator.
    """
    for marker in (":zone-", ":image-"):
        if marker in target_id:
            return target_id.split(marker)[0]
    return None


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, list, tuple, set, dict)):
        return len(value) == 0
    return False


def _serialisable(value: Any) -> Any:
    """Convert observed values into JSON-friendly primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_serialisable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialisable(v) for k, v in value.items()}
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return str(value)
