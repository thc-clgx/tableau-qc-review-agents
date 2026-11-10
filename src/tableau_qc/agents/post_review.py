"""Agent 2 - post-technical review verification.

Re-runs every QC rule against the revised workbook XML, matches the results
against the baseline audit (previous JSON report and/or baseline XML),
classifies each cited issue and detects regressions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import yaml

from ..checklist import ChecklistDefinition, build_checklist_results, checklist_metadata, load_checklist
from ..domain.comparison import Comparison, SMEFeedbackItem, VerificationReport, VerificationStatus
from ..domain.findings import Finding, Status
from ..domain.models import Workbook
from ..parsers.workbook_parser import WorkbookParser
from ..recommendations.engine import RecommendationEngine
from ..recommendations.llm import LLMProvider
from ..reporting.excel_report import ExcelReportWriter
from ..reporting.json_report import load_json_report, write_json_report
from ..reporting.pdf_report import write_pdf_report
from ..rules.engine import RuleEngine
from ..rules.loader import RuleRepository, load_rules
from ..rules.operators import OperatorError, get_operator
from ..settings import (
    DEFAULT_CHECKLIST_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RULES_DIR,
    excel_template_or_none,
)
from ..xmlio.loader import load_xml_file
from .pre_review import ReviewArtifacts

PathLike = Union[str, Path]


class VerificationInputError(ValueError):
    """Raised when Agent 2 is given an unusable set of inputs."""


@dataclass
class BaselineFinding:
    """Normalised baseline result, from a previous audit JSON or baseline XML."""

    key: str
    rule_id: str
    title: str
    status: Status
    target_type: str
    target_id: str
    target_name: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    recommendation: Optional[str] = None
    checklist_ref: Optional[str] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_finding(cls, finding: Finding) -> "BaselineFinding":
        return cls(
            key=finding.key,
            rule_id=finding.rule_id,
            title=finding.title,
            status=finding.status,
            target_type=finding.target_type,
            target_id=finding.target_id,
            target_name=finding.target_name,
            severity=finding.severity.value,
            category=finding.category,
            recommendation=finding.recommendation,
            checklist_ref=finding.checklist_ref,
            evidence=[e.as_dict() for e in finding.evidence],
        )

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "BaselineFinding":
        target = data.get("target") or {}
        rule_id = data.get("rule_id", "")
        target_type = target.get("type", "unknown")
        target_id = target.get("id", "*")
        return cls(
            key=data.get("key") or f"{rule_id}::{target_type}::{target_id}",
            rule_id=rule_id,
            title=data.get("title", ""),
            status=Status(data.get("status", Status.MANUAL_REVIEW.value)),
            target_type=target_type,
            target_id=target_id,
            target_name=target.get("name"),
            severity=data.get("severity"),
            category=data.get("category"),
            recommendation=data.get("recommendation"),
            checklist_ref=data.get("checklist_ref"),
            evidence=list(data.get("evidence") or []),
        )


def _failed_fields(evidence: Sequence[Dict[str, Any]]) -> set:
    """Field paths whose assertion does not hold for the recorded evidence."""
    failed = set()
    for item in evidence:
        if item.get("note") == "context" or not item.get("operator"):
            continue
        if not item.get("observed_available", True):
            continue
        try:
            operator = get_operator(str(item["operator"]))
            if not operator(item.get("observed"), item.get("expected")):
                failed.add(str(item.get("field")))
        except (OperatorError, KeyError, TypeError):
            continue
    return failed


def load_sme_feedback(path: PathLike) -> List[SMEFeedbackItem]:
    """Load optional SME feedback from a YAML or JSON file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise VerificationInputError(f"SME feedback file not found: {file_path}")
    text = file_path.read_text(encoding="utf-8")
    data = json.loads(text) if file_path.suffix.lower() == ".json" else yaml.safe_load(text)
    if isinstance(data, dict):
        data = data.get("feedback") or data.get("items") or []
    if not isinstance(data, list):
        raise VerificationInputError(f"{file_path}: expected a list of feedback items")

    items: List[SMEFeedbackItem] = []
    for entry in data:
        if isinstance(entry, str):
            items.append(SMEFeedbackItem(comment=entry))
            continue
        if not isinstance(entry, dict):
            raise VerificationInputError(f"{file_path}: feedback items must be strings or mappings")
        comment = entry.get("comment") or entry.get("note")
        if not comment:
            raise VerificationInputError(f"{file_path}: each feedback item requires a 'comment'")
        items.append(
            SMEFeedbackItem(
                comment=str(comment),
                rule_id=entry.get("rule_id"),
                target_id=entry.get("target_id"),
                author=entry.get("author"),
                raised_on=str(entry["raised_on"]) if entry.get("raised_on") else None,
            )
        )
    return items


