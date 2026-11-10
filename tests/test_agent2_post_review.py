"""Integration tests for Agent 2 (post-technical review verification)."""

from __future__ import annotations

import openpyxl
import pytest

from tableau_qc.agents.post_review import (
    PostTechnicalReviewAgent,
    VerificationInputError,
    load_sme_feedback,
)
from tableau_qc.agents.pre_review import PreTechnicalReviewAgent
from tableau_qc.domain.comparison import VerificationStatus
from tableau_qc.domain.findings import Status
from tableau_qc.reporting.json_report import write_json_report


@pytest.fixture()
def agent(rules_dir, checklist_path):
    return PostTechnicalReviewAgent(rules_path=rules_dir, checklist_path=checklist_path)


def _verification(comparisons, rule_id):
    return {c.verification for c in comparisons if c.rule_id == rule_id}


def test_resolved_when_defect_is_fixed(agent, rule_fixtures_dir):
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-003_fail.xml",
    )
    assert _verification(report.comparisons, "CTL-LAYOUT-003") == {VerificationStatus.RESOLVED}
    resolved = next(c for c in report.comparisons if c.rule_id == "CTL-LAYOUT-003")
    assert resolved.baseline_status is Status.FAIL
    assert resolved.revised_status is Status.PASS
    assert resolved.baseline_evidence and resolved.revised_evidence
    assert resolved.baseline_evidence[0]["observed"] == 7   # over the limit
    assert resolved.revised_evidence[0]["observed"] == 3    # within the limit


def test_unresolved_when_defect_remains(agent, rule_fixtures_dir):
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-003_fail.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-003_fail.xml",
    )
    assert _verification(report.comparisons, "CTL-LAYOUT-003") == {VerificationStatus.UNRESOLVED}
    assert report.summary["sign_off_ready"] is False


def test_partially_resolved_when_one_assertion_is_fixed(agent, rule_fixtures_dir):
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-004_partial.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-004_fail.xml",
    )
    comparison = next(c for c in report.comparisons if c.rule_id == "CTL-LAYOUT-004")
    assert comparison.verification is VerificationStatus.PARTIALLY_RESOLVED
    assert "outer_padding.minimum" in comparison.note
    assert "inner_padding.minimum" in comparison.note


def test_cannot_verify_when_the_object_is_removed(agent, rule_fixtures_dir):
    """A zone deleted during remediation cannot be verified as fixed."""
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-004_fail.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-004_added_zone.xml",
    )
    removed = [
        c
        for c in report.comparisons
        if c.verification is VerificationStatus.CANNOT_VERIFY and "no longer exists" in c.note
    ]
    assert removed


def test_new_regression_detected(agent, rule_fixtures_dir):
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-003_fail.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml",
    )
    assert _verification(report.comparisons, "CTL-LAYOUT-003") == {
        VerificationStatus.NEW_FAILURE
    }
    assert report.summary["new_failure_count"] >= 1
    assert report.summary["sign_off_ready"] is False


def test_new_object_failing_is_a_regression(agent, rule_fixtures_dir):
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-004_added_zone.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-004_pass.xml",
    )
    new_zone = next(c for c in report.comparisons if c.target_id == "Dashboard A:zone-11")
    assert new_zone.verification is VerificationStatus.NEW_FAILURE
    assert new_zone.baseline_status is None
    assert "new in the revised workbook" in new_zone.note


def test_regression_on_existing_object_is_detected(agent, rule_fixtures_dir):
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-004_fail.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-004_pass.xml",
    )
    comparison = next(c for c in report.comparisons if c.rule_id == "CTL-LAYOUT-004")
    assert comparison.verification is VerificationStatus.NEW_FAILURE
    assert comparison.baseline_status is Status.PASS
    assert "passed in the baseline" in comparison.note


def test_removed_object_cannot_be_verified(agent, rule_fixtures_dir, non_compliant_xml_path):
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-004_pass.xml",
        baseline_xml=non_compliant_xml_path,
    )
    removed = [
        c
        for c in report.comparisons
        if c.verification is VerificationStatus.CANNOT_VERIFY and "no longer exists" in c.note
    ]
    assert removed
    assert all(c.revised_status is None for c in removed)


def test_unchanged_pass_is_reported(rules_dir, checklist_path, rule_fixtures_dir):
    # Scoped to the layout rules: the minimal fixture has no logo or metadata,
    # which the content/structure rules would correctly flag.
    agent = PostTechnicalReviewAgent(
        rules_path=rules_dir,
        checklist_path=checklist_path,
        rule_ids=["CTL-LAYOUT-003", "CTL-TYPO-001"],
    )
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml",
    )
    assert _verification(report.comparisons, "CTL-TYPO-001") == {
        VerificationStatus.UNCHANGED_PASS
    }
    assert report.summary["sign_off_ready"] is True


