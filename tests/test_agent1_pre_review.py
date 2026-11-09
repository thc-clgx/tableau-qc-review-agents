"""Integration tests for Agent 1 (pre-technical review)."""

from __future__ import annotations

import json

import openpyxl
import pytest

from tableau_qc.agents.pre_review import PreTechnicalReviewAgent
from tableau_qc.domain.findings import Status


@pytest.fixture()
def agent(rules_dir, checklist_path):
    return PreTechnicalReviewAgent(rules_path=rules_dir, checklist_path=checklist_path)


def test_run_on_sample_workbook(agent, sample_xml_path):
    report = agent.run(sample_xml_path)
    summary = report.summary

    assert report.report_type == "PRE_TECHNICAL_REVIEW"
    assert report.workbook["name"] == "TestAIBIDashboards"
    assert summary["rules_evaluated"] == 19
    assert summary["overall_status"] == Status.FAIL.value
    assert summary["by_status"][Status.FAIL.value] > 0
    assert summary["by_status"][Status.FAIL.value] >= 1


def test_findings_cover_the_known_defects(agent, sample_xml_path):
    report = agent.run(sample_xml_path)
    statuses = {}
    for finding in report.findings:
        statuses.setdefault(finding.rule_id, set()).add(finding.status)

    assert Status.FAIL in statuses["CTL-LAYOUT-003"]
    assert Status.FAIL in statuses["CTL-LAYOUT-004"]
    assert statuses["CTL-TYPO-001"] == {Status.FAIL}  # declares Tableau Medium


def test_every_finding_has_evidence_and_provenance(agent, sample_xml_path):
    report = agent.run(sample_xml_path)
    for finding in report.findings:
        assert finding.automated is True
        assert finding.evidence
        assert finding.message
        if finding.status in (Status.PASS, Status.FAIL):
            assertion_evidence = [e for e in finding.evidence if e.note != "context"]
            assert assertion_evidence
            assert all(e.source is not None for e in assertion_evidence)


def test_compliant_workbook_passes(agent, compliant_xml_path):
    report = agent.run(compliant_xml_path)
    assert report.summary["overall_status"] == Status.PASS.value
    assert report.summary["by_status"][Status.FAIL.value] == 0
    assert all(f.recommendation is None for f in report.findings if f.status is Status.PASS)


def test_checklist_is_populated(agent, sample_xml_path):
    report = agent.run(sample_xml_path)
    assert len(report.checklist) == 19
    assert {r.sheet for r in report.checklist} == {"Agent Review"}
    answered = {r.item_id: r.pass_flag for r in report.checklist}
    assert answered["AR-10"] == "N"      # 9 views
    assert set(answered.values()) <= {"Y", "N"}


def test_rule_subset_execution(rules_dir, checklist_path, sample_xml_path):
    agent = PreTechnicalReviewAgent(
        rules_path=rules_dir, checklist_path=checklist_path, rule_ids=["CTL-LAYOUT-003"]
    )
    report = agent.run(sample_xml_path)
    assert {f.rule_id for f in report.findings} == {"CTL-LAYOUT-003"}
    assert report.rule_repository["rule_count"] == 1


def test_category_filter(rules_dir, checklist_path, sample_xml_path):
    agent = PreTechnicalReviewAgent(
        rules_path=rules_dir, checklist_path=checklist_path, categories=["Template"]
    )
    assert {f.rule_id for f in agent.run(sample_xml_path).findings} == {
        "CTL-STRUCT-002",
        "CTL-CONTENT-001",
        "CTL-TYPO-001",
        "CTL-COLOR-001",
    }


def test_run_without_checklist(rules_dir, sample_xml_path):
    agent = PreTechnicalReviewAgent(rules_path=rules_dir, checklist_path=None)
    report = agent.run(sample_xml_path)
    assert report.checklist == []
    assert report.findings


def test_run_and_export_writes_all_artifacts(agent, sample_xml_path, tmp_path):
    report, artifacts = agent.run_and_export(
        sample_xml_path, output_dir=tmp_path, basename="review", write_pdf=True
    )
    assert artifacts.json_path.is_file()
    assert artifacts.excel_path.is_file()
    assert artifacts.pdf_path.is_file()

    data = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    assert data["summary"]["overall_status"] == report.summary["overall_status"]

    workbook = openpyxl.load_workbook(artifacts.excel_path)
    assert "Agent Review" in workbook.sheetnames


def test_results_are_deterministic(agent, sample_xml_path):
    first = agent.run(sample_xml_path)
    second = agent.run(sample_xml_path)
    assert [(f.key, f.status, f.message) for f in first.findings] == [
        (f.key, f.status, f.message) for f in second.findings
    ]


def test_parse_step_is_reusable(agent, sample_xml_path):
    workbook = agent.parse(sample_xml_path)
    assert workbook.dashboard_count == 1
    assert agent.evaluate(workbook)


def test_malformed_input_raises(agent, security_fixtures_dir):
    from tableau_qc.xmlio.loader import XMLLoadError

    with pytest.raises(XMLLoadError):
        agent.run(security_fixtures_dir / "malformed.xml")


def test_xxe_input_is_rejected(agent, security_fixtures_dir):
    from tableau_qc.xmlio.loader import XMLSecurityError

    with pytest.raises(XMLSecurityError):
        agent.run(security_fixtures_dir / "xxe.xml")
