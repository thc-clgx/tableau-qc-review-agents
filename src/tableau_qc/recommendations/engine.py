"""Deterministic recommendation layer.

Recommendations are derived from the YAML rule definition plus the observed
evidence. An optional LLM provider may add *advisory* phrasing, but it can
never change an objective PASS/FAIL outcome and never receives workbook XML.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from ..domain.findings import Finding, Status
from .llm import LLMProvider, NullLLMProvider, build_llm_payload


@dataclass
class Recommendation:
    rule_id: str
    finding_key: str
    target: str
    severity: str
    action: str
    evidence: List[str]
    advisory: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "finding_key": self.finding_key,
            "target": self.target,
            "severity": self.severity,
            "action": self.action,
            "evidence": self.evidence,
            "advisory": self.advisory,
        }


class RecommendationEngine:
    """Builds reviewer-facing remediation text from findings."""

    def __init__(self, llm_provider: Optional[LLMProvider] = None) -> None:
        self.llm_provider: LLMProvider = llm_provider or NullLLMProvider()

    def build(self, findings: Sequence[Finding]) -> List[Recommendation]:
        actionable = [f for f in findings if f.status in (Status.FAIL, Status.MANUAL_REVIEW)]
        recommendations = [self._build_one(f) for f in actionable]

        if self.llm_provider.enabled and recommendations:
            payload = build_llm_payload(actionable)
            advisories = self.llm_provider.suggest(payload)
            for recommendation in recommendations:
                advisory = advisories.get(recommendation.finding_key)
                if advisory:
                    recommendation.advisory = advisory
        return recommendations

    def apply(self, findings: Sequence[Finding]) -> List[Finding]:
        """Attach the rendered recommendation text back onto each finding."""
        by_key = {r.finding_key: r for r in self.build(findings)}
        for finding in findings:
            recommendation = by_key.get(finding.key)
            if recommendation is None:
                continue
            text = recommendation.action
            if recommendation.advisory:
                text = f"{text} [advisory: {recommendation.advisory}]"
            finding.recommendation = text
        return list(findings)

    def _build_one(self, finding: Finding) -> Recommendation:
        evidence_lines = [
            f"{e.summary()} @ {e.source.xpath if e.source else 'n/a'}"
            for e in finding.evidence
            if e.note != "context"
        ]
        base = " ".join((finding.recommendation or finding.title).split())
        if finding.status is Status.MANUAL_REVIEW:
            action = f"Manual verification required. {base}"
        else:
            action = base
        return Recommendation(
            rule_id=finding.rule_id,
            finding_key=finding.key,
            target=finding.where,
            severity=finding.severity.value,
            action=action,
            evidence=evidence_lines,
        )
