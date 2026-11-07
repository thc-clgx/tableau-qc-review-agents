"""Excel reporting: populates the Tableau Dashboard Review checklist."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from openpyxl import Workbook as XLWorkbook
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet as XLWorksheet

from ..domain.comparison import VerificationReport, VerificationStatus
from ..domain.findings import ChecklistResult, Finding, ReviewReport, Status

PathLike = Union[str, Path]

SUMMARY_SHEET = "QC Summary"
FINDINGS_SHEET = "QC Findings"
VERIFICATION_SHEET = "QC Verification"
SME_SHEET = "SME Feedback"

STATUS_FILLS: Dict[str, PatternFill] = {
    Status.PASS.value: PatternFill("solid", fgColor="C6EFCE"),
    Status.FAIL.value: PatternFill("solid", fgColor="FFC7CE"),
    Status.ADVISORY.value: PatternFill("solid", fgColor="FCE4D6"),
    Status.MANUAL_REVIEW.value: PatternFill("solid", fgColor="FFEB9C"),
    Status.NOT_APPLICABLE.value: PatternFill("solid", fgColor="D9D9D9"),
}

VERIFICATION_FILLS: Dict[str, PatternFill] = {
    VerificationStatus.RESOLVED.value: PatternFill("solid", fgColor="C6EFCE"),
    VerificationStatus.UNCHANGED_PASS.value: PatternFill("solid", fgColor="E2EFDA"),
    VerificationStatus.UNRESOLVED.value: PatternFill("solid", fgColor="FFC7CE"),
    VerificationStatus.PARTIALLY_RESOLVED.value: PatternFill("solid", fgColor="FCE4D6"),
    VerificationStatus.NEW_REGRESSION.value: PatternFill("solid", fgColor="F8696B"),
    VerificationStatus.CANNOT_VERIFY.value: PatternFill("solid", fgColor="FFEB9C"),
}

HEADER_FILL = PatternFill("solid", fgColor="1E1405")
HEADER_FONT = Font(bold=True, color="F7EFE2")
WRAP = Alignment(wrap_text=True, vertical="top")


class ExcelReportWriter:
    """Writes review and verification results into the Excel checklist."""

    def __init__(self, template_path: Optional[PathLike] = None) -> None:
        self.template_path = Path(template_path) if template_path else None

    # -- public API --------------------------------------------------------
    def write_review(self, report: ReviewReport, path: PathLike) -> Path:
        workbook = self._open_workbook()
        self._populate_checklist(workbook, report.checklist)
        self._write_summary(workbook, self._review_summary_rows(report))
        self._write_findings(workbook, report.findings)
        return self._save(workbook, path)

    def write_verification(self, report: VerificationReport, path: PathLike) -> Path:
        workbook = self._open_workbook()
        self._populate_checklist(workbook, report.checklist)
        self._write_summary(workbook, self._verification_summary_rows(report))
        self._write_findings(workbook, report.revised_findings)
        self._write_verification(workbook, report)
        if report.sme_feedback:
            self._write_sme_feedback(workbook, report)
        return self._save(workbook, path)

    # -- workbook plumbing -------------------------------------------------
    def _open_workbook(self) -> XLWorkbook:
        if self.template_path and self.template_path.is_file():
            return load_workbook(self.template_path)
        workbook = XLWorkbook()
        workbook.remove(workbook.active)
        return workbook

    @staticmethod
    def _save(workbook: XLWorkbook, path: PathLike) -> Path:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(out_path)
        return out_path

    def _sheet(self, workbook: XLWorkbook, name: str) -> XLWorksheet:
        if name in workbook.sheetnames:
            sheet = workbook[name]
            sheet.delete_rows(1, sheet.max_row or 1)
            return sheet
        return workbook.create_sheet(name)

    @staticmethod
    def _write_header(sheet: XLWorksheet, headers: Sequence[str], widths: Sequence[int]) -> None:
        sheet.append(list(headers))
        for index, (header, width) in enumerate(zip(headers, widths), start=1):
            cell = sheet.cell(row=1, column=index)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            sheet.column_dimensions[get_column_letter(index)].width = width
        sheet.freeze_panes = "A2"

    # -- checklist ---------------------------------------------------------
    def _populate_checklist(self, workbook: XLWorkbook, results: Sequence[ChecklistResult]) -> None:
        by_sheet: Dict[str, List[ChecklistResult]] = {}
        for result in results:
            by_sheet.setdefault(result.sheet or "Checklist", []).append(result)

        for sheet_name, sheet_results in by_sheet.items():
            if sheet_name in workbook.sheetnames:
                self._fill_template_sheet(workbook[sheet_name], sheet_results)
            else:
                self._write_checklist_sheet(workbook.create_sheet(sheet_name), sheet_results)

    def _fill_template_sheet(
        self, sheet: XLWorksheet, results: Sequence[ChecklistResult]
    ) -> None:
        for result in results:
            if not result.cell:
                continue
            row = int("".join(ch for ch in result.cell if ch.isdigit()))
            answer = sheet.cell(row=row, column=3)
            answer.value = result.pass_flag
            answer.fill = STATUS_FILLS[result.status.value]
            answer.alignment = Alignment(horizontal="center", vertical="top")

            comment_parts = [part for part in (result.recommendation, result.evidence_summary) if part]
            comment = sheet.cell(row=row, column=4)
            comment.value = "\n".join(comment_parts)
            comment.alignment = WRAP
        sheet.column_dimensions["C"].width = 12
        sheet.column_dimensions["D"].width = 90

    def _write_checklist_sheet(
        self, sheet: XLWorksheet, results: Sequence[ChecklistResult]
    ) -> None:
        self._write_header(
            sheet,
            ["Item", "Section", "Question", "Pass (Y/N)", "Status", "Recommended Changes", "Evidence"],
            [10, 28, 60, 12, 16, 60, 70],
        )
        for result in results:
            sheet.append(
                [
                    result.item_id,
                    result.section or "",
                    result.question,
                    result.pass_flag,
                    result.status.value,
                    result.recommendation,
                    result.evidence_summary,
                ]
            )
            cell = sheet.cell(row=sheet.max_row, column=4)
            cell.fill = STATUS_FILLS[result.status.value]
            for column in (3, 6, 7):
                sheet.cell(row=sheet.max_row, column=column).alignment = WRAP

    # -- summary -----------------------------------------------------------
    def _write_summary(self, workbook: XLWorkbook, rows: Sequence[Sequence[object]]) -> None:
        sheet = self._sheet(workbook, SUMMARY_SHEET)
        self._write_header(sheet, ["Metric", "Value"], [42, 90])
        for row in rows:
            sheet.append(list(row))
            sheet.cell(row=sheet.max_row, column=2).alignment = WRAP

    @staticmethod
    def _review_summary_rows(report: ReviewReport) -> List[List[object]]:
        summary = report.summary
        workbook_info = report.workbook or {}
        counts = workbook_info.get("counts", {})
        rows: List[List[object]] = [
            ["Report type", report.report_type],
            ["Generated at (UTC)", report.generated_at],
            ["Workbook", workbook_info.get("name", "")],
            ["Source XML", workbook_info.get("source_path", "")],
            ["Source SHA-256", workbook_info.get("source_sha256", "")],
            ["Rule repository checksum", (report.rule_repository or {}).get("checksum", "")],
            ["Rules evaluated", summary["rules_evaluated"]],
            ["Rules failed", summary["rules_failed"]],
            ["Overall status", summary["overall_status"]],
        ]
        for status, count in summary["by_status"].items():
            rows.append([f"Findings - {status}", count])
        for key, value in counts.items():
            rows.append([f"Workbook objects - {key}", value])
        return rows

    @staticmethod
    def _verification_summary_rows(report: VerificationReport) -> List[List[object]]:
        summary = report.summary
        rows: List[List[object]] = [
            ["Report type", report.report_type],
            ["Generated at (UTC)", report.generated_at],
            ["Baseline source", (report.baseline or {}).get("source_path", "")],
            ["Baseline SHA-256", (report.baseline or {}).get("source_sha256", "")],
            ["Revised source", (report.revised or {}).get("source_path", "")],
            ["Revised SHA-256", (report.revised or {}).get("source_sha256", "")],
            ["Comparisons", summary["total_comparisons"]],
            ["Unresolved", summary["unresolved_count"]],
            ["New regressions", summary["regression_count"]],
            ["Sign-off ready", "YES" if summary["sign_off_ready"] else "NO"],
        ]
        for status, count in summary["by_verification"].items():
            rows.append([f"Verification - {status}", count])
        return rows

    # -- findings ----------------------------------------------------------
    def _write_findings(self, workbook: XLWorkbook, findings: Sequence[Finding]) -> None:
        sheet = self._sheet(workbook, FINDINGS_SHEET)
        self._write_header(
            sheet,
            [
                "Rule ID",
                "Title",
                "Category",
                "Severity",
                "Status",
                "Target type",
                "Target",
                "Message",
                "Evidence (field / expected / observed / XPath)",
                "Recommended change",
                "Checklist",
                "Standard",
            ],
            [16, 42, 14, 10, 16, 20, 28, 60, 80, 60, 16, 42],
        )
        for finding in findings:
            evidence = "\n".join(
                f"{e.field_path} | expected {e.operator} {e.expected!r} | observed {e.observed!r} | "
                f"{e.source.xpath if e.source else 'n/a'}"
                for e in finding.evidence
            )
            sheet.append(
                [
                    finding.rule_id,
                    finding.title,
                    finding.category or "",
                    finding.severity.value,
                    finding.status.value,
                    finding.target_type,
                    finding.target_name or finding.target_id,
                    finding.message,
                    evidence,
                    finding.recommendation or "",
                    finding.checklist_ref or "",
                    finding.standard_ref or "",
                ]
            )
            sheet.cell(row=sheet.max_row, column=5).fill = STATUS_FILLS[finding.status.value]
            for column in (8, 9, 10):
                sheet.cell(row=sheet.max_row, column=column).alignment = WRAP

    # -- verification ------------------------------------------------------
    def _write_verification(self, workbook: XLWorkbook, report: VerificationReport) -> None:
        sheet = self._sheet(workbook, VERIFICATION_SHEET)
        self._write_header(
            sheet,
            [
                "Rule ID",
                "Title",
                "Target",
                "Verification",
                "Baseline status",
                "Revised status",
                "Evidence before",
                "Evidence after",
                "Recommended change",
                "Note",
            ],
            [16, 42, 30, 20, 16, 16, 70, 70, 60, 40],
        )
        for comparison in report.comparisons:
            sheet.append(
                [
                    comparison.rule_id,
                    comparison.title,
                    comparison.target_id,
                    comparison.verification.value,
                    comparison.baseline_status.value if comparison.baseline_status else "",
                    comparison.revised_status.value if comparison.revised_status else "",
                    _format_evidence(comparison.baseline_evidence),
                    _format_evidence(comparison.revised_evidence),
                    comparison.recommendation or "",
                    comparison.note,
                ]
            )
            sheet.cell(row=sheet.max_row, column=4).fill = VERIFICATION_FILLS[
                comparison.verification.value
            ]
            for column in (7, 8, 9, 10):
                sheet.cell(row=sheet.max_row, column=column).alignment = WRAP

    def _write_sme_feedback(self, workbook: XLWorkbook, report: VerificationReport) -> None:
        sheet = self._sheet(workbook, SME_SHEET)
        self._write_header(
            sheet,
            ["Rule ID", "Target", "Author", "Raised on", "Status", "Comment"],
            [16, 30, 20, 16, 18, 80],
        )
        for item in report.sme_feedback:
            sheet.append(
                [
                    item.rule_id or "",
                    item.target_id or "",
                    item.author or "",
                    item.raised_on or "",
                    item.status.value,
                    item.comment,
                ]
            )
            sheet.cell(row=sheet.max_row, column=6).alignment = WRAP


def _format_evidence(evidence: Sequence[dict]) -> str:
    lines = []
    for item in evidence:
        if item.get("note") == "context":
            continue
        lines.append(
            f"{item.get('field')} | expected {item.get('operator')} {item.get('expected')!r} | "
            f"observed {item.get('observed')!r} | {item.get('xpath') or 'n/a'}"
        )
    return "\n".join(lines)


def write_excel_report(
    report: Union[ReviewReport, VerificationReport],
    path: PathLike,
    *,
    template_path: Optional[PathLike] = None,
) -> Path:
    """Write the appropriate Excel report for a review or verification run."""
    writer = ExcelReportWriter(template_path)
    if isinstance(report, VerificationReport):
        return writer.write_verification(report, path)
    return writer.write_review(report, path)
