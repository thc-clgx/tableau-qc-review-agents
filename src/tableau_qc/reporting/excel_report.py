"""Excel reporting: populates the Tableau Dashboard Review checklist."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from openpyxl import Workbook as XLWorkbook
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet as XLWorksheet

from ..domain.comparison import VerificationReport
from ..domain.findings import ChecklistResult, ReviewReport, Status

PathLike = Union[str, Path]

STATUS_FILLS: Dict[str, PatternFill] = {
    Status.PASS.value: PatternFill("solid", fgColor="C6EFCE"),
    Status.FAIL.value: PatternFill("solid", fgColor="FFC7CE"),
    Status.MANUAL_REVIEW.value: PatternFill("solid", fgColor="FFEB9C"),
    Status.NOT_APPLICABLE.value: PatternFill("solid", fgColor="D9D9D9"),
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
        """Write the review workbook with only the Agent Review tab filled in."""
        workbook = self._open_workbook()
        self._populate_checklist(workbook, report.checklist)
        self._focus_agent_tab(workbook, report.checklist)
        return self._save(workbook, path)

    def write_verification(self, report: VerificationReport, path: PathLike) -> Path:
        workbook = self._open_workbook()
        self._populate_checklist(workbook, report.checklist)
        self._focus_agent_tab(workbook, report.checklist)
        return self._save(workbook, path)

    @staticmethod
    def _focus_agent_tab(workbook: XLWorkbook, results: Sequence[ChecklistResult]) -> None:
        """Open the workbook on the tab the agent filled.

        Every template tab is preserved - the Peer Review and Tech Review tabs
        are the human review portions and are handed back untouched. Only the
        selected tab changes, so the file opens on the agent's results.
        """
        answered = [r.sheet for r in results if r.sheet]
        if not answered:
            return
        target = answered[0]
        if target not in workbook.sheetnames:
            return

        index = workbook.sheetnames.index(target)
        for view in getattr(workbook, "views", []) or []:
            view.activeTab = index
            # firstSheet must not exceed the active tab or Excel rejects the view.
            view.firstSheet = 0
        for position, sheet in enumerate(workbook.worksheets):
            sheet.views.sheetView[0].tabSelected = position == index

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
