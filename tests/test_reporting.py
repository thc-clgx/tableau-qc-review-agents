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
    checklist = request.config.rootpath / "config" / "checklist"
    sample = request.config.rootpath / "tests" / "fixtures" / "sample_workbook.xml"
    agent = PreTechnicalReviewAgent(rules_path=rules, checklist_path=checklist)
    return agent.run(sample)


def test_json_report_structure(review_report, tmp_path):
    path = write_json_report(review_report, tmp_path / "report.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["report_type"] == "PRE_TECHNICAL_REVIEW"
    assert data["schema_version"] == "1.0"
    assert data["workbook"]["source_sha256"]
    assert data["rule_repository"]["rule_count"] == 19
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


def test_excel_report_fills_only_the_agent_tab(review_report, tmp_path):
    """Without a template only the agent's tab is created."""
    path = ExcelReportWriter(None).write_review(review_report, tmp_path / "report.xlsx")
    workbook = openpyxl.load_workbook(path)
    assert workbook.sheetnames == ["Agent Review"]


def test_template_tabs_are_all_preserved(review_report, tmp_path):
    """Every template tab survives; the agent only writes into its own."""
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")
    path = ExcelReportWriter(template).write_review(review_report, tmp_path / "tabs.xlsx")

    written = openpyxl.load_workbook(path)
    original = openpyxl.load_workbook(template)
    assert written.sheetnames == original.sheetnames


def test_human_tabs_are_left_untouched(review_report, tmp_path):
    """Peer Review and Tech Review are the human portions of the checklist."""
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")
    path = ExcelReportWriter(template).write_review(review_report, tmp_path / "human.xlsx")

    written = openpyxl.load_workbook(path)
    original = openpyxl.load_workbook(template)
    for name in written.sheetnames:
        if name == "Agent Review":
            continue
        out_sheet, tpl_sheet = written[name], original[name]
        rows = max(out_sheet.max_row, tpl_sheet.max_row)
        for row in range(1, rows + 1):
            for column in range(1, 5):
                assert out_sheet.cell(row, column).value == tpl_sheet.cell(row, column).value, (
                    f"{name}!{row},{column} was modified"
                )


def test_workbook_opens_on_the_agent_tab(review_report, tmp_path):
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")
    path = ExcelReportWriter(template).write_review(review_report, tmp_path / "active.xlsx")

    workbook = openpyxl.load_workbook(path)
    expected = workbook.sheetnames.index("Agent Review")
    assert workbook.views[0].activeTab == expected


def test_excel_report_populates_template(review_report, tmp_path):
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")
    path = ExcelReportWriter(template).write_review(review_report, tmp_path / "filled.xlsx")
    workbook = openpyxl.load_workbook(path)

    assert "Agent Review" in workbook.sheetnames
    sheet = workbook["Agent Review"]
    assert sheet.cell(row=3, column=2).value == "Question"  # template preserved
    assert sheet.cell(row=10, column=3).value == "N"  # more than 6 views
    assert "at most 6 views" in sheet.cell(row=10, column=4).value


def test_every_answered_cell_is_binary(review_report, tmp_path):
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")
    path = ExcelReportWriter(template).write_review(review_report, tmp_path / "binary.xlsx")
    sheet = openpyxl.load_workbook(path)["Agent Review"]
    answers = {
        sheet.cell(row=r, column=3).value
        for r in range(4, 26)
        if sheet.cell(row=r, column=3).value is not None
    }
    assert answers <= {"Y", "N"}, f"non-binary answers found: {answers}"


def test_recommendations_are_written_for_failures(review_report, tmp_path):
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")
    path = ExcelReportWriter(template).write_review(review_report, tmp_path / "report.xlsx")
    sheet = openpyxl.load_workbook(path)["Agent Review"]
    for result in review_report.checklist:
        row = int("".join(c for c in result.cell if c.isdigit()))
        if sheet.cell(row=row, column=3).value == "N":
            assert sheet.cell(row=row, column=4).value, f"{result.item_id} needs advice"


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
    """The PDF uses one binary column: Y or N."""
    from tableau_qc.reporting.pdf_report import VERIFICATION_COLOURS, verification_label

    assert verification_label(Status.PASS) == "Y"
    assert verification_label(Status.NOT_APPLICABLE) == "Y"
    assert verification_label(Status.FAIL) == "N"
    assert verification_label(Status.MANUAL_REVIEW) == "N"
    # A missing status is never silently treated as a pass.
    assert verification_label(None) == "N"
    assert set(VERIFICATION_COLOURS) == {"Y", "N"}


def test_pdf_contains_only_the_checklist(review_report, tmp_path):
    """The PDF carries the Agent Review checklist and nothing else."""
    from pypdf import PdfReader

    path = write_pdf_report(review_report, tmp_path / "columns.pdf")
    text = " ".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)

    assert "Agent Review" in text
    assert "Pass (Y/N)" in text
    assert "Recommended Changes" in text
    # No findings dump, no before/after evidence, no other checklist tab.
    for unwanted in ("Evidence before", "Evidence after", "QC Findings", "Tech Review"):
        assert unwanted not in text, f"PDF still carries '{unwanted}'"


