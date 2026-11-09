"""Tests for the YAML rule schema and repository loader."""

from __future__ import annotations

import pytest

from tableau_qc.domain.findings import Severity, Status
from tableau_qc.rules.loader import RuleRepositoryError, load_rule_directory, load_rules
from tableau_qc.rules.schema import RuleSchemaError, parse_rule

VALID_RULE = {
    "id": "CTL-TEST-001",
    "title": "Dashboard width must be 1600 px",
    "scope": "dashboard",
    "severity": "HIGH",
    "assertions": [{"field": "size.width", "operator": "equals", "value": 1600}],
}


def test_parse_valid_rule():
    rule = parse_rule(dict(VALID_RULE), source_file="memory.yaml")
    assert rule.id == "CTL-TEST-001"
    assert rule.severity is Severity.HIGH
    assert rule.on_missing is Status.MANUAL_REVIEW
    assert rule.enabled is True
    assert rule.source_file == "memory.yaml"
    assert rule.assertions[0].field_path == "size.width"


@pytest.mark.parametrize(
    "mutation,message",
    [
        ({"id": "lowercase-id"}, "upper-case"),
        ({"scope": "galaxy"}, "unknown scope"),
        ({"assertions": []}, "non-empty list"),
        ({"severity": "URGENT"}, "invalid severity"),
        ({"on_missing": "PASS"}, "on_missing"),
        ({"title": "  "}, "non-empty string"),
        ({"tags": "layout"}, "list of strings"),
    ],
)
def test_invalid_rules_are_rejected(mutation, message):
    data = dict(VALID_RULE)
    data.update(mutation)
    with pytest.raises(RuleSchemaError) as exc:
        parse_rule(data)
    assert message in str(exc.value)


def test_unknown_rule_key_rejected():
    data = dict(VALID_RULE)
    data["xpath"] = "/workbook/dashboards"
    with pytest.raises(RuleSchemaError, match="unknown rule keys"):
        parse_rule(data)


def test_unknown_operator_rejected():
    data = dict(VALID_RULE)
    data["assertions"] = [{"field": "size.width", "operator": "approximately", "value": 1600}]
    with pytest.raises(RuleSchemaError, match="unknown operator"):
        parse_rule(data)


def test_operator_requiring_value_rejected_without_one():
    data = dict(VALID_RULE)
    data["assertions"] = [{"field": "size.width", "operator": "equals"}]
    with pytest.raises(RuleSchemaError, match="requires a 'value'"):
        parse_rule(data)


def test_valueless_operator_allowed_without_value():
    data = dict(VALID_RULE)
    data["assertions"] = [{"field": "size.is_fixed", "operator": "is_true"}]
    assert parse_rule(data).assertions[0].value is None


def test_missing_required_key():
    data = dict(VALID_RULE)
    del data["scope"]
    with pytest.raises(RuleSchemaError, match="missing required key"):
        parse_rule(data)


# -- repository ------------------------------------------------------------
def test_repository_loads_shipped_rules(repository):
    assert len(repository) == 19
    assert {
        "CTL-LAYOUT-003",
        "CTL-LAYOUT-004",
        "CTL-TYPO-001",
        "CTL-COLOR-001",
        "CTL-STRUCT-001",
        "CTL-CONTENT-001",
        "CTL-CHART-001",
    }.issubset(set(repository.rule_ids))
    assert repository.checksum and len(repository.checksum) == 64


def test_repository_metadata(repository):
    metadata = repository.as_dict()
    assert metadata["rule_count"] == 19
    assert any(s.endswith("design_questions.yaml") for s in metadata["sources"])
    assert metadata["versions"]["design_questions.yaml"] == "3.0.0"


def test_repository_filtering(repository):
    assert repository.filtered(rule_ids=["CTL-TYPO-001"]).rule_ids == ["CTL-TYPO-001"]
    assert repository.filtered(categories=["Design"]).rule_ids == [
        "CTL-LAYOUT-003",
        "CTL-COLOR-002",
        "CTL-STRUCT-004",
        "CTL-LAYOUT-004",
        "CTL-TYPO-002",
        "CTL-TYPO-003",
        "CTL-CHART-001",
        "CTL-CHART-002",
        "CTL-STRUCT-001",
    ]
    assert "CTL-COLOR-001" in repository.filtered(categories=["Template"]).rule_ids
    assert repository.filtered(tags=["padding"]).rule_ids == ["CTL-LAYOUT-004"]


def test_rules_reference_the_style_guide(repository):
    for rule in repository:
        assert rule.standard_ref, f"{rule.id} must cite the source standard"
        assert rule.recommendation, f"{rule.id} must provide a recommendation"


def test_duplicate_rule_ids_rejected(tmp_path):
    body = """
version: "1.0.0"
rules:
  - id: CTL-DUP-001
    title: Duplicate
    scope: dashboard
    assertions:
      - field: size.width
        operator: equals
        value: 1600
"""
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(RuleRepositoryError, match="Duplicate rule id"):
        load_rule_directory(tmp_path)


def test_missing_rules_path(tmp_path):
    with pytest.raises(RuleRepositoryError):
        load_rules(tmp_path / "nope.yaml")


def test_empty_directory_rejected(tmp_path):
    with pytest.raises(RuleRepositoryError, match="No rule files"):
        load_rule_directory(tmp_path)


def test_invalid_yaml_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("rules: [: :", encoding="utf-8")
    with pytest.raises(RuleRepositoryError, match="Invalid YAML"):
        load_rules(bad)


def test_rules_file_without_rules_key(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: '1.0.0'\n", encoding="utf-8")
    with pytest.raises(RuleRepositoryError, match="'rules' must be"):
        load_rules(bad)
