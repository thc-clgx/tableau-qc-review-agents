"""Tests for JSON, Excel and PDF reporting."""

from __future__ import annotations

import json

import openpyxl
import pytest

from tableau_qc.agents.pre_review import PreTechnicalReviewAgent
from tableau_qc.domain.findings import Status
from tableau_qc.reporting.excel_report import ExcelReportWriter, write_excel_report
from tableau_qc.reporting.json_report import load_json_report, write_json_report
from tableau_qc.reporting.pdf_report import write_pdf_report
from tableau_qc.settings import excel_template_or_none


@pytest.fixture(scope="module")
def review_report(request):
    rules = request.config.rootpath / "config" / "rules"
    checklist = request.config.rootpath / "config" / "checklist" / "tech_review.yaml"
    sample = request.config.rootpath / "tests" / "fixtures" / "sample_workbook.xml"
    agent = PreTechnicalReviewAgent(rules_path=rules, checklist_path=checklist)
    return agent.run(sample)


def test_json_report_structure(review_report, tmp_path):
    path = write_json_report(review_report, tmp_path / "report.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["report_type"] == "PRE_TECHNICAL_REVIEW"
    assert data["schema_version"] == "1.0"
    assert data["workbook"]["source_sha256"]
    assert data["rule_repository"]["rule_count"] >= 20
    assert data["summary"]["overall_status"] == Status.FAIL.value
    assert data["findings"] and data["checklist"]


def test_json_findings_carry_evidence(review_report, tmp_path):
    data = json.loads(write_json_report(review_report, tmp_path / "r.json").read_text("utf-8"))
    for finding in data["findings"]:
        assert finding["evidence"]
        assert finding["key"].count("::") == 2
        for evidence in finding["evidence"]:
            assert "field" in evidence and "xpath" in evidence


def test_json_round_trip(review_report, tmp_path):
    path = write_json_report(review_report, tmp_path / "r.json")
    assert load_json_report(path)["findings"][0]["rule_id"].startswith("CTL-")


def test_load_json_report_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_json_report(tmp_path / "absent.json")


def test_excel_report_without_template(review_report, tmp_path):
    path = ExcelReportWriter(None).write_review(review_report, tmp_path / "report.xlsx")
    workbook = openpyxl.load_workbook(path)
    assert "QC Summary" in workbook.sheetnames
    assert "QC Findings" in workbook.sheetnames
    assert "Tech Review" in workbook.sheetnames
    sheet = workbook["Tech Review"]
    assert sheet.cell(row=1, column=1).value == "Item"
    assert sheet.max_row == len(review_report.checklist) + 1


def test_excel_report_populates_template(review_report, tmp_path):
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")
    path = ExcelReportWriter(template).write_review(review_report, tmp_path / "filled.xlsx")
    sheet = openpyxl.load_workbook(path)["Tech Review"]

    assert sheet.cell(row=3, column=2).value == "Question"  # template preserved
    assert sheet.cell(row=11, column=3).value == "N"  # no more than 6 views -> fail
    assert "at most 6 views" in sheet.cell(row=11, column=4).value
    assert sheet.cell(row=8, column=3).value == "N"  # Tableau Medium, not Arial


def test_excel_findings_sheet_lists_evidence(review_report, tmp_path):
    path = ExcelReportWriter(None).write_review(review_report, tmp_path / "report.xlsx")
    sheet = openpyxl.load_workbook(path)["QC Findings"]
    headers = [c.value for c in sheet[1]]
    assert "Rule ID" in headers and "Status" in headers
    assert sheet.max_row == len(review_report.findings) + 1
    evidence_column = headers.index("Evidence (field / expected / observed / XPath)") + 1
    assert "/workbook" in sheet.cell(row=2, column=evidence_column).value


def test_pdf_report_is_written(review_report, tmp_path):
    path = write_pdf_report(review_report, tmp_path / "report.pdf")
    assert path.is_file()
    assert path.read_bytes().startswith(b"%PDF")
    assert path.stat().st_size > 1000


def test_write_excel_report_dispatch(review_report, tmp_path):
    path = write_excel_report(review_report, tmp_path / "dispatch.xlsx")
    assert path.is_file()


# -- PDF column contract ---------------------------------------------------
def test_verification_label_vocabulary():
    """PDFs use one standard column with exactly four reportable values."""
    from tableau_qc.reporting.pdf_report import VERIFICATION_COLOURS, verification_label

    assert verification_label(Status.PASS) == "PASS"
    assert verification_label(Status.FAIL) == "FAIL"
    assert verification_label(Status.ADVISORY) == "ADVISORY"
    assert verification_label(Status.MANUAL_REVIEW) == "MANUAL"
    assert verification_label(Status.NOT_APPLICABLE) == "N/A"
    # A missing status is never silently treated as a pass.
    assert verification_label(None) == "MANUAL"
    assert set(VERIFICATION_COLOURS) == {"PASS", "FAIL", "ADVISORY", "MANUAL", "N/A"}


def test_pdf_has_no_before_after_columns(review_report, tmp_path):
    from pypdf import PdfReader

    path = write_pdf_report(review_report, tmp_path / "columns.pdf")
    text = " ".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    assert "Verification" in text
    assert "Evidence before" not in text
    assert "Evidence after" not in text
