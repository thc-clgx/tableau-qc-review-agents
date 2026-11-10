"""Findings, evidence and review-result model shared by both agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

from .models import SourceRef


class Status(str, Enum):
    """Outcome of a QC check."""

    PASS = "PASS"
    FAIL = "FAIL"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @property
    def rank(self) -> int:
        """Severity ordering used when aggregating statuses."""
        return _STATUS_RANK[self]


_STATUS_RANK = {
    Status.NOT_APPLICABLE: 0,
    Status.PASS: 1,
    Status.MANUAL_REVIEW: 2,
    Status.FAIL: 3,
}


def aggregate_status(statuses: Iterable[Status]) -> Status:
    """Worst-case aggregation: FAIL > MANUAL_REVIEW > PASS > NOT_APPLICABLE."""
    worst = Status.NOT_APPLICABLE
    for status in statuses:
        if status.rank > worst.rank:
            worst = status
    return worst


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass(frozen=True)
class Evidence:
    """Immutable proof for an automated decision.

    Every automated PASS/FAIL must carry at least one evidence item.
    """

    field_path: str
    operator: Optional[str] = None
    expected: Any = None
    observed: Any = None
    source: Optional[SourceRef] = None
    note: Optional[str] = None
    observed_available: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field_path,
            "operator": self.operator,
            "expected": self.expected,
            "observed": self.observed,
            "observed_available": self.observed_available,
            "xpath": self.source.xpath if self.source else None,
            "attribute": self.source.attribute if self.source else None,
            "note": self.note,
        }

    def summary(self) -> str:
        if not self.observed_available:
            return f"{self.field_path} not declared in XML"
        return f"{self.field_path}={self.observed!r} (expected {self.operator} {self.expected!r})"


@dataclass
class Finding:
    """Result of evaluating one rule against one target object."""

    rule_id: str
    title: str
    status: Status
    target_type: str
    target_id: str
    target_name: Optional[str] = None
    target_location: Optional[str] = None
    category: Optional[str] = None
    severity: Severity = Severity.MEDIUM
    message: str = ""
    evidence: List[Evidence] = field(default_factory=list)
    recommendation: Optional[str] = None
    checklist_ref: Optional[str] = None
    standard_ref: Optional[str] = None
    automated: bool = True
    tags: List[str] = field(default_factory=list)

    @property
    def where(self) -> str:
        """Readable location, e.g. 'Exec Summary > Performance Details'."""
        name = self.target_name or self.target_id
        if self.target_location and self.target_location != name:
            return f"{self.target_location} > {name}"
        return name

    @property
    def key(self) -> str:
        """Stable identity used to match baseline and revised findings."""
        return f"{self.rule_id}::{self.target_type}::{self.target_id}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "key": self.key,
            "title": self.title,
            "status": self.status.value,
            "severity": self.severity.value,
            "category": self.category,
            "target": {
                "type": self.target_type,
                "id": self.target_id,
                "name": self.target_name,
                "location": self.target_location,
                "where": self.where,
            },
            "message": self.message,
            "evidence": [e.as_dict() for e in self.evidence],
            "recommendation": self.recommendation,
            "checklist_ref": self.checklist_ref,
            "standard_ref": self.standard_ref,
            "automated": self.automated,
            "tags": self.tags,
        }


@dataclass
class ChecklistResult:
    """A checklist question answered by zero or more rules."""

    item_id: str
    section: Optional[str]
    question: str
    status: Status
    sheet: Optional[str] = None
    cell: Optional[str] = None
    rule_ids: List[str] = field(default_factory=list)
    recommendation: str = ""
    evidence_summary: str = ""
    automated: bool = False

    @property
    def pass_flag(self) -> str:
        """Binary answer for the review checklist.

        NOT_APPLICABLE reports ``Y``: when a workbook contains nothing the rule
        could apply to, it cannot violate the standard. MANUAL_REVIEW reports
        ``N`` because compliance has not been demonstrated - the reason is
        carried in the Recommended Changes column.
        """
        return "Y" if self.status in (Status.PASS, Status.NOT_APPLICABLE) else "N"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "section": self.section,
            "question": self.question,
            "status": self.status.value,
            "pass_flag": self.pass_flag,
            "sheet": self.sheet,
            "cell": self.cell,
            "rule_ids": self.rule_ids,
            "recommendation": self.recommendation,
            "evidence_summary": self.evidence_summary,
            "automated": self.automated,
        }


@dataclass
class ReviewReport:
    """Complete output of Agent 1 (pre-technical review)."""

    report_type: str = "PRE_TECHNICAL_REVIEW"
    schema_version: str = "1.0"
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    workbook: Dict[str, Any] = field(default_factory=dict)
    rule_repository: Dict[str, Any] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    checklist: List[ChecklistResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def findings_by_status(self, status: Status) -> List[Finding]:
        return [f for f in self.findings if f.status is status]

    @property
    def summary(self) -> Dict[str, Any]:
        by_status = {s.value: len(self.findings_by_status(s)) for s in Status}
        by_severity: Dict[str, int] = {}
        for finding in self.findings:
            if finding.status is Status.FAIL:
                by_severity[finding.severity.value] = by_severity.get(finding.severity.value, 0) + 1
        rule_statuses: Dict[str, Status] = {}
        for finding in self.findings:
            current = rule_statuses.get(finding.rule_id)
            rule_statuses[finding.rule_id] = (
                finding.status if current is None else aggregate_status([current, finding.status])
            )
        return {
            "total_findings": len(self.findings),
            "by_status": by_status,
            "failed_by_severity": by_severity,
            "rules_evaluated": len(rule_statuses),
            "rules_failed": len([s for s in rule_statuses.values() if s is Status.FAIL]),
            "overall_status": aggregate_status([f.status for f in self.findings]).value,
        }

    def as_dict(self) -> Dict[str, Any]:
        return {
            "report_type": self.report_type,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "workbook": self.workbook,
            "rule_repository": self.rule_repository,
            "summary": self.summary,
            "findings": [f.as_dict() for f in self.findings],
            "checklist": [c.as_dict() for c in self.checklist],
            "errors": self.errors,
        }