class PostTechnicalReviewAgent:
    """Verifies that technical-review feedback was addressed in a revised workbook."""

    def __init__(
        self,
        *,
        rules_path: PathLike = DEFAULT_RULES_DIR,
        checklist_path: Optional[PathLike] = DEFAULT_CHECKLIST_PATH,
        excel_template: Optional[PathLike] = None,
        llm_provider: Optional[LLMProvider] = None,
        rule_ids: Optional[Sequence[str]] = None,
    ) -> None:
        self.repository: RuleRepository = load_rules(rules_path)
        if rule_ids:
            self.repository = self.repository.filtered(rule_ids=rule_ids)
        self.engine = RuleEngine(self.repository)
        self.checklist: Optional[ChecklistDefinition] = (
            load_checklist(checklist_path) if checklist_path else None
        )
        self.excel_template = Path(excel_template) if excel_template else excel_template_or_none()
        self.recommendation_engine = RecommendationEngine(llm_provider)

    # -- pipeline ----------------------------------------------------------
    def parse(self, xml_path: PathLike) -> Workbook:
        return WorkbookParser(load_xml_file(xml_path)).parse()

    def run(
        self,
        revised_xml: PathLike,
        *,
        baseline_xml: Optional[PathLike] = None,
        previous_audit_json: Optional[PathLike] = None,
        sme_feedback_path: Optional[PathLike] = None,
    ) -> VerificationReport:
        if baseline_xml is None and previous_audit_json is None:
            raise VerificationInputError(
                "Agent 2 requires a baseline XML and/or a previous audit JSON"
            )

        revised_workbook = self.parse(revised_xml)
        revised_findings = self.recommendation_engine.apply(self.engine.execute(revised_workbook))

        baseline_meta: Dict[str, Any] = {}
        baseline_findings: List[BaselineFinding]
        if previous_audit_json is not None:
            audit = load_json_report(previous_audit_json)
            baseline_findings = [
                BaselineFinding.from_json(entry) for entry in audit.get("findings", [])
            ]
            baseline_meta = {
                "source": "previous_audit_json",
                "path": str(previous_audit_json),
                "generated_at": audit.get("generated_at"),
                "source_path": (audit.get("workbook") or {}).get("source_path"),
                "source_sha256": (audit.get("workbook") or {}).get("source_sha256"),
                "finding_count": len(baseline_findings),
            }
            if baseline_xml is not None:
                baseline_meta["baseline_xml"] = str(baseline_xml)
        else:
            baseline_workbook = self.parse(baseline_xml)  # type: ignore[arg-type]
            baseline_findings = [
                BaselineFinding.from_finding(f) for f in self.engine.execute(baseline_workbook)
            ]
            baseline_meta = {
                "source": "baseline_xml",
                "path": str(baseline_xml),
                "source_path": baseline_workbook.source_path,
                "source_sha256": baseline_workbook.source_sha256,
                "finding_count": len(baseline_findings),
            }

        comparisons = self.compare(baseline_findings, revised_findings)

        report = VerificationReport(
            baseline=baseline_meta,
            revised={
                "name": revised_workbook.name,
                "source_path": revised_workbook.source_path,
                "source_sha256": revised_workbook.source_sha256,
                "counts": revised_workbook.as_dict()["counts"],
            },
            rule_repository=self.repository.as_dict(),
            comparisons=comparisons,
            revised_findings=revised_findings,
        )

        if self.checklist is not None:
            report.checklist = build_checklist_results(
                self.checklist, revised_findings, evaluated_rule_ids=self.repository.rule_ids
            )
            report.rule_repository["checklist"] = checklist_metadata(self.checklist)

        if sme_feedback_path is not None:
            report.sme_feedback = load_sme_feedback(sme_feedback_path)
            report.comparisons.extend(self._sme_comparisons(report.sme_feedback, revised_findings))

        return report

    # -- comparison --------------------------------------------------------
    def compare(
        self, baseline: Sequence[BaselineFinding], revised: Sequence[Finding]
    ) -> List[Comparison]:
        """Match baseline and revised findings and classify every difference."""
        baseline_by_key = {b.key: b for b in baseline}
        revised_by_key = {r.key: r for r in revised}
        keys = list(baseline_by_key) + [k for k in revised_by_key if k not in baseline_by_key]

        comparisons: List[Comparison] = []
        for key in keys:
            before = baseline_by_key.get(key)
            after = revised_by_key.get(key)
            comparison = self._classify(key, before, after)
            if comparison is not None:
                comparisons.append(comparison)
        return comparisons

    def _classify(
        self, key: str, before: Optional[BaselineFinding], after: Optional[Finding]
    ) -> Optional[Comparison]:
        if before is not None and after is not None:
            return self._classify_matched(key, before, after)
        if before is not None:
            if before.status in (Status.PASS, Status.NOT_APPLICABLE):
                return None
            return self._comparison(
                key,
                before,
                None,
                VerificationStatus.CANNOT_VERIFY,
                note=(
                    "The object cited in the baseline no longer exists in the revised workbook, "
                    "so the fix cannot be verified automatically."
                ),
            )
        assert after is not None
        if after.status is Status.FAIL:
            return self._comparison(
                key,
                None,
                after,
                VerificationStatus.NEW_FAILURE,
                note="Object is new in the revised workbook and violates the standard.",
            )
        if after.status is Status.MANUAL_REVIEW:
            return self._comparison(
                key,
                None,
                after,
                VerificationStatus.CANNOT_VERIFY,
                note="Object is new in the revised workbook and requires manual verification.",
            )
        if after.status is Status.PASS:
            return self._comparison(
                key,
                None,
                after,
                VerificationStatus.UNCHANGED_PASS,
                note="Object is new in the revised workbook and complies with the standard.",
            )
        return None

    def _classify_matched(
        self, key: str, before: BaselineFinding, after: Finding
    ) -> Comparison:
        after_status = after.status
        note = ""

        if before.status is Status.FAIL:
            if after_status is Status.PASS:
                verification = VerificationStatus.RESOLVED
                note = "The cited issue no longer reproduces."
            elif after_status is Status.FAIL:
                before_failed = _failed_fields(before.evidence)
                after_failed = _failed_fields([e.as_dict() for e in after.evidence])
                if before_failed and after_failed < before_failed:
                    verification = VerificationStatus.PARTIALLY_RESOLVED
                    note = (
                        "Fixed: "
                        + ", ".join(sorted(before_failed - after_failed))
                        + "; still failing: "
                        + ", ".join(sorted(after_failed))
                    )
                else:
                    verification = VerificationStatus.UNRESOLVED
                    note = "The cited issue still reproduces."
            elif after_status is Status.MANUAL_REVIEW:
                verification = VerificationStatus.CANNOT_VERIFY
                note = "The required value is no longer declared in the XML; verify manually."
            else:
                verification = VerificationStatus.CANNOT_VERIFY
                note = "The rule no longer applies to this object; verify manually."
        elif before.status is Status.MANUAL_REVIEW:
            if after_status is Status.PASS:
                verification = VerificationStatus.RESOLVED
                note = "Previously unverifiable; the revised workbook now evidences compliance."
            elif after_status is Status.FAIL:
                verification = VerificationStatus.UNRESOLVED
                note = "Previously unverifiable; the revised workbook evidences a violation."
            else:
                verification = VerificationStatus.CANNOT_VERIFY
                note = "Still not verifiable from the workbook XML."
        else:  # baseline PASS or NOT_APPLICABLE
            if after_status is Status.FAIL:
                verification = VerificationStatus.NEW_FAILURE
                note = "This check passed in the baseline and fails in the revised workbook."
            elif after_status is Status.PASS:
                verification = VerificationStatus.UNCHANGED_PASS
            elif after_status is Status.MANUAL_REVIEW:
                verification = VerificationStatus.CANNOT_VERIFY
                note = "Previously evidenced; the revised workbook no longer declares the value."
            else:
                verification = VerificationStatus.UNCHANGED_PASS
                note = "The rule does not apply to this object in either version."

        return self._comparison(key, before, after, verification, note=note)

    def _comparison(
        self,
        key: str,
        before: Optional[BaselineFinding],
        after: Optional[Finding],
        verification: VerificationStatus,
        *,
        note: str = "",
    ) -> Comparison:
        reference = after or before
        assert reference is not None
        return Comparison(
            key=key,
            rule_id=reference.rule_id,
            title=reference.title,
            target_type=reference.target_type,
            target_id=reference.target_id,
            verification=verification,
            baseline_status=before.status if before else None,
            revised_status=after.status if after else None,
            baseline_evidence=list(before.evidence) if before else [],
            revised_evidence=[e.as_dict() for e in after.evidence] if after else [],
            severity=(after.severity.value if after else (before.severity if before else None)),
            category=(after.category if after else (before.category if before else None)),
            recommendation=(
                after.recommendation if after and after.recommendation else (before.recommendation if before else None)
            ),
            checklist_ref=(after.checklist_ref if after else (before.checklist_ref if before else None)),
            note=note,
        )

    def _sme_comparisons(
        self, feedback: Sequence[SMEFeedbackItem], revised: Sequence[Finding]
    ) -> List[Comparison]:
        """Fold SME comments into the verification view as explicit manual items."""
        revised_by_rule: Dict[str, List[Finding]] = {}
        for finding in revised:
            revised_by_rule.setdefault(finding.rule_id, []).append(finding)

        comparisons: List[Comparison] = []
        for index, item in enumerate(feedback, start=1):
            matched = [
                f
                for f in revised_by_rule.get(item.rule_id or "", [])
                if item.target_id is None or f.target_id == item.target_id
            ]
            if matched:
                worst = max(matched, key=lambda f: f.status.rank)
                verification = (
                    VerificationStatus.RESOLVED
                    if worst.status is Status.PASS
                    else VerificationStatus.UNRESOLVED
                    if worst.status is Status.FAIL
                    else VerificationStatus.CANNOT_VERIFY
                )
                comparisons.append(
                    Comparison(
                        key=f"SME-{index:03d}::{worst.key}",
                        rule_id=worst.rule_id,
                        title=f"SME feedback: {item.comment}",
                        target_type=worst.target_type,
                        target_id=worst.target_id,
                        verification=verification,
                        baseline_status=Status.MANUAL_REVIEW,
                        revised_status=worst.status,
                        revised_evidence=[e.as_dict() for e in worst.evidence],
                        severity=worst.severity.value,
                        category=worst.category,
                        recommendation=worst.recommendation,
                        checklist_ref=worst.checklist_ref,
                        note=f"Raised by {item.author or 'SME'}.",
                    )
                )
            else:
                comparisons.append(
                    Comparison(
                        key=f"SME-{index:03d}",
                        rule_id=item.rule_id or "SME",
                        title=f"SME feedback: {item.comment}",
                        target_type="sme_feedback",
                        target_id=item.target_id or "n/a",
                        verification=VerificationStatus.CANNOT_VERIFY,
                        baseline_status=Status.MANUAL_REVIEW,
                        revised_status=None,
                        note=(
                            "No automated rule covers this comment; the reviewer must confirm "
                            "the change manually."
                        ),
                    )
                )
        return comparisons

    # -- export ------------------------------------------------------------
    def run_and_export(
        self,
        revised_xml: PathLike,
        *,
        baseline_xml: Optional[PathLike] = None,
        previous_audit_json: Optional[PathLike] = None,
        sme_feedback_path: Optional[PathLike] = None,
        output_dir: PathLike = DEFAULT_OUTPUT_DIR,
        basename: Optional[str] = None,
        write_json: bool = True,
        write_excel: bool = True,
        write_pdf: bool = False,
    ) -> tuple[VerificationReport, ReviewArtifacts]:
        report = self.run(
            revised_xml,
            baseline_xml=baseline_xml,
            previous_audit_json=previous_audit_json,
            sme_feedback_path=sme_feedback_path,
        )
        stem = basename or Path(revised_xml).stem
        out_dir = Path(output_dir)
        artifacts = ReviewArtifacts()

        if write_json:
            artifacts.json_path = write_json_report(report, out_dir / f"{stem}_post_review.json")
        if write_excel:
            writer = ExcelReportWriter(self.excel_template)
            artifacts.excel_path = writer.write_verification(
                report, out_dir / f"{stem}_post_review.xlsx"
            )
        if write_pdf:
            artifacts.pdf_path = write_pdf_report(report, out_dir / f"{stem}_post_review.pdf")
        return report, artifacts
