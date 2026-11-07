"""Tests for load-time semantic validation of rules."""

from __future__ import annotations

import pytest

from tableau_qc.rules.loader import RuleRepositoryError, load_rules
from tableau_qc.rules.schema import parse_rule
from tableau_qc.rules.validation import (
    SCOPE_MODELS,
    unmapped_rule_ids,
    validate_checklist_references,
    validate_condition_value,
    validate_field_path,
    validate_rule,
)

BASE = {
    "id": "CTL-TEST-001",
    "title": "Probe",
    "scope": "dashboard",
    "assertions": [{"field": "size.width", "operator": "equals", "value": 1600}],
}


def _rule(**overrides):
    data = dict(BASE)
    data.update(overrides)
    return parse_rule(data)


# -- field paths -----------------------------------------------------------
@pytest.mark.parametrize(
    "scope,path",
    [
        ("dashboard", "size.width"),
        ("dashboard", "view_count"),
        ("dashboard", "floating_zone_count"),
        ("workbook", "style.font_families"),
        ("workbook", "missing_metadata_elements"),
        ("dashboard_view_zone", "outer_padding.minimum"),
        ("mark_palette", "combines_red_and_green"),
        ("worksheet", "is_visible"),
        ("dashboard_image", "is_upper_left"),
    ],
)
def test_valid_field_paths_accepted(scope, path):
    assert validate_field_path(scope, path) is None


@pytest.mark.parametrize(
    "scope,path,fragment",
    [
        ("dashboard", "siz.widht", "'siz' does not exist"),
        ("dashboard", "size.depth", "'depth' does not exist"),
        ("workbook", "style.font_familys", "'font_familys' does not exist"),
        ("dashboard", "style.font_families", "'style' does not exist"),
    ],
)
def test_invalid_field_paths_rejected(scope, path, fragment):
    error = validate_field_path(scope, path)
    assert error is not None and fragment in error


def test_unknown_scope_is_not_validated():
    """An unregistered scope cannot be introspected; do not fail the load."""
    assert validate_field_path("galaxy", "anything.at.all") is None


def test_every_selector_scope_has_a_model():
    from tableau_qc.rules.selectors import SELECTORS

    assert set(SELECTORS) == set(SCOPE_MODELS)


# -- operator / value compatibility ---------------------------------------
@pytest.mark.parametrize(
    "operator,value,ok",
    [
        ("equals", 1600, True),
        ("between", [10, 15], True),
        ("between", 5, False),
        ("between", [10], False),
        ("between", ["a", "b"], False),
        ("in", ["a"], True),
        ("in", "a", False),
        ("all_in", ["Arial"], True),
        ("all_in", "Arial", False),
        ("greater_than_or_equal", 10, True),
        ("greater_than_or_equal", "ten", False),
        ("greater_than_or_equal", True, False),
        ("matches", "^Dash", True),
        ("matches", "[unclosed", False),
        ("matches", 5, False),
    ],
)
def test_operator_value_compatibility(operator, value, ok):
    condition = parse_rule(
        dict(BASE, assertions=[{"field": "name", "operator": operator, "value": value}])
    ).assertions[0]
    assert (validate_condition_value(condition) is None) is ok


def test_valueless_operator_rejects_a_value():
    condition = parse_rule(
        dict(BASE, assertions=[{"field": "name", "operator": "is_true", "value": 1}])
    ).assertions[0]
    assert "takes no 'value'" in validate_condition_value(condition)


# -- whole-rule validation -------------------------------------------------
def test_duplicate_assertion_field_reported():
    rule = _rule(
        assertions=[
            {"field": "view_count", "operator": "greater_than_or_equal", "value": 1},
            {"field": "view_count", "operator": "less_than_or_equal", "value": 6},
        ]
    )
    assert any("duplicate assertion" in p for p in validate_rule(rule))


def test_applies_when_paths_are_validated():
    rule = _rule(applies_when=[{"field": "nope", "operator": "is_true"}])
    assert any("'nope'" in p for p in validate_rule(rule))


def test_evidence_fields_are_validated():
    rule = _rule(evidence_fields=["size.nonsense"])
    problems = validate_rule(rule)
    assert any("evidence_fields" in p for p in problems)


def test_valid_rule_has_no_problems():
    assert validate_rule(_rule()) == []


# -- loader integration ----------------------------------------------------
def _write(tmp_path, body: str):
    path = tmp_path / "probe.yaml"
    path.write_text(f'version: "1.0.0"\nrules:\n{body}', encoding="utf-8")
    return path


def test_loader_rejects_a_field_typo(tmp_path):
    path = _write(
        tmp_path,
        """  - id: CTL-BAD-001
    title: typo
    scope: dashboard
    assertions:
      - field: siz.widht
        operator: equals
        value: 1600
""",
    )
    with pytest.raises(RuleRepositoryError, match="does not exist"):
        load_rules(path)


def test_loader_rejects_a_bad_operand(tmp_path):
    path = _write(
        tmp_path,
        """  - id: CTL-BAD-002
    title: operand
    scope: dashboard
    assertions:
      - field: size.width
        operator: between
        value: 5
""",
    )
    with pytest.raises(RuleRepositoryError, match="two bounds"):
        load_rules(path)


def test_shipped_rules_pass_validation(repository):
    from tableau_qc.rules.validation import validate_repository

    assert validate_repository(repository) == []


# -- checklist cross-references -------------------------------------------
def test_dangling_checklist_ref_detected():
    rule = _rule(checklist_ref="Agent Review!B99")
    problems = validate_checklist_references([rule], ["Agent Review!B10"])
    assert problems and "does not match" in problems[0]


def test_matching_checklist_ref_accepted():
    rule = _rule(checklist_ref="Agent Review!B10")
    assert validate_checklist_references([rule], ["Agent Review!B10"]) == []


def test_unmapped_rules_listed():
    assert unmapped_rule_ids([_rule()], ["CTL-OTHER-001"]) == ["CTL-TEST-001"]
    assert unmapped_rule_ids([_rule()], ["CTL-TEST-001"]) == []


def test_disabled_rules_are_not_reported_as_unmapped():
    assert unmapped_rule_ids([_rule(enabled=False)], []) == []