# -- OOXML package integrity ----------------------------------------------
def _validate_xlsx_package(path) -> list:
    """Check the parts Excel checks when it decides a file is corrupt."""
    import re
    import xml.etree.ElementTree as ET
    import zipfile

    archive = zipfile.ZipFile(path)
    names = set(archive.namelist())
    problems = []

    if archive.testzip() is not None:
        problems.append("corrupt zip entry")

    for rels in [n for n in names if n.endswith(".rels")]:
        base = rels.rsplit("_rels/", 1)[0]
        for rel in ET.fromstring(archive.read(rels)):
            target = rel.get("Target", "")
            if target.startswith(("http", "../")) or rel.get("TargetMode") == "External":
                continue
            part = target.lstrip("/") if target.startswith("/") else base + target
            if part not in names:
                problems.append(f"{rels}: dangling relationship target {target}")

    workbook_xml = archive.read("xl/workbook.xml").decode()
    sheets = re.findall(r'<sheet name="([^"]+)"', workbook_xml)

    # A view pointing past the last sheet is what Excel reports as corruption.
    for attribute in ("firstSheet", "activeTab"):
        match = re.search(rf'{attribute}="(\d+)"', workbook_xml)
        if match and int(match.group(1)) >= len(sheets):
            problems.append(
                f"{attribute}={match.group(1)} is out of range for {len(sheets)} sheet(s)"
            )

    for defined in re.findall(r"<definedName[^>]*>([^<]*)</definedName>", workbook_xml):
        sheet_ref = defined.split("!")[0].strip("'")
        if sheet_ref and sheet_ref not in sheets and not sheet_ref.startswith("["):
            problems.append(f"definedName references a removed sheet: {sheet_ref}")

    return problems


def test_review_xlsx_package_is_valid(review_report, tmp_path):
    """Deleting template sheets must not leave Excel with dangling indices."""
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")
    path = ExcelReportWriter(template).write_review(review_report, tmp_path / "pkg.xlsx")
    assert _validate_xlsx_package(path) == []


def test_review_xlsx_reopens_cleanly(review_report, tmp_path):
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")
    path = ExcelReportWriter(template).write_review(review_report, tmp_path / "reopen.xlsx")
    reopened = openpyxl.load_workbook(path)
    assert "Agent Review" in reopened.sheetnames
    assert reopened["Agent Review"].cell(row=10, column=3).value in {"Y", "N"}


# -- cross-format consistency ---------------------------------------------
def _pdf_answers(path, checklist) -> dict:
    """Pull the Y/N answer for each checklist row out of the rendered PDF."""
    import re

    from pypdf import PdfReader

    text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in PdfReader(str(path)).pages))
    answers = {}
    for result in checklist:
        match = re.search(rf"\b{re.escape(result.item_id)}\b\s+(.*?)\s+\b([YN])\b", text)
        if match:
            answers[result.cell] = match.group(2)
    return answers


def test_excel_and_pdf_report_identical_answers(review_report, tmp_path):
    """A reviewer must never see one verdict in Excel and another in the PDF."""
    template = excel_template_or_none()
    if template is None:
        pytest.skip("review template not available")

    xlsx = ExcelReportWriter(template).write_review(review_report, tmp_path / "x.xlsx")
    pdf = write_pdf_report(review_report, tmp_path / "x.pdf")

    expected = {r.cell: r.pass_flag for r in review_report.checklist}

    sheet = openpyxl.load_workbook(xlsx)["Agent Review"]
    excel_answers = {
        f"B{row}": sheet.cell(row=row, column=3).value
        for row in range(4, 26)
        if sheet.cell(row=row, column=3).value
    }

    assert excel_answers == expected
    assert _pdf_answers(pdf, review_report.checklist) == expected
