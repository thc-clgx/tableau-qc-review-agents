"""PDF reporting for stakeholder distribution."""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Union

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..domain.comparison import VerificationReport
from ..domain.findings import ReviewReport, Status

PathLike = Union[str, Path]

HEADER_BG = colors.HexColor("#1E1405")
HEADER_FG = colors.HexColor("#F7EFE2")

#: The single standard verification vocabulary used in every PDF column.
VERIFICATION_LABELS = {
    Status.PASS.value: "Y",
    Status.NOT_APPLICABLE.value: "Y",
    Status.FAIL.value: "N",
    Status.MANUAL_REVIEW.value: "N",
}

VERIFICATION_COLOURS = {
    "Y": colors.HexColor("#C6EFCE"),
    "N": colors.HexColor("#FFC7CE"),
}


def verification_label(status) -> str:
    """Map any status onto the binary Y / N answer used by the checklist."""
    if status is None:
        return "N"
    value = status.value if hasattr(status, "value") else str(status)
    return VERIFICATION_LABELS.get(value, "N")


def _styles():
    sheet = getSampleStyleSheet()
    sheet.add(
        ParagraphStyle(
            name="Cell", fontName="Helvetica", fontSize=7, leading=9, alignment=TA_LEFT
        )
    )
    sheet.add(
        ParagraphStyle(
            name="CellHeader",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=HEADER_FG,
        )
    )
    return sheet


def _table(data: List[List], widths: Sequence[float], colour_column: int, colour_map) -> Table:
    table = Table(data, colWidths=list(widths), repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_FG),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
    ]
    for row_index, row in enumerate(data[1:], start=1):
        value = row[colour_column]
        label = value.text if hasattr(value, "text") else str(value)
        colour = colour_map.get(label)
        if colour is not None:
            style.append(("BACKGROUND", (colour_column, row_index), (colour_column, row_index), colour))
    table.setStyle(TableStyle(style))
    return table


def write_pdf_report(
    report: Union[ReviewReport, VerificationReport], path: PathLike
) -> Path:
    """Render a review or verification report to PDF."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=landscape(letter),
        leftMargin=0.4 * inch,
        rightMargin=0.4 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=report.report_type,
    )
    story = []
    if isinstance(report, VerificationReport):
        _verification_story(report, styles, story)
    else:
        _review_story(report, styles, story)
    doc.build(story)
    return out_path


def _header(title: str, subtitle: str, styles, story: List) -> None:
    story.append(Paragraph(title, styles["Title"]))
    story.append(Paragraph(subtitle, styles["Normal"]))
    story.append(Spacer(1, 10))


def _checklist_table(results, styles) -> Table:
    """The Agent Review checklist: question, Y/N answer, recommendation."""
    header = ["Item", "Question", "Pass (Y/N)", "Recommended Changes"]
    data: List[List] = [[Paragraph(h, styles["CellHeader"]) for h in header]]
    for result in results:
        data.append(
            [
                Paragraph(result.item_id, styles["Cell"]),
                Paragraph(result.question, styles["Cell"]),
                Paragraph(verification_label(result.status), styles["Cell"]),
                Paragraph(result.recommendation, styles["Cell"]),
            ]
        )
    return _table(
        data,
        [0.7 * inch, 4.2 * inch, 0.8 * inch, 4.8 * inch],
        2,
        VERIFICATION_COLOURS,
    )


def _review_story(report: ReviewReport, styles, story: List) -> None:
    """Agent Review output only - no findings dump, no other tabs."""
    workbook = report.workbook or {}
    passed = len([r for r in report.checklist if r.pass_flag == "Y"])
    total = len(report.checklist)
    _header(
        "Tableau Dashboard Review - Agent Review",
        f"Workbook: <b>{workbook.get('name', 'unknown')}</b> &nbsp;|&nbsp; "
        f"Generated: {report.generated_at[:10]} &nbsp;|&nbsp; "
        f"Passed: <b>{passed} of {total}</b>",
        styles,
        story,
    )
    story.append(_checklist_table(report.checklist, styles))


def _verification_story(report: VerificationReport, styles, story: List) -> None:
    """Agent Review output only, reflecting the revised workbook."""
    revised = report.revised or {}
    passed = len([r for r in report.checklist if r.pass_flag == "Y"])
    total = len(report.checklist)
    summary = report.summary
    _header(
        "Tableau Dashboard Review - Agent Review (post-review)",
        f"Workbook: <b>{revised.get('name', 'unknown')}</b> &nbsp;|&nbsp; "
        f"Generated: {report.generated_at[:10]} &nbsp;|&nbsp; "
        f"Passed: <b>{passed} of {total}</b> &nbsp;|&nbsp; "
        f"Resolved: {summary['by_verification']['RESOLVED']} &nbsp;|&nbsp; "
        f"New failures: {summary['new_failure_count']}",
        styles,
        story,
    )
    story.append(_checklist_table(report.checklist, styles))


def _evidence_html(evidence: Sequence[dict]) -> str:
    lines = []
    for item in evidence:
        if item.get("note") == "context":
            continue
        lines.append(f"{item.get('field')}: {item.get('observed')!r}")
    return "<br/>".join(lines)
