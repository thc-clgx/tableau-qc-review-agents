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
    Status.PASS.value: "PASS",
    Status.FAIL.value: "FAIL",
    Status.ADVISORY.value: "ADVISORY",
    Status.MANUAL_REVIEW.value: "MANUAL",
    Status.NOT_APPLICABLE.value: "N/A",
}

VERIFICATION_COLOURS = {
    "PASS": colors.HexColor("#C6EFCE"),
    "FAIL": colors.HexColor("#FFC7CE"),
    "ADVISORY": colors.HexColor("#FCE4D6"),
    "MANUAL": colors.HexColor("#FFEB9C"),
    "N/A": colors.HexColor("#D9D9D9"),
}


def verification_label(status) -> str:
    """Map any status onto the standard PASS / FAIL / ADVISORY / MANUAL set."""
    if status is None:
        return "MANUAL"
    value = status.value if hasattr(status, "value") else str(status)
    return VERIFICATION_LABELS.get(value, "MANUAL")


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


def _review_story(report: ReviewReport, styles, story: List) -> None:
    summary = report.summary
    workbook = report.workbook or {}
    story.append(Paragraph("Tableau Pre-Technical Review", styles["Title"]))
    story.append(
        Paragraph(
            f"Workbook: <b>{workbook.get('name', 'unknown')}</b> &nbsp;|&nbsp; "
            f"Generated: {report.generated_at} &nbsp;|&nbsp; "
            f"Overall status: <b>{summary['overall_status']}</b>",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "Findings: "
            + ", ".join(f"{k} {v}" for k, v in summary["by_status"].items())
            + f" &nbsp;|&nbsp; XML SHA-256: {workbook.get('source_sha256', 'n/a')}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 10))

    header = ["Rule", "Title", "Target", "Verification", "Evidence", "Recommended change"]
    data: List[List] = [[Paragraph(h, styles["CellHeader"]) for h in header]]
    for finding in report.findings:
        evidence = "<br/>".join(
            f"{e.field_path}: observed {e.observed!r} vs {e.operator} {e.expected!r}"
            for e in finding.evidence
            if e.note != "context"
        )
        data.append(
            [
                Paragraph(finding.rule_id, styles["Cell"]),
                Paragraph(finding.title, styles["Cell"]),
                Paragraph(str(finding.target_name or finding.target_id), styles["Cell"]),
                Paragraph(verification_label(finding.status), styles["Cell"]),
                Paragraph(evidence, styles["Cell"]),
                Paragraph(finding.recommendation or "", styles["Cell"]),
            ]
        )
    story.append(
        _table(
            data,
            [0.8 * inch, 2.1 * inch, 1.7 * inch, 0.9 * inch, 2.6 * inch, 2.4 * inch],
            3,
            VERIFICATION_COLOURS,
        )
    )

    story.append(Spacer(1, 14))
    story.append(Paragraph("Review checklist", styles["Heading2"]))
    checklist_header = ["Item", "Question", "Verification", "Comment"]
    checklist_data: List[List] = [[Paragraph(h, styles["CellHeader"]) for h in checklist_header]]
    for result in report.checklist:
        checklist_data.append(
            [
                Paragraph(result.item_id, styles["Cell"]),
                Paragraph(result.question, styles["Cell"]),
                Paragraph(verification_label(result.status), styles["Cell"]),
                Paragraph(result.recommendation, styles["Cell"]),
            ]
        )
    story.append(
        _table(
            checklist_data,
            [0.7 * inch, 4.0 * inch, 1.0 * inch, 4.8 * inch],
            2,
            VERIFICATION_COLOURS,
        )
    )


def _verification_story(report: VerificationReport, styles, story: List) -> None:
    summary = report.summary
    story.append(Paragraph("Tableau Post-Technical Review Verification", styles["Title"]))
    story.append(
        Paragraph(
            f"Generated: {report.generated_at} &nbsp;|&nbsp; "
            f"Sign-off ready: <b>{'YES' if summary['sign_off_ready'] else 'NO'}</b> &nbsp;|&nbsp; "
            f"Regressions: {summary['regression_count']} &nbsp;|&nbsp; "
            f"Unresolved: {summary['unresolved_count']}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 10))

    header = ["Rule", "Title", "Target", "Verification", "Evidence", "Recommended change"]
    data: List[List] = [[Paragraph(h, styles["CellHeader"]) for h in header]]
    for comparison in report.comparisons:
        data.append(
            [
                Paragraph(comparison.rule_id, styles["Cell"]),
                Paragraph(comparison.title, styles["Cell"]),
                Paragraph(comparison.target_id, styles["Cell"]),
                Paragraph(verification_label(comparison.revised_status), styles["Cell"]),
                Paragraph(_evidence_html(comparison.revised_evidence), styles["Cell"]),
                Paragraph(comparison.recommendation or "", styles["Cell"]),
            ]
        )
    story.append(
        _table(
            data,
            [0.8 * inch, 2.1 * inch, 1.7 * inch, 0.9 * inch, 2.6 * inch, 2.4 * inch],
            3,
            VERIFICATION_COLOURS,
        )
    )

    story.append(Spacer(1, 14))
    story.append(Paragraph("Review checklist", styles["Heading2"]))
    checklist_header = ["Item", "Question", "Verification", "Comment"]
    checklist_data: List[List] = [[Paragraph(h, styles["CellHeader"]) for h in checklist_header]]
    for result in report.checklist:
        checklist_data.append(
            [
                Paragraph(result.item_id, styles["Cell"]),
                Paragraph(result.question, styles["Cell"]),
                Paragraph(verification_label(result.status), styles["Cell"]),
                Paragraph(result.recommendation, styles["Cell"]),
            ]
        )
    story.append(
        _table(
            checklist_data,
            [0.7 * inch, 4.0 * inch, 1.0 * inch, 4.8 * inch],
            2,
            VERIFICATION_COLOURS,
        )
    )


def _evidence_html(evidence: Sequence[dict]) -> str:
    lines = []
    for item in evidence:
        if item.get("note") == "context":
            continue
        lines.append(f"{item.get('field')}: {item.get('observed')!r}")
    return "<br/>".join(lines)
