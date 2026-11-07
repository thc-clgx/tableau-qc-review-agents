"""Agent 1 - pre-technical review.

Pipeline: secure XML load -> parse -> normalise -> deterministic rule engine ->
findings with evidence -> recommendations -> checklist -> reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from ..checklist import ChecklistDefinition, build_checklist_results, checklist_metadata, load_checklist
from ..domain.findings import Finding, ReviewReport
from ..domain.models import Workbook
from ..parsers.workbook_parser import WorkbookParser
from ..recommendations.engine import RecommendationEngine
from ..recommendations.llm import LLMProvider
from ..reporting.excel_report import ExcelReportWriter
from ..reporting.json_report import write_json_report
from ..reporting.pdf_report import write_pdf_report
from ..rules.engine import RuleEngine
from ..rules.loader import RuleRepository, load_rules
from ..settings import (
    DEFAULT_CHECKLIST_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RULES_DIR,
    excel_template_or_none,
)
from ..xmlio.loader import load_xml_file

PathLike = Union[str, Path]


@dataclass
class ReviewArtifacts:
    """Files produced by a review run."""

    json_path: Optional[Path] = None
    excel_path: Optional[Path] = None
    pdf_path: Optional[Path] = None

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {
            "json": str(self.json_path) if self.json_path else None,
            "excel": str(self.excel_path) if self.excel_path else None,
            "pdf": str(self.pdf_path) if self.pdf_path else None,
        }


class PreTechnicalReviewAgent:
    """Runs the automated pre-technical QC review of a Tableau workbook XML."""

    def __init__(
        self,
        *,
        rules_path: PathLike = DEFAULT_RULES_DIR,
        checklist_path: Optional[PathLike] = DEFAULT_CHECKLIST_PATH,
        excel_template: Optional[PathLike] = None,
        llm_provider: Optional[LLMProvider] = None,
        rule_ids: Optional[Sequence[str]] = None,
        categories: Optional[Sequence[str]] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> None:
        self.repository: RuleRepository = load_rules(rules_path)
        if rule_ids or categories or tags:
            self.repository = self.repository.filtered(
                rule_ids=rule_ids, categories=categories, tags=tags
            )
        self.engine = RuleEngine(self.repository)
        self.checklist: Optional[ChecklistDefinition] = (
            load_checklist(checklist_path) if checklist_path else None
        )
        self.excel_template = Path(excel_template) if excel_template else excel_template_or_none()
        self.recommendation_engine = RecommendationEngine(llm_provider)

    # -- pipeline ----------------------------------------------------------
    def parse(self, xml_path: PathLike) -> Workbook:
        """Securely load and normalise the workbook XML."""
        document = load_xml_file(xml_path)
        return WorkbookParser(document).parse()

    def evaluate(self, workbook: Workbook) -> List[Finding]:
        findings = self.engine.execute(workbook)
        return self.recommendation_engine.apply(findings)

    def run(self, xml_path: PathLike) -> ReviewReport:
        """Execute the full review and return the in-memory report."""
        workbook = self.parse(xml_path)
        findings = self.evaluate(workbook)

        report = ReviewReport(
            workbook=workbook.as_dict(),
            rule_repository=self.repository.as_dict(),
            findings=findings,
        )
        if self.checklist is not None:
            report.checklist = build_checklist_results(
                self.checklist, findings, evaluated_rule_ids=self.repository.rule_ids
            )
            report.rule_repository["checklist"] = checklist_metadata(self.checklist)
        return report

    def run_and_export(
        self,
        xml_path: PathLike,
        *,
        output_dir: PathLike = DEFAULT_OUTPUT_DIR,
        basename: Optional[str] = None,
        write_json: bool = True,
        write_excel: bool = True,
        write_pdf: bool = False,
    ) -> tuple[ReviewReport, ReviewArtifacts]:
        """Run the review and write the requested report files."""
        report = self.run(xml_path)
        stem = basename or Path(xml_path).stem
        out_dir = Path(output_dir)
        artifacts = ReviewArtifacts()

        if write_json:
            artifacts.json_path = write_json_report(report, out_dir / f"{stem}_pre_review.json")
        if write_excel:
            writer = ExcelReportWriter(self.excel_template)
            artifacts.excel_path = writer.write_review(report, out_dir / f"{stem}_pre_review.xlsx")
        if write_pdf:
            artifacts.pdf_path = write_pdf_report(report, out_dir / f"{stem}_pre_review.pdf")
        return report, artifacts