def test_previous_audit_json_is_accepted(
    agent, rules_dir, checklist_path, rule_fixtures_dir, tmp_path
):
    pre_agent = PreTechnicalReviewAgent(rules_path=rules_dir, checklist_path=checklist_path)
    baseline_report = pre_agent.run(rule_fixtures_dir / "CTL-LAYOUT-003_fail.xml")
    audit_path = write_json_report(baseline_report, tmp_path / "audit.json")

    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml", previous_audit_json=audit_path
    )
    assert report.baseline["source"] == "previous_audit_json"
    assert report.baseline["finding_count"] == len(baseline_report.findings)
    assert _verification(report.comparisons, "CTL-LAYOUT-003") == {VerificationStatus.RESOLVED}


def test_requires_a_baseline(agent, rule_fixtures_dir):
    with pytest.raises(VerificationInputError):
        agent.run(rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml")


def test_sme_feedback_is_included(agent, rule_fixtures_dir, fixtures_dir):
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-004_pass.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-004_fail.xml",
        sme_feedback_path=fixtures_dir / "sme_feedback.yaml",
    )
    assert len(report.sme_feedback) == 2
    sme_comparisons = [c for c in report.comparisons if c.key.startswith("SME-")]
    assert len(sme_comparisons) == 2
    assert sme_comparisons[0].verification is VerificationStatus.RESOLVED
    assert sme_comparisons[1].verification is VerificationStatus.CANNOT_VERIFY


def test_sme_feedback_loader_accepts_plain_strings(tmp_path):
    path = tmp_path / "feedback.yaml"
    path.write_text("- Check the logo placement\n", encoding="utf-8")
    items = load_sme_feedback(path)
    assert items[0].comment == "Check the logo placement"
    assert items[0].status is Status.MANUAL_REVIEW


def test_sme_feedback_loader_rejects_bad_input(tmp_path):
    path = tmp_path / "feedback.yaml"
    path.write_text("feedback:\n  - author: X\n", encoding="utf-8")
    with pytest.raises(VerificationInputError):
        load_sme_feedback(path)


def test_checklist_reflects_revised_workbook(agent, rule_fixtures_dir):
    report = agent.run(
        rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-003_fail.xml",
    )
    answers = {r.item_id: r.pass_flag for r in report.checklist}
    assert answers["AR-10"] == "Y"
    assert set(answers.values()) <= {"Y", "N"}


def test_run_and_export_writes_reports(agent, rule_fixtures_dir, tmp_path):
    report, artifacts = agent.run_and_export(
        rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml",
        baseline_xml=rule_fixtures_dir / "CTL-LAYOUT-003_fail.xml",
        output_dir=tmp_path,
        basename="verification",
        write_pdf=True,
    )
    assert artifacts.json_path.is_file()
    assert artifacts.pdf_path.read_bytes().startswith(b"%PDF")

    workbook = openpyxl.load_workbook(artifacts.excel_path)
    assert "Agent Review" in workbook.sheetnames
    sheet = workbook["Agent Review"]
    answers = {
        sheet.cell(row=r, column=3).value
        for r in range(4, 26)
        if sheet.cell(row=r, column=3).value is not None
    }
    assert answers <= {"Y", "N"}


def test_verification_is_deterministic(agent, rule_fixtures_dir):
    kwargs = {"baseline_xml": rule_fixtures_dir / "CTL-LAYOUT-003_fail.xml"}
    first = agent.run(rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml", **kwargs)
    second = agent.run(rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml", **kwargs)
    assert [(c.key, c.verification) for c in first.comparisons] == [
        (c.key, c.verification) for c in second.comparisons
    ]


def test_sample_workbook_against_compliant_revision(agent, sample_xml_path, compliant_xml_path):
    report = agent.run(compliant_xml_path, baseline_xml=sample_xml_path)
    verifications = {c.verification for c in report.comparisons}
    assert VerificationStatus.CANNOT_VERIFY in verifications
    assert report.revised["name"] == "CompliantWorkbook"
    assert report.baseline["source"] == "baseline_xml"


def test_realistic_revision_of_the_sample_workbook(agent, fixtures_dir, sample_xml_path):
    """The revised sample fixes size, padding and fonts but keeps 9 views."""
    report = agent.run(
        fixtures_dir / "sample_workbook_revised.xml", baseline_xml=sample_xml_path
    )
    by_rule = {}
    for comparison in report.comparisons:
        by_rule.setdefault(comparison.rule_id, set()).add(comparison.verification)

    assert by_rule["CTL-LAYOUT-003"] == {VerificationStatus.UNRESOLVED}
    # The revision added workbook-level Arial but left 'Tableau Medium' in the
    # title <run> elements, so the font rule correctly still reports a defect.
    assert by_rule["CTL-TYPO-001"] == {VerificationStatus.UNRESOLVED}
    # Button zones keep a zero side-margin override, so padding is only partly fixed.
    assert by_rule["CTL-LAYOUT-004"] == {
        VerificationStatus.RESOLVED,
        VerificationStatus.UNRESOLVED,
    }
    assert VerificationStatus.NEW_FAILURE not in {
        v for values in by_rule.values() for v in values
    }
    assert report.summary["sign_off_ready"] is False
