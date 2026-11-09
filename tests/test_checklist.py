"""Tests for checklist loading and population."""

from __future__ import annotations

import pytest

from conftest import parse_fixture
from tableau_qc.checklist import (
    ChecklistError,
    build_checklist_results,
    checklist_metadata,
    load_checklist,
)
from tableau_qc.domain.findings import Status
from tableau_qc.rules.engine import RuleEngine


def _results(definition, repository, path):
    findings = RuleEngine(repository).execute(parse_fixture(path))
    return {r.item_id: r for r in build_checklist_results(definition, findings, evaluated_rule_ids=repository.rule_ids)}


def test_checklist_loads_every_question(checklist_definition):
    """The agent owns the Agent Review tab only."""
    assert len(checklist_definition.items) == 19
    assert checklist_definition.sheets() == ["Agent Review"]
    assert checklist_definition.answer_column == "C"
    assert checklist_definition.comment_column == "D"


def test_checklist_rule_references_exist(checklist_definition, repository):
    for rule_id in checklist_definition.rule_ids:
        assert repository.by_id(rule_id) is not None, f"{rule_id} referenced but not defined"


def test_checklist_item_rows(checklist_definition):
    item = next(i for i in checklist_definition.items if i.item_id == "AR-10")
    assert item.cell == "B10"
    assert item.row == 10
    assert item.rule_ids == ["CTL-LAYOUT-003"]


def test_compliant_workbook_answers_yes(checklist_definition, repository, compliant_xml_path):
    results = _results(checklist_definition, repository, compliant_xml_path)
    assert results["AR-10"].status is Status.PASS
    assert results["AR-10"].pass_flag == "Y"
    assert results["AR-13"].pass_flag == "Y"


def test_non_compliant_workbook_answers_no(checklist_definition, repository, non_compliant_xml_path):
    results = _results(checklist_definition, repository, non_compliant_xml_path)
    assert results["AR-10"].status is Status.FAIL
    assert results["AR-10"].pass_flag == "N"
    assert "at most 6 views" in results["AR-10"].recommendation
    assert "CTL-LAYOUT-003" in results["AR-10"].evidence_summary


def test_every_answer_is_binary(checklist_definition, repository, non_compliant_xml_path):
    """The Pass column carries Y or N only - never Review or Manual."""
    for results in (
        _results(checklist_definition, repository, non_compliant_xml_path),
    ):
        assert {r.pass_flag for r in results.values()} <= {"Y", "N"}
        assert len(results) == 19


def test_not_applicable_answers_yes(checklist_definition, repository, compliant_xml_path):
    """Nothing to violate is compliance, so N/A reports Y."""
    from tableau_qc.domain.findings import ChecklistResult

    result = ChecklistResult(
        item_id="AR-11",
        section=None,
        question="q",
        status=Status.NOT_APPLICABLE,
    )
    assert result.pass_flag == "Y"


def test_manual_review_answers_no():
    """Undemonstrated compliance answers N, with the reason in the comment."""
    from tableau_qc.domain.findings import ChecklistResult

    result = ChecklistResult(
        item_id="AR-07", section=None, question="q", status=Status.MANUAL_REVIEW
    )
    assert result.pass_flag == "N"


def test_rules_not_evaluated_fall_back_to_manual(checklist_definition, repository, compliant_xml_path):  # noqa: E501
    subset = repository.filtered(rule_ids=["CTL-TYPO-001"])
    findings = RuleEngine(subset).execute(parse_fixture(compliant_xml_path))
    results = {
        r.item_id: r
        for r in build_checklist_results(
            checklist_definition, findings, evaluated_rule_ids=subset.rule_ids
        )
    }
    assert results["AR-10"].status is Status.MANUAL_REVIEW
    assert "not evaluated" in results["AR-10"].recommendation


def test_metadata(checklist_definition):
    metadata = checklist_metadata(checklist_definition)
    assert metadata["item_count"] == 19
    assert metadata["automated_item_count"] == 19


def test_invalid_checklist_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("sheets: []\n", encoding="utf-8")
    with pytest.raises(ChecklistError):
        load_checklist(bad)


def test_duplicate_checklist_ids_rejected(tmp_path):
    bad = tmp_path / "dup.yaml"
    bad.write_text(
        """
sheets:
  - sheet: Tech Review
    items:
      - id: TR-01
        cell: B4
        question: Q1
      - id: TR-01
        cell: B5
        question: Q2
""",
        encoding="utf-8",
    )
    with pytest.raises(ChecklistError, match="duplicate"):
        load_checklist(bad)


def test_missing_checklist_file(tmp_path):
    with pytest.raises(ChecklistError):
        load_checklist(tmp_path / "absent.yaml")
