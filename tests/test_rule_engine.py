"""Tests for the generic rule engine (scope selection, statuses, evidence)."""

from __future__ import annotations

import pytest

from conftest import parse_fixture
from tableau_qc.domain.findings import Status
from tableau_qc.rules.engine import RuleEngine
from tableau_qc.rules.loader import RuleRepository
from tableau_qc.rules.schema import parse_rule
from tableau_qc.rules.selectors import SELECTORS, resolve_field


def engine_for(rule_dict) -> RuleEngine:
    return RuleEngine(RuleRepository(rules=[parse_rule(rule_dict)]))


BASE = {
    "id": "CTL-TEST-001",
    "title": "Test rule",
    "scope": "dashboard",
    "assertions": [{"field": "size.width", "operator": "equals", "value": 1600}],
}


def test_pass_includes_evidence(compliant_xml_path):
    workbook = parse_fixture(compliant_xml_path)
    findings = engine_for(dict(BASE)).execute(workbook)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.status is Status.PASS
    assert finding.evidence
    assert finding.evidence[0].observed == 1600
    assert finding.evidence[0].source.xpath.endswith("/size[1]")


def test_fail_includes_expected_and_observed(non_compliant_xml_path):
    workbook = parse_fixture(non_compliant_xml_path)
    finding = engine_for(dict(BASE)).execute(workbook)[0]
    assert finding.status is Status.FAIL
    assert finding.evidence[0].expected == 1600
    assert finding.evidence[0].observed == 1000
    assert finding.recommendation is not None


def test_unavailable_value_returns_manual_review(compliant_xml_path):
    rule = dict(BASE)
    rule["assertions"] = [{"field": "size.sizing_mode", "operator": "equals", "value": "fixed"}]
    workbook = parse_fixture(compliant_xml_path)
    finding = engine_for(rule).execute(workbook)[0]
    assert finding.status is Status.MANUAL_REVIEW
    assert finding.evidence[0].observed_available is False


def test_on_missing_can_be_overridden(compliant_xml_path):
    rule = dict(BASE)
    rule["assertions"] = [{"field": "size.sizing_mode", "operator": "equals", "value": "fixed"}]
    rule["on_missing"] = "NOT_APPLICABLE"
    workbook = parse_fixture(compliant_xml_path)
    assert engine_for(rule).execute(workbook)[0].status is Status.NOT_APPLICABLE


def test_unknown_field_is_manual_review(compliant_xml_path):
    rule = dict(BASE)
    rule["assertions"] = [{"field": "size.diagonal", "operator": "equals", "value": 1}]
    workbook = parse_fixture(compliant_xml_path)
    finding = engine_for(rule).execute(workbook)[0]
    assert finding.status is Status.MANUAL_REVIEW
    assert "no attribute" in finding.evidence[0].note


def test_applies_when_false_yields_not_applicable(compliant_xml_path):
    rule = dict(BASE)
    rule["applies_when"] = [{"field": "name", "operator": "equals", "value": "Other dashboard"}]
    workbook = parse_fixture(compliant_xml_path)
    assert engine_for(rule).execute(workbook)[0].status is Status.NOT_APPLICABLE


def test_applies_when_true_evaluates_assertions(compliant_xml_path):
    rule = dict(BASE)
    rule["applies_when"] = [{"field": "name", "operator": "equals", "value": "Dashboard A"}]
    workbook = parse_fixture(compliant_xml_path)
    assert engine_for(rule).execute(workbook)[0].status is Status.PASS


def test_empty_scope_yields_single_not_applicable_finding():
    from tableau_qc.parsers.workbook_parser import parse_workbook_bytes

    workbook = parse_workbook_bytes(b"<workbook version='18.1' />")
    finding = engine_for(dict(BASE)).execute(workbook)[0]
    assert finding.status is Status.NOT_APPLICABLE
    assert finding.target_id == "*"
    assert finding.evidence


def test_treat_empty_as_missing(compliant_xml_path):
    rule = dict(BASE)
    rule["scope"] = "workbook"
    rule["assertions"] = [{"field": "custom_palettes", "operator": "all_in", "value": ["X"]}]
    rule["treat_empty_as_missing"] = True
    workbook = parse_fixture(compliant_xml_path)
    assert engine_for(rule).execute(workbook)[0].status is Status.MANUAL_REVIEW


def test_multi_target_scope_produces_one_finding_per_target(non_compliant_xml_path):
    rule = dict(BASE)
    rule["scope"] = "dashboard_view_zone"
    rule["assertions"] = [
        {"field": "outer_padding.minimum", "operator": "greater_than_or_equal", "value": 10}
    ]
    workbook = parse_fixture(non_compliant_xml_path)
    findings = engine_for(rule).execute(workbook)
    assert len(findings) == 7
    assert {f.status for f in findings} == {Status.FAIL}
    assert len({f.target_id for f in findings}) == 7


def test_evidence_fields_are_context_only(compliant_xml_path):
    rule = dict(BASE)
    rule["evidence_fields"] = ["size.is_fixed"]
    workbook = parse_fixture(compliant_xml_path)
    finding = engine_for(rule).execute(workbook)[0]
    context = [e for e in finding.evidence if e.note == "context"]
    assert len(context) == 1
    assert context[0].observed is True


def test_execution_is_deterministic(sample_workbook, repository):
    engine = RuleEngine(repository)
    first = [(f.key, f.status) for f in engine.execute(sample_workbook)]
    second = [(f.key, f.status) for f in engine.execute(sample_workbook)]
    assert first == second


def test_every_automated_finding_has_evidence(sample_workbook, repository):
    for finding in RuleEngine(repository).execute(sample_workbook):
        assert finding.evidence, f"{finding.rule_id} produced no evidence"


def test_unknown_scope_is_reported_as_manual_review(compliant_xml_path):
    rule = parse_rule(dict(BASE))
    engine = RuleEngine(RuleRepository(rules=[rule]), selectors={})
    finding = engine.execute(parse_fixture(compliant_xml_path))[0]
    assert finding.status is Status.MANUAL_REVIEW
    assert "not supported" in finding.message


def test_finding_keys_are_stable_and_unique(sample_workbook, repository):
    keys = [f.key for f in RuleEngine(repository).execute(sample_workbook)]
    assert len(keys) == len(set(keys))
    assert all("::" in key for key in keys)


# -- field resolution -------------------------------------------------------
def test_resolve_field_returns_source(compliant_xml_path):
    workbook = parse_fixture(compliant_xml_path)
    resolution = resolve_field(workbook.dashboards[0], "size.width")
    assert resolution.present is True
    assert resolution.value == 1600
    assert resolution.source.xpath.endswith("/size[1]")


def test_resolve_field_missing_attribute(compliant_xml_path):
    workbook = parse_fixture(compliant_xml_path)
    resolution = resolve_field(workbook.dashboards[0], "size.depth")
    assert resolution.present is False
    assert "no attribute" in resolution.error


@pytest.mark.parametrize("scope", sorted(SELECTORS))
def test_every_selector_runs(scope, sample_workbook):
    assert isinstance(SELECTORS[scope](sample_workbook), list)
