"""Comparison model used by Agent 2 (post-technical review verification)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .findings import ChecklistResult, Finding, Status


class VerificationStatus(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    CANNOT_VERIFY = "CANNOT_VERIFY"
    NEW_FAILURE = "NEW_FAILURE"
    UNCHANGED_PASS = "UNCHANGED_PASS"


@dataclass
class SMEFeedbackItem:
    """Optional reviewer comment carried into the verification report."""

    comment: str
    rule_id: Optional[str] = None
    target_id: Optional[str] = None
    author: Optional[str] = None
    raised_on: Optional[str] = None
    status: Status = Status.MANUAL_REVIEW

    def as_dict(self) -> Dict[str, Any]:
        return {
            "comment": self.comment,
            "rule_id": self.rule_id,
            "target_id": self.target_id,
            "author": self.author,
            "raised_on": self.raised_on,
            "status": self.status.value,
        }


@dataclass
class Comparison:
    """Baseline vs revised outcome for a single finding key."""

    key: str
    rule_id: str
    title: str
    target_type: str
    target_id: str
    verification: VerificationStatus
    baseline_status: Optional[Status] = None
    revised_status: Optional[Status] = None
    baseline_evidence: List[Dict[str, Any]] = field(default_factory=list)
    revised_evidence: List[Dict[str, Any]] = field(default_factory=list)
    severity: Optional[str] = None
    category: Optional[str] = None
    recommendation: Optional[str] = None
    checklist_ref: Optional[str] = None
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "rule_id": self.rule_id,
            "title": self.title,
            "target": {"type": self.target_type, "id": self.target_id},
            "verification": self.verification.value,
            "baseline_status": self.baseline_status.value if self.baseline_status else None,
            "revised_status": self.revised_status.value if self.revised_status else None,
            "evidence": {"before": self.baseline_evidence, "after": self.revised_evidence},
            "severity": self.severity,
            "category": self.category,
            "recommendation": self.recommendation,
            "checklist_ref": self.checklist_ref,
            "note": self.note,
        }


@dataclass
class VerificationReport:
    """Complete output of Agent 2."""

    report_type: str = "POST_TECHNICAL_REVIEW"
    schema_version: str = "1.0"
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    baseline: Dict[str, Any] = field(default_factory=dict)
    revised: Dict[str, Any] = field(default_factory=dict)
    rule_repository: Dict[str, Any] = field(default_factory=dict)
    comparisons: List[Comparison] = field(default_factory=list)
    revised_findings: List[Finding] = field(default_factory=list)
    checklist: List[ChecklistResult] = field(default_factory=list)
    sme_feedback: List[SMEFeedbackItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def by_verification(self, status: VerificationStatus) -> List[Comparison]:
        return [c for c in self.comparisons if c.verification is status]

    @property
    def summary(self) -> Dict[str, Any]:
        counts = {s.value: len(self.by_verification(s)) for s in VerificationStatus}
        return {
            "total_comparisons": len(self.comparisons),
            "by_verification": counts,
            "new_failure_count": counts[VerificationStatus.NEW_FAILURE.value],
            "unresolved_count": counts[VerificationStatus.UNRESOLVED.value]
            + counts[VerificationStatus.PARTIALLY_RESOLVED.value],
            "sign_off_ready": counts[VerificationStatus.UNRESOLVED.value] == 0
            and counts[VerificationStatus.PARTIALLY_RESOLVED.value] == 0
            and counts[VerificationStatus.NEW_FAILURE.value] == 0,
        }

    def as_dict(self) -> Dict[str, Any]:
        return {
            "report_type": self.report_type,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "baseline": self.baseline,
            "revised": self.revised,
            "rule_repository": self.rule_repository,
            "summary": self.summary,
            "comparisons": [c.as_dict() for c in self.comparisons],
            "revised_findings": [f.as_dict() for f in self.revised_findings],
            "checklist": [c.as_dict() for c in self.checklist],
            "sme_feedback": [s.as_dict() for s in self.sme_feedback],
            "errors": self.errors,
        }
